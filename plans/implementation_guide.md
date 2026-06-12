# RTF-to-PDF Compiler — Complete Implementation Guide

**Purpose:** Full reproduction guide for the Flask-based clinical document PDF compiler.  
**Language:** Python 3.10+  
**Last Updated:** 2026-02-24  

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Project File Structure](#3-project-file-structure)
4. [Installation & Launch](#4-installation--launch)
5. [Application Architecture](#5-application-architecture)
6. [Processing Pipeline (Detailed)](#6-processing-pipeline-detailed)
7. [Module Reference](#7-module-reference)
8. [Configuration System](#8-configuration-system)
9. [Flask API Endpoints](#9-flask-api-endpoints)
10. [Frontend Implementation](#10-frontend-implementation)
11. [Output Artefacts](#11-output-artefacts)
12. [Coordinate System](#12-coordinate-system)
13. [PyMuPDF Font Reference](#13-pymupdf-font-reference)
14. [Error Handling](#14-error-handling)
15. [Extension Points](#15-extension-points)
16. [Known Limitations](#16-known-limitations)

---

## 1. Overview

The application accepts a folder of SAS-generated RTF files and compiles them into a single annotated PDF with:

- A self-aware hyperlinked Table of Contents (accounts for its own page count)
- Dual-layer page numbering: original RTF page numbers preserved + master "Page X of Y" overlay
- Configurable header and footer bands (Left / Center / Right text slots) on every page
- Flat PDF bookmarks (outline) per section
- ISO 8601-timestamped output files for audit traceability
- JSON config persistence for settings recall
- Per-file audit log with master page ranges

The web UI is a VSCode-dark-themed single-page Flask application. All heavy processing runs asynchronously in a daemon thread; the browser polls for progress every 1.5 seconds.

---

## 2. Prerequisites

### 2.1 Python Packages

```
flask>=3.0.0
pymupdf>=1.24.0
striprtf>=0.0.26
Werkzeug>=3.0.0
```

Install with:

```bash
pip install -r requirements.txt
```

### 2.2 LibreOffice

LibreOffice must be installed on the host machine. It is used headlessly for RTF → PDF conversion. The application auto-detects its binary; no manual configuration is required if LibreOffice is installed via standard installer.

**Tested paths detected automatically:**

| Platform | Candidate paths probed |
|---|---|
| Windows | `Program Files\LibreOffice\program\soffice.exe` and variants for LO 7/24/25 |
| Linux | `/usr/bin/soffice`, `/usr/lib/libreoffice/program/soffice`, `/snap/bin/libreoffice` |
| macOS | `/Applications/LibreOffice.app/Contents/MacOS/soffice` |
| All | `shutil.which('soffice')` and `shutil.which('soffice.exe')` (checks PATH) |

If LibreOffice is installed in a non-standard location, add its `program/` directory to `PATH`.

---

## 3. Project File Structure

```
rtftosinglepdf/
│
├── app.py                        Flask application + background job runner
├── config.py                     Hardcoded coordinate/layout constants
├── requirements.txt              Python dependencies
│
├── plans/
│   ├── architecture.md           High-level architecture summary
│   └── implementation_guide.md  This document
│
├── modules/
│   ├── __init__.py               Package marker (empty)
│   ├── libreoffice.py            soffice autodetection + RTF→PDF subprocess
│   ├── rtf_parser.py             Title extraction using striprtf
│   ├── csv_handler.py            CSV mapping parser and file resolver
│   ├── pdf_merger.py             PyMuPDF page merging + SectionInfo tracking
│   ├── bookmarks.py              PDF outline (bookmark) injection
│   ├── toc_generator.py          Two-pass self-aware ToC builder + link injector
│   ├── page_numbering.py         "Page X of Y" master overlay
│   ├── header_footer.py          Header/footer text overlay (L/C/R slots)
│   ├── config_manager.py         JSON config save/load with timestamp
│   └── process_logger.py         Per-file audit logger with flush-to-disk
│
├── static/
│   ├── css/style.css             VSCode-dark theme stylesheet
│   └── js/app.js                 Fetch-based async polling + UI logic
│
└── templates/
    └── index.html                Single-page UI template
```

---

## 4. Installation & Launch

```bash
# 1. Clone / place the project at any local path
cd rtftosinglepdf

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Ensure LibreOffice is installed (checked at first job run)

# 4a. Development server (auto-reload on file changes)
python app.py
# → http://localhost:5000

# 4b. Production server (Waitress, no debug mode)
pip install waitress
python -m waitress --host=0.0.0.0 --port=5000 app:app
```

The Flask dev server is multi-threaded (`threaded=True`) so concurrent HTTP requests (polling + download) do not block each other.

---

## 5. Application Architecture

### 5.1 Request / Response Flow

```
Browser                     Flask (main thread)          Worker Thread
  │                              │                             │
  │── POST /api/run ────────────►│                             │
  │                              │── spawn daemon thread ─────►│
  │◄── {"job_id": "uuid"} ───────│                             │
  │                              │                    [pipeline runs]
  │── GET /api/status/<id> ──────►│                             │
  │◄── {status, progress, log} ──│◄── reads JOBS dict ─────────│
  │                              │                             │
  │   [poll every 1.5 s ...]     │                             │
  │                              │                    [complete]
  │── GET /api/status/<id> ──────►│                             │
  │◄── {status:"complete",...} ──│                             │
  │                              │                             │
  │── GET /api/download/<id> ────►│                             │
  │◄── PDF binary stream ─────────│                             │
```

### 5.2 In-Memory Job Registry

```python
JOBS: dict[str, dict[str, Any]] = {}

# Per-job structure:
{
    "status":   "running" | "complete" | "error",
    "progress": 0..100,          # integer percentage
    "log":      [str, ...],      # list of log lines appended during run
    "pdf_path": str | None,      # absolute path to final PDF when complete
    "error":    str | None,      # exception message on failure
}
```

A `threading.Lock` (`_JOBS_LOCK`) guards all reads/writes to `JOBS`. Worker threads call `_update_job()` and `_append_log()` helper functions that acquire the lock internally.

The registry is in-process memory only. **It is lost on server restart.** The PDF file remains on disk; only the registry entry is gone.

---

## 6. Processing Pipeline (Detailed)

Below is the full step-by-step execution of `_run_job()` in `app.py`.

```
Step  1  Generate ISO timestamp stem  →  ts = "20260224T070829Z"
Step  2  Detect LibreOffice binary    →  find_soffice()
Step  3  Resolve RTF file list
           a) CSV uploaded → parse_csv() + resolve_entries_against_directory()
           b) No CSV       → glob *.rtf in rtf_dir, alphanumeric sort
                             extract_title() called per file via rtf_parser
Step  4  LibreOffice conversion loop
           For each RTF:
             convert_rtf_to_pdf(rtf_path, rtf_dir, soffice_path)
             Output: rtf_dir/<stem>.pdf  (lives permanently alongside RTF)
Step  5  Merge PDFs
           merge_pdfs([(pdf_path, title, table_num, rtf_name), ...])
           Returns: (merged_doc, [SectionInfo])
           SectionInfo tracks start_page, end_page (0-based) in merged_doc
Step  6  ToC — Pass 1 (estimate)
           build_toc(sections, page_rect)
             → _estimate_toc_pages(len(sections), entries_per_page)
             → render draft to confirm page count (convergence loop ≤ 2 iter)
Step  7  ToC — Pass 2 (render final text + dot leaders)
           _render_toc_pages(sections, page_rect, toc_page_count)
           Displayed master page number: section.start_page + toc_page_count + 1
Step  8  Prepend ToC
           combined_doc, prepended = prepend_pages(merged_doc, toc_doc)
           toc_doc pages inserted at front; merged_doc pages follow
Step  9  Shift section page indices
           sections = shift_section_info(sections, prepended)
           All start_page / end_page += prepended (= toc_page_count)
Step 10  Inject ToC hyperlinks
           inject_toc_links(combined_doc, sections, prepended, page_rect)
           Computes row Y positions → inserts fitz.LINK_GOTO on ToC pages
           Links point to section.start_page in combined_doc (absolute, valid)
Step 11  Header / Footer overlay
           apply_headers_and_footers(combined_doc, header, footer, overlay_config)
           Operates on ALL pages including ToC pages
Step 12  Master page number overlay
           apply_master_page_numbers(combined_doc, toc_page_count, overlay_config)
           Inserts "Page {n} of {total}" on ALL pages
Step 13  PDF bookmarks (outline)
           build_toc_list(entries)  →  [[1, title, page_1based], ...]
           inject_bookmarks(combined_doc, bm_toc)
           Flat structure (level=1 for all entries)
Step 14  Save PDF
           combined_doc.save("output_<ts>.pdf", garbage=4, deflate=True, clean=True)
Step 15  Log page ranges to ProcessLogger
           plogger.log_conversion_ok(filename, master_start, master_end) per section
Step 16  Save config JSON
           save_config(params, output_dir, filename_stem="output_<ts>_config")
Step 17  Flush process log
           plogger.flush(output_dir, total_files, filename_stem="output_<ts>")
Step 18  Mark job complete in JOBS registry
```

---

## 7. Module Reference

### 7.1 `config.py`

Central constant store. **All overlay coordinate decisions live here.** To adjust any position without touching logic, edit this file.

| Constant | Default | Type | Description |
|---|---|---|---|
| `PAGE_NUMBER_X` | `540.0` | float | Right-edge X for "Page X of Y" text (pts) |
| `PAGE_NUMBER_Y` | `818.0` | float | Y position of page number text (pts from top) |
| `PAGE_NUMBER_FONT_SIZE` | `8` | int | Font size for page number overlay |
| `PAGE_NUMBER_FONT` | `"helv"` | str | PyMuPDF built-in font (Helvetica) |
| `PAGE_NUMBER_COLOR` | `(0,0,0)` | tuple | RGB black |
| `HEADER_Y_DEFAULT` | `28.0` | float | Default Y for header text (pts from top) |
| `FOOTER_Y_DEFAULT` | `820.0` | float | Default Y for footer text (pts from top) |
| `HEADER_FOOTER_FONT` | `"helv"` | str | Font for header/footer text |
| `HEADER_FOOTER_FONT_SIZE` | `8` | int | Font size for header/footer |
| `HEADER_FOOTER_COLOR` | `(0,0,0)` | tuple | RGB black |
| `TOC_TITLE` | `"TABLE OF CONTENTS"` | str | Heading text on first ToC page |
| `TOC_TITLE_FONT_SIZE` | `13` | int | Font size for ToC heading |
| `TOC_ENTRY_FONT_SIZE` | `10` | int | Font size for ToC entry rows |
| `TOC_ENTRY_FONT` | `"helv"` | str | Font for entry text |
| `TOC_LEFT_MARGIN` | `60.0` | float | Left start X of entry text (pts) |
| `TOC_RIGHT_MARGIN` | `540.0` | float | Right boundary / page number column X (pts) |
| `TOC_TOP_MARGIN` | `80.0` | float | Y of first entry row on any ToC page (pts) |
| `TOC_LINE_HEIGHT` | `18.0` | float | Vertical gap between entry rows (pts) |
| `TOC_DOT_LEADER_CHAR` | `"."` | str | Character repeated as dot leader |
| `LIBREOFFICE_TIMEOUT` | `120` | int | Max seconds per file for LibreOffice conversion |
| `TEMP_DIR_NAME` | `"_rtf2pdf_tmp"` | str | Legacy constant (no longer used) |

UI values loaded from a saved JSON config override these at runtime when passed as `overlay_config` dict.

---

### 7.2 `modules/libreoffice.py`

**Public functions:**

```python
find_soffice() -> str
```
Probes PATH then platform-specific hardcoded paths. Returns absolute path to `soffice`/`soffice.exe`. Raises `RuntimeError` if not found.

```python
convert_rtf_to_pdf(rtf_path, output_dir, soffice_path=None) -> Path
```
Runs:
```
soffice --headless --norestore --nofirststartwizard
        --convert-to pdf --outdir <output_dir> <rtf_path>
```
Returns `Path` to the produced PDF. Raises `FileNotFoundError` or `RuntimeError` on failure. Timeout governed by `config.LIBREOFFICE_TIMEOUT`.

**Side-effect:** Intermediate PDFs are written into `rtf_dir` (same folder as source RTFs) and are never deleted. Re-running will overwrite existing intermediates with the same stem name.

---

### 7.3 `modules/rtf_parser.py`

```python
extract_title(rtf_path, max_read_bytes=16384) -> str
```

- Reads first `max_read_bytes` bytes (default 16 KB) of the RTF file
- Decodes as `cp1252` with `errors="replace"`
- Passes raw RTF string to `striprtf.rtf_to_text()` (falls back to regex stripper if `striprtf` unavailable)
- Returns the first non-blank plain-text line, truncated at 256 characters
- Falls back to `rtf_path.stem` (filename without extension) if no text is extractable

**Fallback regex stripper** handles: control words (`\par`, `\fs24`), control symbols (`\~`), braces, line-breaks. Does not handle `\bin` blobs reliably (hence `striprtf` is preferred).

---

### 7.4 `modules/csv_handler.py`

**CSV schema** (header row required; column names are case-insensitive):

| Canonical key | Recognised aliases | Required |
|---|---|---|
| `rtf_filename` | `RTF_Filename`, `filename`, `file` | Yes |
| `table_number` | `Table_Number`, `table_no`, `number` | No |
| `title` | `Title`, `description`, `label` | Yes |

**Public types/functions:**

```python
class SectionEntry(NamedTuple):
    rtf_filename: str
    table_number: str
    title: str

parse_csv(csv_path) -> list[SectionEntry]
```
Reads CSV; returns entries in row order. Raises `ValueError` if required columns missing.

```python
resolve_entries_against_directory(entries, rtf_dir) -> list[tuple[SectionEntry, Path]]
```
Filters to entries whose RTF file actually exists in `rtf_dir`. Unmatched entries are silently dropped here; the caller logs them via `ProcessLogger.log_skip()`.

---

### 7.5 `modules/pdf_merger.py`

**`SectionInfo` dataclass:**

```python
@dataclass
class SectionInfo:
    title: str
    table_number: str
    rtf_filename: str
    pdf_path: str
    start_page: int      # 0-based index in merged doc
    end_page: int        # 0-based index, inclusive

    # Computed properties:
    page_count -> int    # end_page - start_page + 1
    master_start -> int  # start_page + 1  (1-based, for display)
    master_end -> int    # end_page + 1
```

**Public functions:**

```python
merge_pdfs(sections) -> tuple[fitz.Document, list[SectionInfo]]
```
`sections` is a list of `(pdf_path, title, table_number, rtf_filename)` tuples. Returns the merged open Document and per-section metadata. Caller must close the Document.

```python
prepend_pages(main_doc, pages_doc) -> tuple[fitz.Document, int]
```
Creates a new `fitz.Document`, inserts all pages of `pages_doc` first, then all of `main_doc`. Returns `(combined_doc, prepend_count)`. Both input docs remain open and unchanged.

```python
shift_section_info(sections, offset) -> list[SectionInfo]
```
Returns a new `SectionInfo` list with every `start_page` and `end_page` incremented by `offset`. Used after `prepend_pages()` to correct page references.

---

### 7.6 `modules/bookmarks.py`

Provides modular flat PDF bookmark (outline) injection.

```python
def build_toc_list(entries: list[dict], default_level=1) -> list[list]:
```
Each entry dict must have:
- `"title"` (str) — display text
- `"page_index"` (int) — 0-based target page

Optional:
- `"level"` (int) — outline depth (default 1 = flat)
- `"table_number"` (str) — prepended to title as `"14.1.1  Title Text"`

Returns PyMuPDF TOC format: `[[level, title, page_1based], ...]`

```python
def inject_bookmarks(doc: fitz.Document, toc: list[list]) -> None:
```
Calls `doc.set_toc(toc)` in-place.

**Extensibility:** To add nested bookmarks, populate `"level": 2` (or deeper) in entry dicts. `build_toc_list()` already passes the value through unchanged. No other code changes required.

---

### 7.7 `modules/toc_generator.py`

The most complex module. Implements a two-pass self-aware ToC builder plus a post-assembly link injector.

#### Two-Pass Algorithm

**The problem:** ToC must display correct master page numbers, but master page numbers depend on how many pages the ToC itself occupies — a circular dependency.

**Solution:**

```
Pass 1 — Estimate
  entries_per_page = floor((page_height - TOC_TOP_MARGIN - 60) / TOC_LINE_HEIGHT)
  estimated_pages  = ceil(num_sections / entries_per_page)

  Render a draft (text only) and count its actual pages.
  If actual ≠ estimate → set estimate = actual and re-render once.
  (Maximum 2 iterations; convergence is guaranteed.)

Pass 2 — Final render
  With toc_page_count confirmed:
    displayed_master = section.start_page + toc_page_count + 1
  Render final ToC with correct displayed page numbers.
```

#### Link Injection (why post-assembly)

`fitz.LINK_GOTO` links embedded in a standalone `toc_doc` that point to content pages are **out-of-range** (`target >= toc_doc.page_count`) and silently discarded by PyMuPDF before `insert_pdf()` can remap them.

**Solution:** `inject_toc_links()` is called AFTER `combined_doc` is assembled and section indices are shifted. It operates directly on `combined_doc`'s ToC pages, making all link targets valid absolute page indices in the same document.

#### Entry Layout

All pages use the same Y coordinate formula:
```
y_text = TOC_TOP_MARGIN + (row_within_page × TOC_LINE_HEIGHT)
```
Page 1 additionally draws the heading "TABLE OF CONTENTS" at `y=50` using font `"hebo"` (Helvetica-Bold).

#### Public API

```python
build_toc(sections, page_rect=None) -> tuple[fitz.Document, int]
```
- `sections`: `list[SectionInfo]` — content-only page indices (pre-prepend)
- `page_rect`: A4 (595×842) default when `None`
- Returns: `(toc_doc, toc_page_count)` — caller must close `toc_doc`

```python
inject_toc_links(combined_doc, sections, toc_page_count, page_rect) -> None
```
- `sections`: page indices **already shifted** by `toc_page_count`
- Inserts `fitz.LINK_GOTO` covering `[TOC_LEFT_MARGIN, y_text-font_size, TOC_RIGHT_MARGIN, y_text+2]` on each entry row
- Links target `section.start_page` (top-left of first section page)

---

### 7.8 `modules/page_numbering.py`

```python
apply_master_page_numbers(doc, toc_page_count=0, overlay_config=None) -> None
```
Iterates every page of `doc` and inserts `"Page {n} of {total}"` right-aligned to `PAGE_NUMBER_X`.

Text width is measured via `fitz.get_text_length()` (PyMuPDF ≥ 1.18); falls back to `len(text) × font_size × 0.50` approximation on older builds.

Right-alignment formula:
```
insert_x = PAGE_NUMBER_X - text_width
```

`overlay_config` dict keys that override `config.py` defaults:
- `page_number_x` (float)
- `page_number_y` (float)
- `page_number_font_size` (int)

---

### 7.9 `modules/header_footer.py`

```python
apply_headers_and_footers(doc, header, footer, overlay_config=None) -> None
```

- `header` / `footer`: dicts with keys `"left"`, `"center"`, `"right"` (str)
- Operates on every page including ToC pages
- `overlay_config` keys: `header_y_pts`, `footer_y_pts`

Slot positioning:
| Slot | X formula |
|---|---|
| Left | `_LEFT_MARGIN` = 60 pts |
| Center | `(page_width - text_width) / 2` |
| Right | `page_width - _RIGHT_MARGIN - text_width` where `_RIGHT_MARGIN` = 60 pts |

Text width via `fitz.get_text_length()` (same fallback as page numbering).

---

### 7.10 `modules/config_manager.py`

```python
save_config(params, output_dir, filename_stem="config") -> Path
```
Writes `<filename_stem>.json`. Injects `"timestamp"` key with current UTC ISO 8601 string. Returns the written file path.

```python
load_config(config_path) -> dict
```
Reads JSON; back-fills any missing keys with defaults from `_default_config()` for forward-compatibility with older saved configs.

```python
build_params_from_form(form) -> dict
```
Converts flat Flask `request.form` dict to the canonical nested config structure. Handles type coercion for numeric fields with safe fallbacks.

**Full JSON schema:**
```json
{
  "timestamp":              "2026-02-24T07:08:29Z",
  "rtf_directory":          "C:/data/rtf",
  "output_directory":       "C:/data/output",
  "csv_path":               "",
  "header": {
    "left":   "",
    "center": "CONFIDENTIAL",
    "right":  "Study ABC-123"
  },
  "footer": {
    "left":   "2026-02-24",
    "center": "",
    "right":  ""
  },
  "header_y_pts":           28.0,
  "footer_y_pts":           820.0,
  "page_number_x":          540.0,
  "page_number_y":          818.0,
  "page_number_font_size":  8
}
```

---

### 7.11 `modules/process_logger.py`

`ProcessLogger` accumulates `LogEntry` namedtuples during a job; `flush()` writes `process.log` to disk.

**Public methods:**

| Method | Description |
|---|---|
| `log_conversion_ok(filename, master_start, master_end)` | Records OK status + page range |
| `log_conversion_error(filename, exc)` | Records ERROR + exception detail |
| `log_skip(filename, reason)` | Records SKIP (CSV entry without file) |
| `log_info(message)` | General info line (not file-specific) |
| `flush(output_dir, total_files, filename_stem="process")` | Writes `<stem>.log` to disk |

**Log line format:**
```
[2026-02-24T07:08:29Z] report01.rtf                     → OK    | Master pages: 3–8
[2026-02-24T07:08:31Z] report02.rtf                     → ERROR | FileNotFoundError: ...
[2026-02-24T07:08:33Z] SUMMARY                          → INFO  | 4 files | 48 pages | 1 errors
```

Filename column is left-padded to 40 characters; status column is left-padded to 5 characters.

The `lines` property returns all accumulated formatted lines for live streaming to the UI via the `/api/status` polling endpoint.

---

## 8. Configuration System

### 8.1 Saving

When a job completes successfully, `save_config()` writes the exact parameters used (including header/footer text, Y coordinates, directory paths) to `output_<ts>_config.json` in the output directory. This allows exact reproduction of any prior run.

### 8.2 Loading via UI

The UI has a "Load" section that uploads a saved `config.json`. The browser sends it to `POST /api/load-config`; Flask parses it and returns the field values as JSON. The frontend (`app.js`) then populates all form fields via `populateFieldsFromConfig()`.

### 8.3 Settings Override Precedence

```
Runtime values (from loaded JSON or UI form input)
    ↓ override
config.py hardcoded defaults
```

The `overlay_config` parameter passed to `apply_master_page_numbers()` and `apply_headers_and_footers()` contains the runtime values; those functions check for the override keys first, then fall back to `config.*`.

---

## 9. Flask API Endpoints

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Serves `templates/index.html` |
| `POST` | `/api/run` | Starts compilation job |
| `GET` | `/api/status/<job_id>` | Job status polling |
| `POST` | `/api/load-config` | Parse uploaded JSON → return field values |
| `GET` | `/api/download/<job_id>` | Stream final PDF |

### `POST /api/run`

**Content-type:** `multipart/form-data`

**Form fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `rtf_directory` | text | Yes | Absolute path to RTF input folder |
| `output_directory` | text | Yes | Absolute path to output folder |
| `header_left` | text | No | Header left slot text |
| `header_center` | text | No | Header center slot text |
| `header_right` | text | No | Header right slot text |
| `footer_left` | text | No | Footer left slot text |
| `footer_center` | text | No | Footer center slot text |
| `footer_right` | text | No | Footer right slot text |
| `header_y_pts` | number | No | Y position of header (pts, default 28) |
| `footer_y_pts` | number | No | Y position of footer (pts, default 820) |
| `page_number_x` | number | No | Right-edge X of page number (pts, default 540) |
| `page_number_y` | number | No | Y of page number (pts, default 818) |
| `page_number_font_size` | number | No | Page number font size (pts, default 8) |
| `csv_file` | file | No | CSV mapping file (see csv_handler) |

**Response:** `{"job_id": "uuid4-string"}`

### `GET /api/status/<job_id>`

**Response:**
```json
{
  "status":   "running",
  "progress": 65,
  "log":      ["[INFO] ...", "[OK] ..."],
  "error":    null
}
```
`log` is the full cumulative list (not a delta). The frontend tracks `logLinesSeen` and appends only new entries.

### `POST /api/load-config`

**Content-type:** `multipart/form-data`  
**Key:** `config_file` (JSON file)  
**Response:** Full config dict (same schema as saved JSON) for field pre-population.

### `GET /api/download/<job_id>`

Streams the PDF with `Content-Disposition: attachment; filename="output_<ts>.pdf"`. The filename is taken from `Path(pdf_path).name` so it preserves the timestamp from the job.

---

## 10. Frontend Implementation

### 10.1 `templates/index.html`

Single-page layout with three vertical sections:

1. **Top bar** — application title + "Run Job" / "Download PDF" buttons
2. **Main content** — two-column grid:
   - **Left panel** — Input Configuration: RTF dir, Output dir, CSV upload, Load Config, page number coordinate inputs
   - **Right panel** — Header & Footer: 3+3 text inputs, Y-coordinate inputs, progress bar + error box (hidden until job runs)
3. **Log panel** — fixed-height, scrollable monospaced log pane at the bottom

### 10.2 `static/css/style.css`

- **Design language:** VSCode Dark+ colour palette using CSS custom properties (`--bg-shell`, `--bg-panel`, etc.)
- **Font:** `Arial, "Helvetica Neue", Helvetica, sans-serif` for UI; `"Consolas", "Courier New", monospace` for log/path inputs
- **Colour tokens:**

| Token | Value | Use |
|---|---|---|
| `--bg-shell` | `#1e1e1e` | Outer background |
| `--bg-panel` | `#252526` | Panel interior |
| `--bg-panel-hdr` | `#2d2d30` | Panel header band + top bar |
| `--bg-input` | `#3c3c3c` | Input fields |
| `--bg-log` | `#1a1a1a` | Log pane |
| `--border` | `#3f3f46` | All borders |
| `--border-focus` | `#007fd4` | Input focus ring |
| `--text-primary` | `#d4d4d4` | Main body text |
| `--text-muted` | `#858585` | Labels, placeholders |
| `--text-subhdr` | `#9cdcfe` | Panel subheadings |
| `--text-log` | `#b5cea8` | Default log line colour |
| `--text-error` | `#f44747` | Error log lines + error box |
| `--text-ok` | `#4ec9b0` | OK log lines |
| `--text-warn` | `#dcdcaa` | Skip/warn log lines |

- Log lines are coloured by class appended in JavaScript: `.log-err`, `.log-ok`, `.log-warn`, `.log-info`
- Responsive: single-column below 780 px viewport width

### 10.3 `static/js/app.js`

**Key functions:**

| Function | Description |
|---|---|
| `lineClass(line)` | Classifies a log line string into a CSS colour class by keyword matching |
| `appendLogLines(lines)` | Appends only new log lines (beyond `logLinesSeen`) to log pane with colour `<span>` elements |
| `setProgress(pct, label)` | Updates progress bar width and label |
| `startPolling(jobId)` | Starts `setInterval` at 1500 ms calling `/api/status/<jobId>` |
| `stopPolling()` | Clears the interval |
| `populateFieldsFromConfig(cfg)` | Maps loaded config dict fields to form input elements by ID |
| `buildFormData()` | Collects all form fields + CSV file into a `FormData` |

**Run Job flow:**
1. Reset UI state, disable Run button, show progress container
2. `buildFormData()` → `fetch('/api/run', {method:'POST', body:fd})`
3. Extract `job_id` from response
4. `startPolling(job_id)` — each tick appends new log lines, updates bar
5. On `status === "complete"`: stop polling, enable Download button, store `job_id` in `btn-download.dataset.jobId`
6. On `status === "error"`: stop polling, show error box

**Download:** Creates a temporary `<a href="/api/download/<id>" download>` element, clicks it programmatically, then removes it.

**Config load flow:**
1. User picks a `.json` file in the "Load Previous Config" input
2. Clicks "Load" → `fetch('/api/load-config', ...)` with the file in `FormData`
3. On success: `populateFieldsFromConfig(data)` fills all inputs; shows timestamp in status line for 5 seconds

---

## 11. Output Artefacts

All three files use the same ISO 8601 UTC timestamp stem (`YYYYMMDDTHHMMSSz` — no colons, Windows-safe):

| File | Name pattern | Description |
|---|---|---|
| Final PDF | `output_<ts>.pdf` | Compiled single PDF with ToC, overlays, bookmarks |
| Config | `output_<ts>_config.json` | Job parameter snapshot with audit timestamp |
| Log | `output_<ts>.log` | Per-file conversion status + master page ranges |

**Intermediate PDFs** (per-RTF converted output) are written to the **RTF input directory** alongside their source files and are kept permanently.

**Error-case log:** If the job fails, a best-effort log is still flushed using a fresh timestamp. The `pdf_path` in the job registry remains `None`.

---

## 12. Coordinate System

PyMuPDF uses a coordinate system with:
- **Origin:** top-left corner of the page
- **Y axis:** increases downward
- **Units:** points (1 pt = 1/72 inch)

**Common page dimensions:**

| Format | Width (pts) | Height (pts) |
|---|---|---|
| A4 portrait | 595.28 | 841.89 |
| Letter portrait | 612.00 | 792.00 |

**Reference positions for A4:**
- Top of printable area: ~28–40 pts from top
- Bottom of printable area: ~800–820 pts from top
- Left margin: ~60 pts
- Right margin: ~535 pts (= 595 - 60)

The application uses the first page's actual `rect` from the merged content document to size ToC pages (`merged_doc[0].rect`), ensuring ToC pages match the RTF output page size exactly.

---

## 13. PyMuPDF Font Reference

PyMuPDF's `insert_text()` and `get_text_length()` accept only these built-in font name codes. **Do not use CSS/Word font names** — they will raise `ValueError`.

| Code | Full name |
|---|---|
| `helv` | Helvetica (regular) |
| `hebo` | **Helvetica-Bold** |
| `heit` | Helvetica-Oblique |
| `hebi` | Helvetica-BoldOblique |
| `cour` | Courier |
| `cobo` | Courier-Bold |
| `cobi` | Courier-BoldOblique |
| `tiro` | Times-Roman |
| `tibo` | Times-Bold |
| `tiit` | Times-Italic |
| `tibi` | Times-BoldItalic |
| `symb` | Symbol |
| `zadb` | ZapfDingbats |

The ToC heading uses `"hebo"`. All other application text uses `"helv"`.

To use an embedded system font (e.g. Arial), create a `fitz.Font` object and pass it via `fontfile` or `fontbuffer` — this is more complex and not used in this application.

---

## 14. Error Handling

### Pipeline errors

All exceptions within `_run_job()` are caught by the outer `try/except`:
1. `_update_job(job_id, status="error", error=str(exc))` — stored for UI display
2. `_append_log(job_id, f"[FATAL] {exc}")` — visible in log pane
3. Full traceback appended to log
4. Best-effort `plogger.flush()` attempted (with fresh timestamp as stem)

### Per-file conversion errors

Each `convert_rtf_to_pdf()` call is wrapped individually. A failure logs an error via `plogger.log_conversion_error()` and continues to the next file. If **all** conversions fail, a `RuntimeError` is raised to abort the job.

### Frontend errors

- HTTP-level errors (4xx/5xx) from `/api/run`: parsed and shown in error box
- Polling fetch errors: appended to log as `[ERR] Polling error: ...`
- Config load errors: shown in the yellow status line below the file picker

---

## 15. Extension Points

### 15.1 Nested PDF Bookmarks

Ready to implement with no module changes:

```python
# In app.py _run_job(), when building bookmark_entries:
bookmark_entries = [
    {
        "title": s.title,
        "table_number": s.table_number,
        "page_index": s.start_page,
        "level": 1 if is_top_level(s) else 2,  # add your logic
    }
    for s in sections
]
```

`bookmarks.build_toc_list()` already passes `entry.get("level", 1)` through unchanged.

### 15.2 Nested ToC Visual Indentation

Add indentation to `toc_generator._render_toc_pages()`:
```python
indent = (section.get("level", 1) - 1) * 20.0  # 20 pts per level
current_page.insert_text(
    fitz.Point(left_margin + indent, current_y), ...
)
```

### 15.3 Additional LibreOffice Candidate Paths

Add to `_WINDOWS_CANDIDATES` / `_LINUX_CANDIDATES` in `modules/libreoffice.py`.

### 15.4 Custom Fonts in Overlays

Replace `fontname="helv"` with a `fitz.Font` object and pass via `fontfile=` in `insert_text()`.

### 15.5 Persistent Job Registry

Replace the in-memory `JOBS` dict with a SQLite or Redis backend.  
Replace `threading.Thread` with Celery for production scale-out.

### 15.6 Watermarking

Insert a watermark SVG or text before other overlays using `page.insert_text()` with a low-opacity colour tuple, or `page.draw_rect()` / `page.insert_image()`.

---

## 16. Known Limitations

| Limitation | Detail |
|---|---|
| Server restart loses job history | `JOBS` dict is in-process memory. PDFs remain on disk but the Download button won't resolve them after restart. |
| LibreOffice must be on the same host | No remote conversion. LibreOffice is invoked as a subprocess by the Flask server. |
| Concurrent job interference | None at file level (each job uses its own timestamp-based stems). High concurrency could be limited by LibreOffice multi-instance behaviour on some systems. |
| Page size mismatch | If RTF files produce pages of different sizes, the ToC page size is taken from `merged_doc[0].rect`. All overlays use the coordinate system of each individual page. |
| No RTF pre-processing | SAS-generated RTF encoding quirks (e.g. Windows-only fonts, embedded EMF images) are passed directly to LibreOffice. Rendering fidelity depends on LibreOffice's RTF engine. |
| Dot leader precision | Dot leaders use character-width approximation for spacing. Minor misalignment may occur for very narrow or wide fonts. |
| Right-alignment approximation | On PyMuPDF builds older than 1.18, text width falls back to `len × size × 0.50`. This approximation may cause slight misalignment for "Page X of Y" and right-aligned footer text. |
| Config JSON not versioned | No schema version field. Future structural changes to the JSON format require manual migration of saved configs. |
