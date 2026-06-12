"""
modules/rtf_parser.py
---------------------
Extracts a human-readable title from an RTF file by stripping RTF control
words and returning the first non-blank line of plain text.

Two multi-line title formats are supported:

  Format 1 — \\line separators within one cell:
      {Title Line 1{\\line}Subtitle\\cell}

  Format 2 — two separate rows followed by \\par:
      {Title Line 1\\cell}{\\row}
      {Subtitle\\cell}{\\row}
      \\par

In both cases the first two lines are joined with " | ".

Uses `striprtf` (https://pypi.org/project/striprtf/) as the primary decoder.
Falls back to a simple regex-based control word stripper if striprtf fails.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from striprtf.striprtf import rtf_to_text as _striprtf_decode
    _HAS_STRIPRTF = True
except ImportError:
    _HAS_STRIPRTF = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RTF_CONTROL_WORD_RE = re.compile(
    r"\\[a-zA-Z]+\-?[0-9]*\s?"  # control words  e.g. \par, \fs24
    r"|\\[^a-zA-Z]"              # control symbols e.g. \~, \*
    r"|\{|\}"                    # braces
    r"|[\r\n]+"                  # line breaks
)

# Matches \line (standalone — not \linex, \linespacing, etc.)
_LINE_BREAK_RE = re.compile(r"\{?\\line\}?(?![a-zA-Z])")

# For Format 2 detection
_BKMKEND_RE  = re.compile(r"bkmkend\s+IDX")
_ROW_RE      = re.compile(r"\\row(?![a-zA-Z])")
_SIGWORD_RE  = re.compile(r"\\(par|trowd|cell)(?![a-zA-Z])")


def _is_two_row_title(raw: str) -> bool:
    """Return True when the title occupies two consecutive rows followed by \\par.

    Format 2 structure (after the IDX bookmark):
        \\trowd ... {line 1 \\cell} {\\row}
        \\trowd ... {line 2 \\cell} {\\row}
        \\pard{\\par}          ← \\par comes before any \\trowd / \\cell
    """
    m = _BKMKEND_RE.search(raw)
    body = raw[m.end():] if m else raw

    rows = list(_ROW_RE.finditer(body))
    if len(rows) < 2:
        return False

    # After the second \row the first significant control word must be \par,
    # not \trowd or \cell (which would indicate the title section continues).
    after = body[rows[1].end():]
    sig = _SIGWORD_RE.search(after)
    return sig is not None and sig.group(1) == "par"


def _regex_strip(raw: str) -> str:
    """Minimal regex-based RTF control word stripper used as fallback."""
    # Remove binary blobs introduced by \bin
    raw = re.sub(r"\\bin\d+\s?.*?(?=\\|\{|\})", "", raw, flags=re.DOTALL)
    return _RTF_CONTROL_WORD_RE.sub(" ", raw)


def _plain_text_from_rtf(raw: str) -> str:
    """Return plain text from RTF content string."""
    raw = raw.replace("\\~", " ")           # RTF non-breaking space → plain space
    raw = re.sub(r"\\cell(?![a-zA-Z])", " ", raw)  # table-cell delimiter → space (not \cellx…)
    if _HAS_STRIPRTF:
        try:
            return _striprtf_decode(raw)
        except Exception:
            pass
    # Fallback
    return _regex_strip(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_title(rtf_path: str | Path, max_read_bytes: int = 16_384) -> str:
    """Return the title from an RTF file as a plain-text string.

    When the title contains a ``\\line`` control word (multi-line title), the
    first two non-blank lines are returned joined by ``" | "``.  Otherwise the
    first non-blank line is returned.

    Only the first `max_read_bytes` bytes are read, which is sufficient for
    title extraction on all SAS-generated RTF outputs and avoids loading
    large files entirely into memory.

    Parameters
    ----------
    rtf_path:
        Path to the RTF file.
    max_read_bytes:
        Maximum number of bytes to read from the file head.

    Returns
    -------
    str
        The extracted title string, or the filename stem if no text is found.
    """
    rtf_path = Path(rtf_path)

    try:
        raw_bytes = rtf_path.read_bytes()[:max_read_bytes]
        # RTF files are typically latin-1 or cp1252; decode with replace to
        # handle any unusual byte sequences without raising.
        raw = raw_bytes.decode("cp1252", errors="replace")
    except (OSError, IOError):
        return rtf_path.stem  # safe fallback: use filename

    # Detect multi-line title.
    # Format 1: \line control word present in the raw RTF.
    # Format 2: two separate rows before a \par (no \line).
    is_multiline = (
        len(_LINE_BREAK_RE.split(raw, maxsplit=1)) >= 2
        or _is_two_row_title(raw)
    )

    plain = _plain_text_from_rtf(raw)
    non_blank = [line.strip() for line in plain.splitlines() if line.strip()]

    if not non_blank:
        return rtf_path.stem

    if is_multiline and len(non_blank) >= 2:
        return f"{non_blank[0][:256]} | {non_blank[1][:256]}"

    # Truncate extremely long lines (RTF sometimes runs table content
    # into the first text block)
    return non_blank[0][:256]
