# =============================================================================
# config.py — Hardcoded coordinate constants and application-level defaults
#
# All PDF coordinate values are in points (1 pt = 1/72 inch).
# Page origin: top-left corner. Y increases downward.
#
# To adjust overlay positions without touching logic, modify values here.
# =============================================================================

# ---------------------------------------------------------------------------
# "Page X of Y" master page number overlay — margins from page edges
# All values are distances from the page edge in points.
# Absolute Y and X are computed per-page as (page_height - bottom_margin)
# and (page_width - right_margin), so the overlay stays within bounds on
# any paper size (A4, Letter) and any orientation (portrait, landscape).
# ---------------------------------------------------------------------------
PAGE_NUMBER_BOTTOM_MARGIN: float = 18.0   # pts from bottom of page
PAGE_NUMBER_RIGHT_MARGIN: float = 55.0    # pts from right edge of page
PAGE_NUMBER_FONT_SIZE: int = 8
PAGE_NUMBER_FONT: str = "helv"            # PyMuPDF built-in: Helvetica
PAGE_NUMBER_COLOR: tuple = (0.0, 0.0, 0.0)   # RGB black

# ---------------------------------------------------------------------------
# Header overlay — margin from top of page (pts)
# ---------------------------------------------------------------------------
HEADER_TOP_MARGIN: float = 28.0

# ---------------------------------------------------------------------------
# Footer overlay — margin from bottom of page (pts)
# Computed as (page_height - FOOTER_BOTTOM_MARGIN) per page, so it works
# on A4 (842 pts), Letter (792 pts), and landscape variants.
# ---------------------------------------------------------------------------
FOOTER_BOTTOM_MARGIN: float = 35.0

# ---------------------------------------------------------------------------
# Header / Footer font settings
# ---------------------------------------------------------------------------
HEADER_FOOTER_FONT: str = "helv"    # PyMuPDF built-in: Helvetica
HEADER_FOOTER_FONT_SIZE: int = 8
HEADER_FOOTER_COLOR: tuple = (0.0, 0.0, 0.0)

# ---------------------------------------------------------------------------
# Table of Contents layout constants
# ---------------------------------------------------------------------------
TOC_TITLE: str = "TABLE OF CONTENTS"
TOC_TITLE_FONT_SIZE: int = 13
TOC_ENTRY_FONT_SIZE: int = 10
TOC_ENTRY_FONT: str = "helv"
TOC_LEFT_MARGIN: float = 60.0       # pts from left
TOC_RIGHT_MARGIN_FROM_EDGE: float = 55.0  # pts from right edge — dot leader boundary
TOC_TOP_MARGIN: float = 80.0        # Y of first entry on a ToC page (pts)
TOC_LINE_HEIGHT: float = 18.0       # vertical spacing between entries (pts)
TOC_DOT_LEADER_CHAR: str = "."

# ---------------------------------------------------------------------------
# LibreOffice conversion timeout — scaled by RTF file size
# ---------------------------------------------------------------------------
LIBREOFFICE_TIMEOUT_PER_MB: float = 90.0   # seconds per MB of RTF file size
LIBREOFFICE_TIMEOUT_MIN: int = 60          # floor: never less than this

# ---------------------------------------------------------------------------
# Maximum simultaneous LibreOffice conversion workers
# ---------------------------------------------------------------------------
MAX_PARALLEL_CONVERSIONS: int = 8

# ---------------------------------------------------------------------------
# Temporary working subdirectory name (created inside output_dir at runtime)
# ---------------------------------------------------------------------------
TEMP_DIR_NAME: str = "_rtf2pdf_tmp"
