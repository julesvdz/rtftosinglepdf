# Architecture: RTF-to-PDF Compiler

**Version:** 1.0  
**Status:** Implemented  
**Language:** Python 3.10+  
**Framework:** Flask 3.x  
**PDF Engine:** PyMuPDF (fitz) 1.24+  
**RTF Converter:** LibreOffice headless subprocess  

---

## 1. Project Layout

```
rtftosinglepdf/
├── app.py                        # Flask application + background job runner
├── config.py                     # Hardcoded coordinate constants and defaults
├── requirements.txt              # Python package dependencies
├── plans/
│   └── architecture.md           # This document
├── modules/
│   ├── __init__.py
│   ├── libreoffice.py            # soffice autodetection + RTF→PDF subprocess
│   ├── rtf_parser.py             # Title extraction using striprtf
│   ├── csv_handler.py            # CSV mapping parser and resolver
│   ├── pdf_merger.py             # PyMuPDF page merging + SectionInfo tracking
│   ├── bookmarks.py              # Flat PDF bookmark injection (extensible)
│   ├── toc_generator.py          # Two-pass self-aware ToC page builder
│   ├── page_numbering.py         # "Page X of Y" overlay
│   ├── header_footer.py          # Header/footer text overlay
│   ├── config_manager.py         # JSON config save/load with ISO 8601 timestamp
│   └── process_logger.py         # Per-file conversion audit logger
├── static/
│   ├── css/style.css             # VSCode-dark theme
│   └── js/app.js                 # Fetch-based async polling
└── templates/
    └── index.html                # Single-page UI
```

---

## 2. Processing Pipeline

```
User submits form (POST /api/run)
        │
        ▼
Flask spawns daemon Thread (job_id = UUID)
        │
        ├── find_soffice()               [libreoffice.py]
        │
        ├── CSV uploaded?
        │     Yes → parse_csv()          [csv_handler.py]
        │     No  → alphanumeric sort + extract_title() per RTF [rtf_parser.py]
        │
        ├── For each RTF:
        │     convert_rtf_to_pdf()       [libreoffice.py]
        │     soffice --headless --convert-to pdf --outdir <tmp>
        │
        ├── merge_pdfs()                 [pdf_merger.py]
        │     Returns: (merged_doc, [SectionInfo])
        │
        ├── build_toc() — two-pass       [toc_generator.py]
        │     Pass 1: estimate ToC page count
        │     Pass 2: render final ToC with correct master page numbers
        │
        ├── prepend_pages()              [pdf_merger.py]
        │     Insert ToC at front of merged doc
        │
        ├── shift_section_info()         [pdf_merger.py]
        │     Offset all SectionInfo page indices by toc_page_count
        │
        ├── apply_headers_and_footers()  [header_footer.py]
        │     All pages: header left/center/right + footer left/center/right
        │
        ├── apply_master_page_numbers()  [page_numbering.py]
        │     All pages: "Page X of Y" at (PAGE_NUMBER_X, PAGE_NUMBER_Y)
        │
        ├── build_toc_list() + inject_bookmarks()   [bookmarks.py]
        │     Flat PDF outline (set_toc)
        │
        ├── doc.save() → compiled_output.pdf
        │
        ├── save_config()               [config_manager.py]
        │     Writes config.json with ISO 8601 timestamp
        │
        └── plogger.flush()             [process_logger.py]
              Writes process.log with page ranges

Frontend polls GET /api/status/<job_id> every 1.5 s
→ streams log lines + progress bar updates
→ enables Download button on status == "complete"
```

---

## 3. Module Responsibilities

### `config.py`
Central repository for all layout constants expressed in PDF points  
(1 pt = 1/72 inch). All overlay coordinate decisions live here:

| Constant | Default | Purpose |
|---|---|---|
| `PAGE_NUMBER_X` | 540 | Right-edge X for "Page X of Y" |
| `PAGE_NUMBER_Y` | 818 | Y position of page number |
| `HEADER_Y_DEFAULT` | 28 | Default header Y from top |
| `FOOTER_Y_DEFAULT` | 820 | Default footer Y from top |
| `TOC_LEFT_MARGIN` | 60 | Left start of ToC entries |
| `TOC_RIGHT_MARGIN` | 540 | Right boundary / page number column |
| `TOC_LINE_HEIGHT` | 18 | Vertical spacing between ToC rows |

UI values from the JSON config override these at runtime.

---

### `modules/libreoffice.py`

**Autodetection strategy (in order):**
1. `shutil.which('soffice')` — Linux/macOS PATH
2. `shutil.which('soffice.exe')` — Windows PATH
3. Hardcoded Windows paths (`Program Files`, `Program Files (x86)`)
4. Hardcoded Linux paths (`/usr/bin`, `/usr/lib/libreoffice/...`)
5. macOS application bundle path
6. `RuntimeError` if nothing found

**Conversion:**  
`soffice --headless --norestore --nofirststartwizard --convert-to pdf --outdir <tmp> <rtf>`

---

### `modules/rtf_parser.py`

Uses `striprtf.striprtf()` to decode RTF control words. Reads only the  
first 16 KB of each file for performance. Returns the first non-blank  
plain-text line, truncated at 256 characters. Falls back to filename stem  
if no text can be extracted.

---

### `modules/csv_handler.py`

**CSV schema (case-insensitive column headers):**

| Column | Aliases | Required |
|---|---|---|
| `RTF_Filename` | `filename`, `file` | Yes |
| `Table_Number` | `table_no`, `number` | No |
| `Title` | `description`, `label` | Yes |

Row order in CSV dictates final document assembly sequence.  
`resolve_entries_against_directory()` filters out entries whose RTF file  
does not exist in the specified directory.

---

### `modules/pdf_merger.py`

`merge_pdfs()` accepts a list of `(pdf_path, title, table_number, rtf_name)`  
tuples and returns a merged `fitz.Document` plus a `list[SectionInfo]`.

`SectionInfo` tracks:
- `start_page` / `end_page` — 0-based indices
- `master_start` / `master_end` — 1-based properties (for display/logging)
- `page_count` — convenience property

`prepend_pages()` creates a fresh combined document with ToC pages first,  
then content. Returns the new doc and the prepend count.

`shift_section_info()` adjusts all `SectionInfo` page indices after prepend.

---

### `modules/toc_generator.py`

**Two-pass algorithm:**

```
Pass 1 — Estimate
  entries_per_page = (page_height - top_margin - bottom_margin) / line_height
  estimated_toc_pages = ceil(num_sections / entries_per_page)

  Render a draft ToC with this estimate to see the actual page count.
  If actual ≠ estimated, iterate once more (convergence guaranteed in ≤ 2 passes).

Pass 2 — Final render
  displayed_page_num = section.start_page + toc_page_count + 1
  link target (0-based) = section.start_page + toc_page_count
  Inject fitz.LINK_GOTO links on each entry row.
```

Each ToC entry row contains:
- Table number + title (left-aligned)
- Dot leaders (centred gap)
- Master page number (right-aligned to `TOC_RIGHT_MARGIN`)

---

### `modules/bookmarks.py`

`build_toc_list(entries)` converts dicts to PyMuPDF's `[level, title, page_1based]`  
format. The `level` key in each entry dict defaults to `1` (flat), but  
callers can set higher values (2, 3, …) to build nested hierarchies in  
the future without modifying this module.

`inject_bookmarks(doc, toc)` calls `doc.set_toc(toc)` in-place.

---

### `modules/page_numbering.py`

Iterates every page and inserts `"Page {n} of {total}"` right-aligned to  
`PAGE_NUMBER_X`. Uses `fitz.get_text_length()` for precise right-alignment;  
falls back to a character-width approximation on older PyMuPDF builds.

---

### `modules/header_footer.py`

Draws a three-slot (left / center / right) band at a configurable Y  
coordinate on every page:

- **Left:** inserted at `LEFT_MARGIN` (60 pt)  
- **Center:** computed as `(page_width - text_width) / 2`  
- **Right:** right edge aligned to `page_width - RIGHT_MARGIN` (60 pt)

---

### `modules/config_manager.py`

`save_config(params, output_dir)` merges caller params with defaults and  
writes `config.json`, injecting a fresh `"timestamp"` key.

`load_config(path)` reads the file and back-fills any missing keys with  
current defaults (forward-compatible with older saved configs).

`build_params_from_form(form)` converts a flat Flask `request.form` dict  
into the canonical nested config structure.

---

### `modules/process_logger.py`

Each `ProcessLogger` instance accumulates `LogEntry` namedtuples in memory  
during a job run. On `flush(output_dir, total_files)`, all entries plus a  
summary line are written to `process.log`.

Log line format:
```
[2026-02-23T13:21:00Z] report01.rtf                     → OK    | Master pages: 3–8
[2026-02-23T13:21:02Z] report02.rtf                     → ERROR | FileNotFoundError: ...
[2026-02-23T13:21:05Z] SUMMARY                          → INFO  | 2 files | 12 pages | 0 errors
```

---

## 4. API Endpoints

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | Serve the main UI |
| `POST` | `/api/run` | Start a new compilation job |
| `GET` | `/api/status/<job_id>` | Poll job state (status, progress, log) |
| `POST` | `/api/load-config` | Parse uploaded config.json → return field values |
| `GET` | `/api/download/<job_id>` | Stream compiled PDF |

---

## 5. JSON Config Schema

```json
{
  "timestamp":              "2026-02-23T13:20:00Z",
  "rtf_directory":          "C:/data/rtf_files",
  "output_directory":       "C:/data/output",
  "csv_path":               "",
  "header": {
    "left":   "",
    "center": "CONFIDENTIAL",
    "right":  "Study ABC-123"
  },
  "footer": {
    "left":   "2026-02-23",
    "center": "",
    "right":  ""
  },
  "header_y_pts":           28,
  "footer_y_pts":           820,
  "page_number_x":          540,
  "page_number_y":          818,
  "page_number_font_size":  8
}
```

---

## 6. Output Artefacts

After a successful job, the `output_directory` contains:

| File | Description |
|---|---|
| `compiled_output.pdf` | Final compiled PDF with ToC, overlays, bookmarks |
| `config.json` | All job parameters with audit timestamp |
| `process.log` | Per-file conversion status and master page ranges |

Temporary per-section PDFs are written to `_rtf2pdf_tmp/` inside the output  
directory and automatically deleted when the job finishes (success or error).

---

## 7. Extending to Nested Bookmarks

The bookmark system is designed for future nesting. To add hierarchy:

1. Populate the `"level"` key in each bookmark entry dict  
   (`1` = top-level, `2` = subsection, etc.)
2. `build_toc_list()` in [`modules/bookmarks.py`](../modules/bookmarks.py)  
   already passes the `level` value through unchanged.
3. No other changes are required.

---

## 8. Dependencies

| Package | Version | Purpose |
|---|---|---|
| `flask` | ≥ 3.0 | Web framework |
| `pymupdf` | ≥ 1.24 | PDF merge, overlay, links, bookmarks |
| `striprtf` | ≥ 0.0.26 | RTF → plain text for title extraction |
| `Werkzeug` | ≥ 3.0 | Flask dependency; `secure_filename` for uploads |

---

## 9. Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Start Flask development server
python app.py

# Production (Waitress example)
pip install waitress
python -m waitress --host=0.0.0.0 --port=5000 app:app
```

Navigate to `http://localhost:5000` in a browser.

---

## 10. Known Constraints

- LibreOffice must be installed on the host running the Flask server.  
  It is not bundled with the application.
- Concurrent jobs share the same Python process. Each job uses an isolated  
  temp directory; there is no file-system collision risk between jobs.
- The in-memory `JOBS` registry is lost on server restart — completed job  
  PDFs remain on disk, but the Download button will no longer resolve them.
- PDF coordinate system: origin at **top-left**, Y increases **downward**.  
  Typical A4 page = 595.28 × 841.89 pt. Letter = 612 × 792 pt.
