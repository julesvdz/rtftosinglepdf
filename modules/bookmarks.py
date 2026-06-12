"""
modules/bookmarks.py
--------------------
Modular PDF bookmark (outline) injection using PyMuPDF.

Design principles
-----------------
* The public API accepts a list of dicts so callers are decoupled from any
  specific data class.
* Each dict must contain at minimum:
      "title"      : str   — bookmark display text
      "page_index" : int   — 0-based target page in the final document
  Optional keys:
      "level"      : int   — outline depth (default 1 = flat)
      "table_number": str  — prepended to title when non-empty

  Keeping "level" in the dict structure means that switching to a nested
  hierarchy in the future requires only changes to how callers populate that
  key — this function does not need to change.

* PyMuPDF TOC format:  [level, title, page_number_1based]
  (page_number is 1-based in PyMuPDF's set_toc API)

Usage
-----
    from modules.bookmarks import build_toc_list, inject_bookmarks

    entries = [
        {"title": "Adverse Events", "page_index": 4, "table_number": "14.1.1"},
        {"title": "Vital Signs",    "page_index": 22, "table_number": "14.2.1"},
    ]
    toc = build_toc_list(entries)
    inject_bookmarks(doc, toc)
"""

from __future__ import annotations

from typing import Any

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_toc_list(
    entries: list[dict[str, Any]],
    default_level: int = 1,
) -> list[list]:
    """Convert entry dicts to PyMuPDF TOC format.

    Parameters
    ----------
    entries:
        List of dicts; each must have ``"title"`` and ``"page_index"``.
        Optional: ``"level"`` (int, default 1), ``"table_number"`` (str).
    default_level:
        Fallback outline level when an entry has no ``"level"`` key.
        Use 1 for flat structure (all entries at the same depth).

    Returns
    -------
    list[list]
        PyMuPDF TOC list — each element is ``[level, title_str, page_1based]``.

    Notes
    -----
    To build a nested structure in the future, populate the ``"level"``
    key in each entry dict (e.g. 1 for top-level, 2 for subsection) and
    call this function without any other changes.
    """
    toc: list[list] = []

    for entry in entries:
        level: int = int(entry.get("level", default_level))
        page_0: int = int(entry["page_index"])
        title: str = _format_title(entry)

        # PyMuPDF expects 1-based page numbers in set_toc
        toc.append([level, title, page_0 + 1])

    return toc


def inject_bookmarks(doc: fitz.Document, toc: list[list]) -> None:
    """Write a PyMuPDF TOC list into *doc* as PDF bookmarks (outline).

    This operation is in-place. The existing outline (if any) is replaced.

    Parameters
    ----------
    doc:
        Open, writable PyMuPDF Document.
    toc:
        TOC list as returned by :func:`build_toc_list`.
    """
    if not toc:
        return
    doc.set_toc(toc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_title(entry: dict[str, Any]) -> str:
    """Compose the bookmark display string from entry fields.

    If ``table_number`` is present and non-empty, it is prepended:
    ``"14.1.1  Summary of Adverse Events"``
    """
    raw_title: str = str(entry.get("title", "")).strip()
    table_num: str = str(entry.get("table_number", "")).strip()

    if table_num:
        return f"{table_num}  {raw_title}"
    return raw_title
