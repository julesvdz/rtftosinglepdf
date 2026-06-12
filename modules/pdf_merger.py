"""
modules/pdf_merger.py
---------------------
Merges an ordered list of single-source PDF files into one PyMuPDF Document
object and returns per-section metadata (title, start_page, end_page) that
other modules consume for ToC generation, bookmarks, and logging.

Uses 0-based page indexing internally; callers that need human-readable
"Master page numbers" should add 1 when displaying.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SectionInfo:
    """Tracks one RTF section's position inside the merged document."""
    title: str               # Display title (from RTF parser or CSV)
    table_number: str        # e.g. "14.1.1" — may be empty string
    rtf_filename: str        # Original source RTF filename
    pdf_path: str            # Path to the temporary per-section PDF
    start_page: int          # 0-based index of the first page in merged doc
    end_page: int            # 0-based index of the last page  (inclusive)

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def master_start(self) -> int:
        """1-based master page number of the first page."""
        return self.start_page + 1

    @property
    def master_end(self) -> int:
        """1-based master page number of the last page."""
        return self.end_page + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_pdfs(
    sections: Sequence[tuple[str, str, str, str]],
) -> tuple[fitz.Document, list[SectionInfo]]:
    """Merge ordered per-section PDFs into a single in-memory Document.

    Parameters
    ----------
    sections:
        Ordered sequence of 4-tuples:
        ``(pdf_path, title, table_number, rtf_filename)``

        - *pdf_path*      — path to a converted single-section PDF
        - *title*         — display title for this section
        - *table_number*  — table reference string (may be empty)
        - *rtf_filename*  — original RTF source name for logging

    Returns
    -------
    tuple[fitz.Document, list[SectionInfo]]
        ``(merged_doc, section_info_list)``

        - *merged_doc*        — open PyMuPDF Document (caller must close)
        - *section_info_list* — metadata about each section's page range

    Raises
    ------
    FileNotFoundError
        When a PDF path in *sections* does not exist.
    fitz.FileDataError
        When a PDF is corrupt or unreadable.
    """
    merged = fitz.open()
    section_info: list[SectionInfo] = []
    cursor: int = 0   # tracks next available 0-based page index in merged doc

    for pdf_path, title, table_number, rtf_filename in sections:
        pdf_path = str(pdf_path)
        src_path = Path(pdf_path)

        if not src_path.exists():
            raise FileNotFoundError(
                f"Converted PDF not found during merge: {src_path}"
            )

        with fitz.open(pdf_path) as src:
            page_count = src.page_count
            if page_count == 0:
                continue  # skip empty PDFs

            # insert_pdf appends all pages from src into merged
            merged.insert_pdf(src)

        start = cursor
        end = cursor + page_count - 1

        section_info.append(SectionInfo(
            title=title,
            table_number=table_number,
            rtf_filename=rtf_filename,
            pdf_path=pdf_path,
            start_page=start,
            end_page=end,
        ))

        cursor += page_count

    return merged, section_info


def prepend_pages(
    main_doc: fitz.Document,
    pages_doc: fitz.Document,
) -> tuple[fitz.Document, int]:
    """Prepend all pages from *pages_doc* in front of *main_doc*.

    Returns a *new* merged Document and the number of prepended pages.
    Both input documents remain open and unchanged.

    This is used to inject the generated ToC pages at the very start of the
    final compiled PDF.
    """
    combined = fitz.open()
    prepend_count = pages_doc.page_count
    combined.insert_pdf(pages_doc)
    combined.insert_pdf(main_doc)
    return combined, prepend_count


def shift_section_info(
    sections: list[SectionInfo],
    offset: int,
) -> list[SectionInfo]:
    """Return new SectionInfo list with page indices shifted by *offset*.

    Used after prepending ToC pages to correct all section page references.
    """
    return [
        SectionInfo(
            title=s.title,
            table_number=s.table_number,
            rtf_filename=s.rtf_filename,
            pdf_path=s.pdf_path,
            start_page=s.start_page + offset,
            end_page=s.end_page + offset,
        )
        for s in sections
    ]
