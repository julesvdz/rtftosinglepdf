"""
modules/libreoffice.py
----------------------
Autodetects the LibreOffice `soffice` binary and runs headless RTF → PDF
conversion via subprocess.

Autodetection order:
  1. shutil.which('soffice')          — works on Linux/macOS after PATH install
  2. shutil.which('soffice.exe')      — Windows PATH
  3. Hardcoded common Windows paths   — Program Files variants
  4. Hardcoded common Linux paths     — /usr/bin, /usr/lib/...
  5. macOS application bundle path
  6. Raises RuntimeError if not found
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import config


# ---------------------------------------------------------------------------
# Candidate paths probed during autodetection
# ---------------------------------------------------------------------------
_WINDOWS_CANDIDATES: list[str] = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"C:\Program Files\LibreOffice 7\program\soffice.exe",
    r"C:\Program Files\LibreOffice 24\program\soffice.exe",
    r"C:\Program Files\LibreOffice 25\program\soffice.exe",
]

_LINUX_CANDIDATES: list[str] = [
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/opt/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
]

_MACOS_CANDIDATES: list[str] = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def find_soffice() -> str:
    """Return the absolute path to the soffice binary.

    Raises
    ------
    RuntimeError
        If no LibreOffice installation is found on the system.
    """
    # 1 & 2: check PATH first
    for name in ("soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found

    # 3–5: platform-specific candidate list
    if sys.platform.startswith("win"):
        candidates = _WINDOWS_CANDIDATES
    elif sys.platform == "darwin":
        candidates = _MACOS_CANDIDATES
    else:
        candidates = _LINUX_CANDIDATES

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise RuntimeError(
        "LibreOffice (soffice) not found. "
        "Install LibreOffice and ensure it is accessible, "
        "or add its 'program' directory to your PATH."
    )


def _timeout_for(rtf_path: Path) -> int:
    """Return a per-file timeout scaled to the RTF file size."""
    try:
        size_mb = rtf_path.stat().st_size / 1_000_000
    except OSError:
        size_mb = 0.0
    return max(config.LIBREOFFICE_TIMEOUT_MIN, int(size_mb * config.LIBREOFFICE_TIMEOUT_PER_MB))


def convert_rtf_to_pdf(
    rtf_path: str | Path,
    output_dir: str | Path,
    soffice_path: str | None = None,
    user_profile_dir: str | Path | None = None,
) -> Path:
    """Convert a single RTF file to PDF using LibreOffice headless mode.

    Parameters
    ----------
    rtf_path:
        Absolute or relative path to the source RTF file.
    output_dir:
        Directory where LibreOffice will write the resulting PDF.
    soffice_path:
        Explicit path to soffice binary. Autodetected when None.
    user_profile_dir:
        Path to an isolated LibreOffice user-profile directory. Required when
        running multiple soffice instances concurrently — without per-instance
        isolation the processes corrupt each other's lock files. Leave None
        for single-threaded (sequential) callers.

    Returns
    -------
    Path
        Absolute path to the generated PDF file.

    Raises
    ------
    FileNotFoundError
        When the RTF source file does not exist.
    RuntimeError
        When LibreOffice reports a non-zero exit code or the expected PDF
        is not produced.
    """
    rtf_path = Path(rtf_path).resolve()
    output_dir = Path(output_dir).resolve()

    if not rtf_path.exists():
        raise FileNotFoundError(f"RTF file not found: {rtf_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    exe = soffice_path or find_soffice()

    cmd: list[str] = [
        exe,
        "--headless",
        "--norestore",
        "--nofirststartwizard",
    ]

    if user_profile_dir is not None:
        profile_uri = Path(user_profile_dir).resolve().as_uri()
        cmd.append(f"-env:UserInstallation={profile_uri}")

    cmd += [
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(rtf_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_timeout_for(rtf_path),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed for '{rtf_path.name}'.\n"
            f"STDOUT: {result.stdout.strip()}\n"
            f"STDERR: {result.stderr.strip()}"
        )

    expected_pdf = output_dir / (rtf_path.stem + ".pdf")
    if not expected_pdf.exists():
        raise RuntimeError(
            f"LibreOffice ran successfully but the expected PDF was not "
            f"produced: {expected_pdf}"
        )

    return expected_pdf
