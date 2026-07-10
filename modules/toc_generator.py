"""
modules/toc_generator.py
------------------------
Generates a hyperlinked Table of Contents (ToC) as one or more PDF pages
that are prepended to the final compiled document.

Algorithm
---------
A single pure layout pass (:func:`_compute_toc_layout`) decides, for every
entry, which ToC page it lands on, its exact baselines, and its (possibly
wrapped) label lines.  Rendering and link injection both consume that same
layout, so the clickable areas can never drift from the drawn text — the
one invariant that matters when entries are allowed to wrap onto multiple
lines.

The layout depends on the ToC's own page count (the master page numbers
shown on the right change width with the offset), so :func:`build_toc`
iterates the layout to a fixed point.  Without wrapping the first guess is
already exact; with wrapping it converges in a step or two.

Public API
----------
    toc_doc, toc_page_count, layout = build_toc(sections, page_rect, wrap=...)
    ...prepend pages, shift sections...
    inject_toc_links(combined_doc, sections, toc_page_count, page_rect, layout)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import fitz  # PyMuPDF

import config
from modules.pdf_merger import SectionInfo


# Hanging indent for wrapped continuation lines (pts).
_WRAP_INDENT = 12.0

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
# Measurement / layout helpers
# ---------------------------------------------------------------------------

def _text_width(text: str, font_name: str, font_size: int) -> float:
    """Measured text width in points, with a heuristic fallback for very
    old PyMuPDF versions that lack ``get_text_length``."""
    try:
        return fitz.get_text_length(text, fontname=font_name, fontsize=font_size)
    except AttributeError:
        return len(text) * font_size * 0.5


def _entries_per_page(page_rect: fitz.Rect) -> int:
    """How many ToC text lines fit on one page."""
    usable_height = page_rect.height - config.TOC_TOP_MARGIN - 60.0  # bottom margin
    return max(1, int(usable_height / config.TOC_LINE_HEIGHT))


def _truncate_to_width(label: str, budget: float, font: str, font_size: int) -> str:
    """Pixel-accurate truncation with a trailing "..." marker.

    ASCII dots, not U+2026: the built-in Helvetica cannot encode the
    ellipsis character and would render a replacement glyph.
    """
    if _text_width(label, font, font_size) <= budget:
        return label
    marker = "..."
    target = budget - _text_width(marker, font, font_size)
    while label and _text_width(label, font, font_size) > target:
        label = label[:-1]
    return label.rstrip() + marker if label else marker


def _wrap_label(
    label: str,
    budget_first: float,
    budget_rest: float,
    font: str,
    font_size: int,
) -> list[str]:
    """Greedy word wrap measured in points.

    Splits on single spaces (preserving multi-space runs when tokens are
    rejoined); a lone word wider than the line budget is hard-broken at
    character level so no line can ever exceed its budget.
    """
    tokens = label.split(" ")
    lines: list[str] = []
    cur = ""
    budget = budget_first

    def flush() -> None:
        nonlocal cur, budget
        if cur:
            lines.append(cur)
            cur = ""
            budget = budget_rest

    for tok in tokens:
        cand = f"{cur} {tok}" if cur else tok
        if _text_width(cand, font, font_size) <= budget:
            cur = cand
            continue
        flush()
        # Token alone on a fresh line — hard-break it if still too wide.
        while _text_width(tok, font, font_size) > budget and len(tok) > 1:
            cut = len(tok)
            while cut > 1 and _text_width(tok[:cut], font, font_size) > budget:
                cut -= 1
            lines.append(tok[:cut])
            tok = tok[cut:]
            budget = budget_rest
        cur = tok
    flush()
    return lines or [""]


@dataclass
class TocEntryLayout:
    """Where one ToC entry lives — shared by renderer and link injection."""
    page_idx: int          # 0-based ToC page
    y_top: float           # baseline of the first line
    y_last: float          # baseline of the last line
    lines: list[str]       # label lines (length 1 when not wrapped)
    pn_x: float            # x of the right-aligned page number
    page_num_str: str
    last_line_end_x: float  # x where the last label line ends (dots start here)


def _compute_toc_layout(
    sections: list[SectionInfo],
    page_rect: fitz.Rect,
    wrap: bool,
    toc_page_count: int,
) -> tuple[list[TocEntryLayout], int]:
    """Pure layout pass: assign every entry its page, baselines and lines.

    *toc_page_count* is the assumed number of ToC pages (it offsets the
    displayed master page numbers); the caller iterates until the returned
    pages-used equals the assumption.
    Entries are never split across pages; an entry too tall for a whole
    page (pathological) has its overflow truncated with an ellipsis.
    """
    font = config.TOC_ENTRY_FONT
    font_size = config.TOC_ENTRY_FONT_SIZE
    left_margin = config.TOC_LEFT_MARGIN
    right_boundary = page_rect.width - config.TOC_RIGHT_MARGIN_FROM_EDGE
    line_height = config.TOC_LINE_HEIGHT
    top_y = config.TOC_TOP_MARGIN
    capacity = _entries_per_page(page_rect)

    entries: list[TocEntryLayout] = []
    page_idx = 0
    row = 0

    for section in sections:
        master_page_num = section.start_page + toc_page_count + 1
        page_num_str = str(master_page_num)
        pn_x = right_boundary - _text_width(page_num_str, font, font_size)

        if section.table_number:
            label = f"{section.table_number}  {section.title}"
        else:
            label = section.title
        label = _latin1_safe(label)

        budget = pn_x - left_margin - 12.0
        if wrap:
            lines = _wrap_label(label, budget, budget - _WRAP_INDENT, font, font_size)
            if len(lines) > capacity:
                lines = lines[:capacity]
                lines[-1] = _truncate_to_width(
                    lines[-1], budget - _WRAP_INDENT, font, font_size
                )
        else:
            lines = [_truncate_to_width(label, budget, font, font_size)]

        n = len(lines)
        if row > 0 and row + n > capacity:
            page_idx += 1
            row = 0

        y_top = top_y + row * line_height
        y_last = top_y + (row + n - 1) * line_height
        last_x_start = left_margin + (_WRAP_INDENT if n > 1 else 0.0)
        entries.append(TocEntryLayout(
            page_idx=page_idx,
            y_top=y_top,
            y_last=y_last,
            lines=lines,
            pn_x=pn_x,
            page_num_str=page_num_str,
            last_line_end_x=last_x_start + _text_width(lines[-1], font, font_size),
        ))
        row += n

    return entries, page_idx + 1


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
    dot_w = _text_width(dot, font_name, font_size)
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
    layout: list[TocEntryLayout],
    page_rect: fitz.Rect,
    toc_page_count: int,
    progress_cb: Callable[[str], None] | None = None,
) -> fitz.Document:
    """Draw the precomputed layout (text + dot leaders) into a new Document.

    Links are NOT injected here because the standalone toc_doc only contains
    toc_page_count pages, so any link pointing to a content page would be
    out-of-range and silently dropped by PyMuPDF.  Call :func:`inject_toc_links`
    on the fully-assembled combined_doc instead.
    """
    toc_doc = fitz.open()

    font = config.TOC_ENTRY_FONT
    font_size = config.TOC_ENTRY_FONT_SIZE
    title_font_size = config.TOC_TITLE_FONT_SIZE
    left_margin = config.TOC_LEFT_MARGIN
    line_height = config.TOC_LINE_HEIGHT

    def _new_toc_page() -> fitz.Page:
        p = toc_doc.new_page(width=page_rect.width, height=page_rect.height)
        if toc_doc.page_count == 1:
            # "TABLE OF CONTENTS" heading on the first page only.
            heading_w = _text_width(config.TOC_TITLE, "hebo", title_font_size)
            heading_x = max(left_margin, (page_rect.width - heading_w) / 2.0)
            p.insert_text(
                fitz.Point(heading_x, 50.0),
                config.TOC_TITLE,
                fontname="hebo",
                fontsize=title_font_size,
                color=(0.0, 0.0, 0.0),
            )
        return p

    current_page = _new_toc_page()

    for idx, entry in enumerate(layout):
        while toc_doc.page_count <= entry.page_idx:
            current_page = _new_toc_page()

        for i, line in enumerate(entry.lines):
            x = left_margin + (_WRAP_INDENT if i > 0 else 0.0)
            current_page.insert_text(
                fitz.Point(x, entry.y_top + i * line_height),
                line,
                fontname=font,
                fontsize=font_size,
                color=(0.0, 0.0, 0.0),
            )

        # Page number, right-aligned, on the entry's LAST line.
        current_page.insert_text(
            fitz.Point(entry.pn_x, entry.y_last),
            entry.page_num_str,
            fontname=font,
            fontsize=font_size,
            color=(0.0, 0.0, 0.0),
        )

        # Dot leader from the end of the last label line to the page number.
        dots_left = entry.last_line_end_x + 4.0
        dots_right = entry.pn_x - 4.0
        if dots_right > dots_left:
            _dot_leader(current_page, dots_left, dots_right, entry.y_last,
                        font, font_size)

        if progress_cb and (idx + 1) % 25 == 0:
            progress_cb(f"[PROG] ToC: rendered {idx + 1}/{len(layout)} entries…")

    # The fixed-point loop in build_toc guarantees agreement; pad defensively
    # so the prepend offset can never be wrong even if it were off.
    while toc_doc.page_count < toc_page_count:
        _new_toc_page()

    return toc_doc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_toc(
    sections: list[SectionInfo],
    page_rect: fitz.Rect | None = None,
    progress_cb: Callable[[str], None] | None = None,
    wrap: bool = False,
) -> tuple[fitz.Document, int, list[TocEntryLayout]]:
    """Build the ToC document; layout is iterated to a fixed point.

    Links are NOT embedded here.  After calling this function, prepend the
    returned pages into the final document and then call
    :func:`inject_toc_links` with the returned layout.

    Parameters
    ----------
    sections:
        Ordered section metadata list from :mod:`pdf_merger`.
        **Before** any ToC prepend — page indices are content-only.
    page_rect:
        Desired page dimensions for ToC pages (A4 portrait when None).
    wrap:
        ``True``: long labels wrap onto continuation lines (hanging indent)
        and entries become variable-height. ``False``: legacy single-line
        entries with ellipsis truncation.

    Returns
    -------
    tuple[fitz.Document, int, list[TocEntryLayout]]
        ``(toc_doc, toc_page_count, layout)`` — pass *layout* unchanged to
        :func:`inject_toc_links`.
    """
    if not sections:
        # Edge case: nothing to list → return a blank single-page ToC
        empty_rect = page_rect or fitz.Rect(0, 0, 595, 842)
        doc = fitz.open()
        doc.new_page(width=empty_rect.width, height=empty_rect.height)
        return doc, 1, []

    rect = page_rect or fitz.Rect(0, 0, 595.0, 842.0)  # A4 default

    # Fixed point: page numbers shown in entries depend on the ToC's own
    # page count, which depends on the layout. Page count is monotone
    # non-decreasing across iterations, so this converges quickly.
    guess = max(1, math.ceil(len(sections) / _entries_per_page(rect)))
    layout, pages_used = _compute_toc_layout(sections, rect, wrap, guess)
    for _ in range(10):
        if pages_used == guess:
            break
        guess = pages_used
        layout, pages_used = _compute_toc_layout(sections, rect, wrap, guess)

    if progress_cb:
        progress_cb(
            f"[INFO] ToC: rendering {len(sections)} entries across {pages_used} page(s)…"
        )
    toc_doc = _render_toc_pages(
        layout=layout,
        page_rect=rect,
        toc_page_count=pages_used,
        progress_cb=progress_cb,
    )

    return toc_doc, pages_used, layout


# ---------------------------------------------------------------------------
# Post-assembly link injection
# ---------------------------------------------------------------------------

def inject_toc_links(
    combined_doc: fitz.Document,
    sections: list[SectionInfo],
    toc_page_count: int,
    page_rect: fitz.Rect,
    layout: list[TocEntryLayout],
) -> None:
    """Inject clickable GOTO links onto the ToC pages of *combined_doc*.

    Must be called AFTER the ToC pages have been prepended into *combined_doc*
    and section page indices have been shifted by *toc_page_count*.  The
    *layout* from :func:`build_toc` supplies each entry's real page and
    baselines, so the hit rects always match the rendered text — including
    multi-line wrapped entries, whose whole band is clickable.
    """
    if not sections or not layout:
        return

    font_size = config.TOC_ENTRY_FONT_SIZE
    left_margin = config.TOC_LEFT_MARGIN
    right_boundary = page_rect.width - config.TOC_RIGHT_MARGIN_FROM_EDGE

    for section, entry in zip(sections, layout):
        if entry.page_idx >= toc_page_count:
            break  # safety guard — layout page outside the prepended range

        link_rect = fitz.Rect(
            left_margin,
            entry.y_top - font_size,
            right_boundary,
            entry.y_last + 2.0,
        )

        toc_page = combined_doc[entry.page_idx]
        toc_page.insert_link({
            "kind": fitz.LINK_GOTO,
            "from": link_rect,
            "page": section.start_page,   # absolute page index in combined_doc
            "to":   fitz.Point(0, 0),     # top-left of target page
            "zoom": 0,
        })
