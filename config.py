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
# LibreOffice conversion workers: form default and hard cap
# ---------------------------------------------------------------------------
DEFAULT_PARALLEL_CONVERSIONS: int = 4
MAX_PARALLEL_CONVERSIONS: int = 8

# ---------------------------------------------------------------------------
# UNO conversion mode — persistent soffice services driven via the UNO API,
# giving real per-file progress. Falls back to the CLI path when unavailable.
# ---------------------------------------------------------------------------
UNO_ENABLED: bool = True          # master switch; False forces the CLI path
UNO_READY_TIMEOUT: float = 90.0   # secs to wait for a slot's soffice + helper
                                  # (first start creates the LO profile: slow)
UNO_START_RETRIES: int = 3        # bootstrap attempts per slot, fresh port each
UNO_LOAD_SPAN: int = 70           # % of the per-file bar given to the load
                                  # phase; the export phase gets the remainder
UNO_RECYCLE_AFTER: int = 100      # conversions per slot before a proactive
                                  # restart (LO leaks memory over many docs)

# ---------------------------------------------------------------------------
# Local processing area: all per-job working files (staged RTF copies,
# per-section PDFs, LibreOffice profiles, final-PDF staging) live under
# %TEMP%\<LOCAL_TEMP_SUBDIR>\job_* on the LOCAL disk — never in the input or
# output directory, which may be on a network share. Removed after each run.
# ---------------------------------------------------------------------------
LOCAL_TEMP_SUBDIR: str = "rtf2pdf"
