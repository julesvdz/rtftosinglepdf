"""
modules/toc_generator.py
------------------------
Generates a hyperlinked Table of Contents (ToC) as one or more PDF pages
that are prepended to the final compiled document.

Algorithm
---------
Page count is computed analytically (``ceil(N / entries_per_page)``).
This is always exact because every entry occupies exactly one fixed-height
row — ``insert_text`` never wraps, and long labels are truncated before
insertion.  The ToC is therefore rendered once with the correct page offset
applied immediately.  Clickable internal links are injected afterwards via
:func:`inject_toc_links` once the ToC pages are prepended into the final doc.

Public API
----------
    toc_doc, toc_page_count = build_toc(sections, page_rect)
    # toc_doc  — fitz.Document containing only the ToC pages
    # toc_page_count — how many pages it took (used for master page offset)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import fitz  # PyMuPDF

import config
from modules.pdf_merger import SectionInfo


# Characters outside Latin-1 that PyMuPDF's built-in fonts cannot render —
# substituted with their closest ASCII equivalents before drawing.
_LATIN1_SAFE = str.maketrans({
    '–': '-',   # en dash
    '—': '-',   # em dash
    '‘': "'",   # left single quotation mark
    '’': "'",   # right single quotation mark
    '“': '"',   # left double quotation mark
    '”': '"',   # right double quotation mark
    '…': '...',  # horizontal ellipsis
})


def _latin1_safe(text: str) -> str:
    return text.translate(_LATIN1_SAFE)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _entries_per_page(page_rect: fitz.Rect) -> int:
    """Calculate how many ToC lines fit on one page."""
    usable_height = page_rect.height - config.TOC_TOP_MARGIN - 60.0  # bottom margin
    return max(1, int(usable_height / config.TOC_LINE_HEIGHT))


def _estimate_toc_pages(num_entries: int, entries_per_page: int) -> int:
    """Return the number of pages required to hold all ToC entries."""
    # +1 for the heading row reserved on page 1
    return max(1, math.ceil(num_entries / entries_per_page))


def _dot_leader(
    page: fitz.Page,
    left_x: float,
    right_x: float,
    y: float,
    font_name: str,
    font_size: int,
) -> None:
    """Draw a dot-leader row between the entry title and the page number."""
    dot = config.TOC_DOT_LEADER_CHAR
    try:
        dot_w = fitz.get_text_length(dot, fontname=font_name, fontsize=font_size)
    except AttributeError:
        dot_w = font_size * 0.35

    if dot_w <= 0:
        dot_w = 4.0

    n_dots = int((right_x - left_x) / dot_w)
    if n_dots > 0:
        page.insert_text(
            fitz.Point(left_x, y),
            dot * n_dots,
            fontname=font_name,
            fontsize=font_size,
            color=(0.5, 0.5, 0.5),
        )


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------

def _render_toc_pages(
    sections: list[SectionInfo],
    page_rect: fitz.Rect,
    toc_page_count: int,
    progress_cb: Callable[[str], None] | None = None,
) -> fitz.Document:
    """Render ToC entries (text + dot leaders) into a new fitz.Document.

    Links are NOT injected here because the standalone toc_doc only contains
    toc_page_count pages, so any link pointing to a content page would be
    out-of-range and silently dropped by PyMuPDF.  Call :func:`inject_toc_links`
    on the fully-assembled combined_doc instead.

    Parameters
    ----------
    sections:
        Section metadata — page indices relative to content-only merged doc.
    page_rect:
        Size of each ToC page.
    toc_page_count:
        How many ToC pages will be prepended; used only for computing the
        displayed master page number in each entry.

    Returns
    -------
    fitz.Document
        A new Document containing the rendered ToC pages (no links).
    """
    toc_doc = fitz.open()
    entries_per_page = _entries_per_page(page_rect)

    font = config.TOC_ENTRY_FONT
    font_size = config.TOC_ENTRY_FONT_SIZE
    title_font_size = config.TOC_TITLE_FONT_SIZE
    left_margin = config.TOC_LEFT_MARGIN
    right_boundary = page_rect.width - config.TOC_RIGHT_MARGIN_FROM_EDGE
    line_height = config.TOC_LINE_HEIGHT
    top_y = config.TOC_TOP_MARGIN

    entry_idx = 0
    current_page: fitz.Page | None = None
    current_y: float = 0.0
    page_count_in_doc = 0

    def _new_toc_page() -> tuple[fitz.Page, float]:
        nonlocal page_count_in_doc
        p = toc_doc.new_page(width=page_rect.width, height=page_rect.height)
        page_count_in_doc += 1
        y0 = top_y

        if page_count_in_doc == 1:
            # Draw "TABLE OF CONTENTS" heading on first page only
            # PyMuPDF built-in bold Helvetica = "hebo"
            try:
                heading_w = fitz.get_text_length(
                    config.TOC_TITLE, fontname="hebo", fontsize=title_font_size
                )
            except AttributeError:
                heading_w = len(config.TOC_TITLE) * title_font_size * 0.6

            heading_x = max(left_margin, (page_rect.width - heading_w) / 2.0)
            p.insert_text(
                fitz.Point(heading_x, 50.0),
                config.TOC_TITLE,
                fontname="hebo",
                fontsize=title_font_size,
                color=(0.0, 0.0, 0.0),
            )

        return p, y0

    current_page, current_y = _new_toc_page()

    for section in sections:
        if entry_idx > 0 and entry_idx % entries_per_page == 0:
            current_page, current_y = _new_toc_page()

        # Master page number displayed in the ToC
        master_page_num = section.start_page + toc_page_count + 1

        # ── Build label ──────────────────────────────────────────────────
        if section.table_number:
            label = f"{section.table_number}  {section.title}"
        else:
            label = section.title
        label = _latin1_safe(label)

        # ── Page number string ───────────────────────────────────────────
        page_num_str = str(master_page_num)
        try:
            pnw = fitz.get_text_length(page_num_str, fontname=font, fontsize=font_size)
        except AttributeError:
            pnw = len(page_num_str) * font_size * 0.5

        pn_x = right_boundary - pnw

        # ── Pixel-accurate label truncation ──────────────────────────────
        # Compute the exact pixel budget: from left_margin to the page number,
        # minus a small gap allowance on each side of the dot-leader run.
        max_label_width = pn_x - left_margin - 12.0
        try:
            lw = fitz.get_text_length(label, fontname=font, fontsize=font_size)
            if lw > max_label_width:
                ellipsis_w = fitz.get_text_length("…", fontname=font, fontsize=font_size)
                target = max_label_width - ellipsis_w
                while label and fitz.get_text_length(label, fontname=font, fontsize=font_size) > target:
                    label = label[:-1]
                if label:
                    label = label.rstrip() + "…"
                lw = fitz.get_text_length(label, fontname=font, fontsize=font_size)
        except AttributeError:
            max_label_chars = int(max_label_width / (font_size * 0.5))
            if len(label) > max_label_chars:
                label = label[: max_label_chars - 1] + "…"
            lw = len(label) * font_size * 0.5

        # ── Draw label ───────────────────────────────────────────────────
        current_page.insert_text(
            fitz.Point(left_margin, current_y),
            label,
            fontname=font,
            fontsize=font_size,
            color=(0.0, 0.0, 0.0),
        )

        # ── Draw page number (right-aligned to right_boundary) ───────────
        current_page.insert_text(
            fitz.Point(pn_x, current_y),
            page_num_str,
            fontname=font,
            fontsize=font_size,
            color=(0.0, 0.0, 0.0),
        )

        # ── Draw dot leaders ─────────────────────────────────────────────
        dots_left = left_margin + lw + 4.0
        dots_right = pn_x - 4.0
        if dots_right > dots_left:
            _dot_leader(
                current_page,
                dots_left,
                dots_right,
                current_y,
                font,
                font_size,
            )

        current_y += line_height
        entry_idx += 1
        if progress_cb and entry_idx % 25 == 0:
            progress_cb(f"[PROG] ToC: rendered {entry_idx}/{len(sections)} entries…")

    return toc_doc


# ---------------------------------------------------------------------------
# Two-pass public entry point
# ---------------------------------------------------------------------------

def build_toc(
    sections: list[SectionInfo],
    page_rect: fitz.Rect | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[fitz.Document, int]:
    """Build a ToC document using the two-pass self-aware algorithm.

    Links are NOT embedded here.  After calling this function, prepend the
    returned pages into the final document and then call
    :func:`inject_toc_links` to add clickable links.

    Parameters
    ----------
    sections:
        Ordered section metadata list from :mod:`pdf_merger`.
        **Before** any ToC prepend — page indices are content-only.
    page_rect:
        Desired page dimensions for ToC pages.  Defaults to A4 portrait
        when None.  Ideally pass ``doc[0].rect`` from the merged content.

    Returns
    -------
    tuple[fitz.Document, int]
        ``(toc_doc, toc_page_count)``
        - *toc_doc*        — Document with ToC pages only; caller must close
        - *toc_page_count* — Number of pages in the ToC (for master page offset)
    """
    if not sections:
        # Edge case: nothing to list → return a blank single-page ToC
        empty_rect = page_rect or fitz.Rect(0, 0, 595, 842)
        doc = fitz.open()
        doc.new_page(width=empty_rect.width, height=empty_rect.height)
        return doc, 1

    rect = page_rect or fitz.Rect(0, 0, 595.0, 842.0)  # A4 default
    entries_per_page = _entries_per_page(rect)

    # entries_per_page is fixed and insert_text never wraps, so the estimate
    # is always exact — no convergence loop needed.
    toc_page_count: int = _estimate_toc_pages(len(sections), entries_per_page)

    if progress_cb:
        progress_cb(
            f"[INFO] ToC: rendering {len(sections)} entries across {toc_page_count} page(s)…"
        )
    toc_doc = _render_toc_pages(
        sections=sections,
        page_rect=rect,
        toc_page_count=toc_page_count,
        progress_cb=progress_cb,
    )

    return toc_doc, toc_page_count


# ---------------------------------------------------------------------------
# Post-assembly link injection
# ---------------------------------------------------------------------------

def inject_toc_links(
    combined_doc: fitz.Document,
    sections: list[SectionInfo],
    toc_page_count: int,
    page_rect: fitz.Rect,
) -> None:
    """Inject clickable GOTO links onto the ToC pages of *combined_doc*.

    Must be called AFTER the ToC pages have been prepended into *combined_doc*
    and section page indices have been shifted by *toc_page_count*.  Links
    therefore point to the correct absolute page indices within *combined_doc*.

    The link hit-rect for each entry spans the full width of the entry row
    (from TOC_LEFT_MARGIN to TOC_RIGHT_MARGIN) so the entire text band is
    clickable, not just the underlined portion.

    Parameters
    ----------
    combined_doc:
        Open, writable fitz.Document — the fully assembled final PDF.
    sections:
        Section list with page indices **already shifted** by *toc_page_count*.
    toc_page_count:
        Number of leading ToC pages in *combined_doc*
        (pages 0 … toc_page_count-1 receive the links).
    page_rect:
        Page dimensions used to recompute entries-per-page (must match the
        value used during ToC rendering).
    """
    if not sections:
        return

    entries_per_page = _entries_per_page(page_rect)
    font_size = config.TOC_ENTRY_FONT_SIZE
    left_margin = config.TOC_LEFT_MARGIN
    right_boundary = page_rect.width - config.TOC_RIGHT_MARGIN_FROM_EDGE
    line_height = config.TOC_LINE_HEIGHT
    top_y = config.TOC_TOP_MARGIN

    for idx, section in enumerate(sections):
        toc_page_idx = idx // entries_per_page   # 0-based ToC page number
        row_on_page  = idx % entries_per_page    # row within that page

        if toc_page_idx >= toc_page_count:
            break  # safety guard — more entries than pages (shouldn't happen)

        y_text = top_y + row_on_page * line_height

        # Hit rect: full-width band covering the entry row
        link_rect = fitz.Rect(
            left_margin,
            y_text - font_size,
            right_boundary,
            y_text + 2.0,
        )

        toc_page = combined_doc[toc_page_idx]
        link = {
            "kind": fitz.LINK_GOTO,
            "from": link_rect,
            "page": section.start_page,   # absolute page index in combined_doc
            "to":   fitz.Point(0, 0),     # top-left of target page
            "zoom": 0,
        }
        toc_page.insert_link(link)
