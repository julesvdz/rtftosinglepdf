"""
modules/page_numbering.py
-------------------------
Overlays "Page X of Y" master page numbers onto every page of the final
compiled PDF document using PyMuPDF.

Coordinate origin: top-left corner of the page (PDF default).
All position and size values are in points (1 pt = 1/72 inch).

Coordinates are read from config.py for easy future adjustment.
Optionally, callers may pass overrides (e.g. values loaded from a saved
JSON config) via the `overlay_config` parameter.
"""

from __future__ import annotations

from typing import Any

import fitz  # PyMuPDF

import config


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_master_page_numbers(
    doc: fitz.Document,
    toc_page_count: int = 0,
    overlay_config: dict[str, Any] | None = None,
) -> None:
    """Stamp "Page X of Y" on every page of *doc* in-place.

    The overlay is inserted at the coordinate specified in :mod:`config`
    (or overridden via *overlay_config*). Text is right-aligned to the X
    position so it does not overflow into the right margin.

    Parameters
    ----------
    doc:
        Open, writable PyMuPDF Document (all pages are stamped).
    toc_page_count:
        Number of leading ToC pages already included in *doc*.  Kept as a
        parameter for future use (e.g. if ToC pages should show "ToC n/m"
        rather than "Page X of Y").  Currently, all pages — including ToC
        pages — receive the same "Page X of Y" treatment.
    overlay_config:
        Optional dict with override keys:
          - ``page_number_bottom_margin_pts`` (float) — pts from bottom of page
          - ``page_number_right_margin_pts``  (float) — pts from right edge of page
          - ``page_number_font_size``         (int)
    """
    cfg = overlay_config or {}

    # Margins from page edges — absolute Y and X are computed per page so the
    # overlay stays in bounds on any paper size or orientation.
    bottom_margin: float = float(cfg.get("page_number_bottom_margin_pts", config.PAGE_NUMBER_BOTTOM_MARGIN))
    right_margin:  float = float(cfg.get("page_number_right_margin_pts",  config.PAGE_NUMBER_RIGHT_MARGIN))
    font_size: int = int(cfg.get("page_number_font_size", config.PAGE_NUMBER_FONT_SIZE))
    font_name: str = config.PAGE_NUMBER_FONT
    color: tuple = config.PAGE_NUMBER_COLOR

    total_pages: int = doc.page_count

    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = f"Page {page_idx + 1} of {total_pages}"
        _insert_right_aligned_text(
            page=page,
            text=text,
            right_x=page.rect.width - right_margin,
            y=page.rect.height - bottom_margin,
            font_name=font_name,
            font_size=font_size,
            color=color,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_right_aligned_text(
    page: fitz.Page,
    text: str,
    right_x: float,
    y: float,
    font_name: str,
    font_size: int,
    color: tuple,
) -> None:
    """Insert text so that its right edge aligns with *right_x*.

    PyMuPDF's insert_text places text with its *left* edge at the given x.
    We approximate the text width to shift left accordingly.

    For Helvetica at a given point size, character width ≈ font_size * 0.5
    (rough average for mixed alphanumeric glyphs).  This is sufficient for
    a short "Page XX of YYY" string; a proper measurement via
    ``page.get_text_length()`` is used when available.
    """
    try:
        # PyMuPDF ≥ 1.18 provides get_text_length for precise measurement
        width = fitz.get_text_length(text, fontname=font_name, fontsize=font_size)
    except AttributeError:
        # Fallback: approximate
        width = len(text) * font_size * 0.50

    insert_x = right_x - width
    if insert_x < 0:
        insert_x = 0.0

    page.insert_text(
        point=fitz.Point(insert_x, y),
        text=text,
        fontname=font_name,
        fontsize=font_size,
        color=color,
    )
