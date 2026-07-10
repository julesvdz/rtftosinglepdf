"""
modules/csv_handler.py
----------------------
Parses the optional CSV mapping file and returns an ordered list of
SectionEntry records that drive document assembly sequence and titles.

Expected CSV schema (header row required, case-insensitive):

    RTF_Filename  | Table_Number | Title
    report01.rtf  | 14.1.1       | Summary of Adverse Events

The delimiter is auto-detected from the file content; comma, semicolon,
tab, and pipe are all recognised.  Rows with a blank RTF_Filename are
silently skipped.  Row order in the CSV dictates final document sequence.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class SectionEntry(NamedTuple):
    """Represents one RTF file's metadata from the CSV mapping."""
    rtf_filename: str     # bare filename, e.g. "report01.rtf"
    table_number: str     # e.g. "14.1.1" — may be empty
    title: str            # display title for ToC and bookmarks — may be
                          # blank; the caller falls back to the RTF-extracted
                          # title for blank values


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS = {"rtf_filename", "title"}

_COLUMN_ALIASES: dict[str, str] = {
    # Maps lowercase CSV header variants → canonical internal key
    "rtf_filename": "rtf_filename",
    "rtf filename": "rtf_filename",
    "filename": "rtf_filename",
    "file": "rtf_filename",
    "table_number": "table_number",
    "table number": "table_number",
    "table_no": "table_number",
    "tableno": "table_number",
    "number": "table_number",
    "title": "title",
    "description": "title",
    "label": "title",
}


def _detect_encoding(csv_path: Path) -> str:
    """Return the encoding to use for csv_path.

    Checks for a UTF-8 BOM, then tries strict UTF-8; falls back to cp1252
    (Windows-1252), which can decode any byte and is the default encoding
    for CSV files saved by Excel on Windows.
    """
    raw = csv_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _normalise_header(raw_header: list[str]) -> dict[str, int]:
    """Map raw CSV column names to canonical keys and their indices."""
    mapping: dict[str, int] = {}
    for idx, col in enumerate(raw_header):
        canonical = _COLUMN_ALIASES.get(col.strip().lower())
        if canonical and canonical not in mapping:
            mapping[canonical] = idx
    return mapping


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_csv(csv_path: str | Path) -> list[SectionEntry]:
    """Parse a CSV mapping file and return ordered SectionEntry list.

    Parameters
    ----------
    csv_path:
        Path to the CSV file.

    Returns
    -------
    list[SectionEntry]
        Entries in CSV row order. Rows with blank RTF_Filename are skipped.

    Raises
    ------
    FileNotFoundError
        When the CSV file does not exist.
    ValueError
        When required columns are missing from the CSV header.
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV mapping file not found: {csv_path}")

    with csv_path.open(newline="", encoding=_detect_encoding(csv_path)) as fh:
        # Auto-detect delimiter from a leading sample; fall back to comma.
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel  # standard comma-separated

        reader = csv.reader(fh, dialect)

        try:
            raw_header = next(reader)
        except StopIteration:
            raise ValueError("CSV file is empty — no header row found.")

        col_map = _normalise_header(raw_header)

        missing = _REQUIRED_COLUMNS - set(col_map.keys())
        if missing:
            raise ValueError(
                f"CSV is missing required column(s): {', '.join(sorted(missing))}.\n"
                f"Found columns: {[h.strip() for h in raw_header]}"
            )

        entries: list[SectionEntry] = []
        for lineno, row in enumerate(reader, start=2):
            if not row:
                continue

            def _get(key: str, default: str = "") -> str:
                idx = col_map.get(key)
                if idx is None or idx >= len(row):
                    return default
                return row[idx].strip()

            rtf_filename = _get("rtf_filename")
            if not rtf_filename:
                continue  # skip blank rows

            entries.append(SectionEntry(
                rtf_filename=rtf_filename,
                table_number=_get("table_number"),
                title=_get("title"),
            ))

    return entries


def resolve_entries_against_directory(
    entries: list[SectionEntry],
    rtf_dir: str | Path,
) -> list[tuple[SectionEntry, Path]]:
    """Pair each SectionEntry with its resolved RTF file Path.

    Parameters
    ----------
    entries:
        Ordered list from :func:`parse_csv`.
    rtf_dir:
        Directory that should contain the RTF files.

    Returns
    -------
    list[tuple[SectionEntry, Path]]
        Only entries whose RTF file exists are returned; missing files are
        silently skipped (callers should log warnings via process_logger).
    """
    rtf_dir = Path(rtf_dir)
    resolved: list[tuple[SectionEntry, Path]] = []

    for entry in entries:
        candidate = rtf_dir / entry.rtf_filename
        if candidate.exists():
            resolved.append((entry, candidate))

    return resolved
