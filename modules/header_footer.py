"""
modules/header_footer.py
------------------------
Overlays configurable header and footer text onto every page of the final
compiled PDF document using PyMuPDF.

Layout model
------------
Each header/footer band has three text slots — Left, Center, Right — that
are placed at a configurable Y coordinate (distance from the top of the page
in points).

    Left text    → inserted at x = LEFT_MARGIN
    Center text  → centred on the page width
    Right text   → right edge aligned to x = page_width - RIGHT_MARGIN

All coordinate defaults are read from config.py; callers may pass an
`overlay_config` dict (typically loaded from the saved JSON config) to
override them at runtime.
"""

from __future__ import annotations

from typing import Any, Callable

import fitz  # PyMuPDF

import config


# ---------------------------------------------------------------------------
# Layout constants (used when not overridden)
# ---------------------------------------------------------------------------
_LEFT_MARGIN: float = 60.0    # pts from left
_RIGHT_MARGIN: float = 60.0   # pts from right


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_headers_and_footers(
    doc: fitz.Document,
    header: dict[str, str],
    footer: dict[str, str],
    overlay_config: dict[str, Any] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> None:
    """Stamp header and footer text on every page of *doc* in-place.

    Parameters
    ----------
    doc:
        Open, writable PyMuPDF Document.
    header:
        Dict with keys ``"left"``, ``"center"``, ``"right"`` — the strings
        to render in the header band.  Empty strings are silently skipped.
    footer:
        Same structure as *header* for the footer band.
    overlay_config:
        Optional dict with override keys from the saved JSON config:
          - ``header_y_pts``  (float) — Y position of header text
          - ``footer_y_pts``  (float) — Y position of footer text
        Falls back to config.py defaults when not supplied.
    progress_cb:
        Optional ``cb(pages_done, total_pages)`` invoked periodically during
        the stamping loop (throttled to ~200 calls per document) so callers
        can surface per-page progress on large documents.
    """
    cfg = overlay_config or {}

    # Margins from page edges — computed as absolute Y per page so the overlay
    # lands correctly on any paper size (A4, Letter) and orientation.
    header_top_margin: float = float(cfg.get("header_top_margin_pts", config.HEADER_TOP_MARGIN))
    footer_bottom_margin: float = float(cfg.get("footer_bottom_margin_pts", config.FOOTER_BOTTOM_MARGIN))

    font_name: str = config.HEADER_FOOTER_FONT
    font_size: int = config.HEADER_FOOTER_FONT_SIZE
    color: tuple = config.HEADER_FOOTER_COLOR

    total_pages: int = doc.page_count
    report_every = max(1, total_pages // 200)

    for page_idx, page in enumerate(doc):
        page_width: float = page.rect.width
        page_height: float = page.rect.height

        # ── Header ──────────────────────────────────────────────────────────
        _draw_band(
            page=page,
            left_text=header.get("left", ""),
            center_text=header.get("center", ""),
            right_text=header.get("right", ""),
            y=header_top_margin,
            page_width=page_width,
            font_name=font_name,
            font_size=font_size,
            color=color,
        )

        # ── Footer ──────────────────────────────────────────────────────────
        _draw_band(
            page=page,
            left_text=footer.get("left", ""),
            center_text=footer.get("center", ""),
            right_text=footer.get("right", ""),
            y=page_height - footer_bottom_margin,
            page_width=page_width,
            font_name=font_name,
            font_size=font_size,
            color=color,
        )

        done = page_idx + 1
        if progress_cb and (done % report_every == 0 or done == total_pages):
            progress_cb(done, total_pages)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _draw_band(
    page: fitz.Page,
    left_text: str,
    center_text: str,
    right_text: str,
    y: float,
    page_width: float,
    font_name: str,
    font_size: int,
    color: tuple,
) -> None:
    """Draw one header or footer band with up to three text slots."""

    if left_text:
        page.insert_text(
            point=fitz.Point(_LEFT_MARGIN, y),
            text=left_text,
            fontname=font_name,
            fontsize=font_size,
            color=color,
        )

    if center_text:
        cx = _center_x(center_text, page_width, font_name, font_size)
        page.insert_text(
            point=fitz.Point(cx, y),
            text=center_text,
            fontname=font_name,
            fontsize=font_size,
            color=color,
        )

    if right_text:
        rx = _right_x(right_text, page_width, font_name, font_size)
        page.insert_text(
            point=fitz.Point(rx, y),
            text=right_text,
            fontname=font_name,
            fontsize=font_size,
            color=color,
        )


def _text_width(text: str, font_name: str, font_size: int) -> float:
    """Return the approximate rendered width of *text* in points."""
    try:
        return fitz.get_text_length(text, fontname=font_name, fontsize=font_size)
    except AttributeError:
        # Fallback approximation for older PyMuPDF builds
        return len(text) * font_size * 0.50


def _center_x(text: str, page_width: float, font_name: str, font_size: int) -> float:
    """Return the x coordinate so that *text* is horizontally centred."""
    w = _text_width(text, font_name, font_size)
    return max(0.0, (page_width - w) / 2.0)


def _right_x(text: str, page_width: float, font_name: str, font_size: int) -> float:
    """Return the x coordinate so that *text*'s right edge is at the right margin."""
    w = _text_width(text, font_name, font_size)
    return max(0.0, page_width - _RIGHT_MARGIN - w)
