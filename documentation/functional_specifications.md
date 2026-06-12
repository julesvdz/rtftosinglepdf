# Functional Specifications

**Document Title:** RTF-to-PDF Compiler — Functional Specifications  
**Document ID:** FS-RTF2PDF-001  
**Version:** 1.0  
**Status:** Draft  
**Effective Date:** 2026-02-24  
**Classification:** GCP Validated System  

---

## Document Control

| Field | Value |
|---|---|
| Prepared By | *\<Author Name\>* |
| Reviewed By | *\<Reviewer Name\>* |
| Approved By | *\<Approver Name\>* |
| Department | *\<Department\>* |
| System Name | RTF-to-PDF Compiler |
| System Category | GAMP 5 Category 4 — Configured Product |

### Change History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-02-24 | *\<Author\>* | Initial release |

---

## 1. Purpose and Scope

### 1.1 Purpose

This document defines the functional specifications for the RTF-to-PDF Compiler, a web-based document processing system used to compile SAS-generated Rich Text Format (RTF) output files into a single annotated Portable Document Format (PDF) file for use in clinical study reporting.

This document is intended to support qualification activities under a V-model validation lifecycle and shall serve as the primary basis for Operational Qualification (OQ) test case development.

### 1.2 Scope

This specification covers all user-visible and system-level functional behaviours of the RTF-to-PDF Compiler application, including:

- Input file and parameter ingestion
- Document conversion and assembly processing
- Table of Contents generation
- Page number, header, and footer overlay
- PDF bookmark injection
- Configuration persistence and recall
- Audit trail generation
- Output artefact naming and storage

### 1.3 Out of Scope

- Installation qualification (IQ) procedures
- Network infrastructure or operating system configuration
- LibreOffice installation and qualification
- User authentication and access control (not implemented in current version)
- Electronic signature functionality

---

## 2. Applicable Documents and References

| Reference ID | Document Title |
|---|---|
| URS-RTF2PDF-001 | User Requirements Specification — RTF-to-PDF Compiler |
| GAMP 5 | Good Automated Manufacturing Practice Guide, 5th Edition |
| 21 CFR Part 11 | Electronic Records; Electronic Signatures |
| ICH E6(R2) | Good Clinical Practice Consolidated Guideline |
| ICH M10 | Bioanalytical Method Validation |

---

## 3. Definitions and Abbreviations

| Term | Definition |
|---|---|
| CSV | Comma-Separated Values — a plain-text tabular data format |
| GCP | Good Clinical Practice |
| GAMP | Good Automated Manufacturing Practice |
| IQ | Installation Qualification |
| JSON | JavaScript Object Notation — a lightweight data interchange format |
| OQ | Operational Qualification |
| PDF | Portable Document Format |
| PQ | Performance Qualification |
| RTF | Rich Text Format — a document format produced by SAS procedures |
| SAS | Statistical Analysis System |
| ToC | Table of Contents |
| URS | User Requirements Specification |
| UTC | Coordinated Universal Time |

---

## 4. Specification Identifier Convention

Each functional specification uses the following identifier format:

```
FS-{CATEGORY}-{SEQ}

Where:
  CATEGORY  = INP (Input)
             | PAR (Parameters)
             | PRO (Processing)
             | TOC (Table of Contents)
             | OUT (Output)
             | AUD (Audit Trail)
             | CFG (Configuration Management)
             | ERR (Error Handling)
  SEQ       = Three-digit zero-padded sequence number
```

---

## 5. Input Specifications

### FS-INP-001 — RTF Input Directory

| Field | Value |
|---|---|
| **ID** | FS-INP-001 |
| **Category** | Input |
| **Priority** | Critical |
| **Title** | RTF Input Directory Selection |

**Description:**  
The system shall accept a user-specified absolute filesystem path designating the directory that contains the RTF source files to be compiled.

**Acceptance Criteria:**  
- AC-INP-001-01: The system shall validate that the specified path exists and is a directory before initiating any processing.
- AC-INP-001-02: The system shall reject the submission with an informative error message if the path does not exist or is not a directory.
- AC-INP-001-03: The directory path shall be preserved in the configuration JSON output artefact.

---

### FS-INP-002 — RTF File Discovery

| Field | Value |
|---|---|
| **ID** | FS-INP-002 |
| **Category** | Input |
| **Priority** | Critical |
| **Title** | RTF File Enumeration and Ordering |

**Description:**  
When no CSV mapping file is provided, the system shall automatically discover all RTF files in the specified input directory and order them alphanumerically by filename (case-insensitive) to determine the document assembly sequence.

**Acceptance Criteria:**  
- AC-INP-002-01: The system shall discover files with the `.rtf` and `.RTF` extensions.
- AC-INP-002-02: Files shall be sorted case-insensitively by filename.
- AC-INP-002-03: Duplicate filenames differing only in case (e.g. on case-insensitive file systems) shall appear only once in the assembly sequence.
- AC-INP-002-04: If no RTF files are found, the system shall terminate processing and report an informative error.

---

### FS-INP-003 — CSV Mapping File (Optional)

| Field | Value |
|---|---|
| **ID** | FS-INP-003 |
| **Category** | Input |
| **Priority** | High |
| **Title** | CSV Mapping File for Document Ordering and Titling |

**Description:**  
The system shall accept an optional CSV mapping file that defines the assembly sequence, table reference number, and display title for each RTF file. When a CSV is provided, its row order shall determine the final document sequence, superseding alphanumeric ordering.

**Acceptance Criteria:**  
- AC-INP-003-01: The CSV file shall contain a header row with at minimum the columns `RTF_Filename` and `Title` (case-insensitive, with documented aliases).
- AC-INP-003-02: The `Table_Number` column is optional; if absent or blank, no table number prefix is displayed.
- AC-INP-003-03: Assembly order shall follow CSV row sequence from top to bottom.
- AC-INP-003-04: CSV rows referencing RTF filenames not found in the input directory shall be skipped; the skip event shall be recorded in the process log.
- AC-INP-003-05: The system shall raise an informative error if the CSV lacks required columns.
- AC-INP-003-06: The CSV shall be accepted via file upload through the web interface.
- AC-INP-003-07: Column headers shall be recognised case-insensitively with the following documented aliases:

| Canonical column | Accepted aliases |
|---|---|
| `RTF_Filename` | `filename`, `file`, `RTF filename` |
| `Table_Number` | `Table_No`, `TableNo`, `number` |
| `Title` | `description`, `label` |

---

### FS-INP-004 — Configuration JSON Reload

| Field | Value |
|---|---|
| **ID** | FS-INP-004 |
| **Category** | Input |
| **Priority** | Medium |
| **Title** | Loading a Previously Saved Configuration |

**Description:**  
The system shall allow a user to upload a previously saved configuration JSON file through the web interface. Upon successful upload and parsing, all configurable UI fields shall be pre-populated with the values stored in that file.

**Acceptance Criteria:**  
- AC-INP-004-01: The system shall accept JSON files conforming to the application configuration schema.
- AC-INP-004-02: All parameters present in the JSON file shall be applied to the corresponding UI input fields without requiring manual re-entry.
- AC-INP-004-03: Parameters absent from the JSON file (e.g. from an older version) shall be back-filled with system defaults.
- AC-INP-004-04: The system shall display the timestamp stored in the loaded file to confirm the version identity of the restored configuration.
- AC-INP-004-05: Malformed or invalid JSON files shall produce an informative error message; no fields shall be altered.

---

## 6. Parameter Specifications

### FS-PAR-001 — Output Directory

| Field | Value |
|---|---|
| **ID** | FS-PAR-001 |
| **Category** | Parameters |
| **Priority** | Critical |
| **Title** | Output Directory Path |

**Description:**  
The system shall accept a user-specified absolute filesystem path for all output artefacts (compiled PDF, configuration JSON, process log). The directory shall be created automatically if it does not yet exist.

**Acceptance Criteria:**  
- AC-PAR-001-01: A non-empty output directory path shall be required before job submission is accepted.
- AC-PAR-001-02: The system shall create the output directory (including any required parent directories) if it does not exist at the time of processing.
- AC-PAR-001-03: The output directory path shall be preserved in the configuration JSON artefact.

---

### FS-PAR-002 — Header Text Fields

| Field | Value |
|---|---|
| **ID** | FS-PAR-002 |
| **Category** | Parameters |
| **Priority** | High |
| **Title** | Header Band — Left, Center, Right Text |

**Description:**  
The system shall provide three independent text input fields for the header band of the compiled PDF: Left, Center, and Right. These strings shall appear on every page of the final document, including Table of Contents pages.

**Acceptance Criteria:**  
- AC-PAR-002-01: Each of the three header slots (Left, Center, Right) shall accept free-text strings.
- AC-PAR-002-02: An empty string for any slot shall result in no text being rendered in that position.
- AC-PAR-002-03: Left text shall be left-aligned at a fixed left margin of 60 points from the page edge.
- AC-PAR-002-04: Center text shall be horizontally centred on the page using measured text width.
- AC-PAR-002-05: Right text shall be right-aligned such that its right edge falls at a fixed margin of 60 points from the right page edge.
- AC-PAR-002-06: Header text shall appear identically on every page of the document.

---

### FS-PAR-003 — Footer Text Fields

| Field | Value |
|---|---|
| **ID** | FS-PAR-003 |
| **Category** | Parameters |
| **Priority** | High |
| **Title** | Footer Band — Left, Center, Right Text |

**Description:**  
The system shall provide three independent text input fields for the footer band: Left, Center, and Right. These strings shall appear on every page of the final document, including Table of Contents pages.

**Acceptance Criteria:**  
- Same structural criteria as FS-PAR-002 (AC-PAR-002-01 through AC-PAR-002-06), applied to the footer band.

---

### FS-PAR-004 — Header Vertical Position

| Field | Value |
|---|---|
| **ID** | FS-PAR-004 |
| **Category** | Parameters |
| **Priority** | Medium |
| **Title** | Header Y-Coordinate (Points from Top) |

**Description:**  
The system shall allow the user to specify the vertical position of the header text as a distance in points from the top edge of the page.

**Acceptance Criteria:**  
- AC-PAR-004-01: The field shall accept a numeric value (integer or decimal) expressed in PDF points.
- AC-PAR-004-02: The default value shall be **28 points** from the top of the page.
- AC-PAR-004-03: The specified value shall be applied uniformly to all pages.
- AC-PAR-004-04: The value shall be persisted in the configuration JSON artefact under key `header_y_pts`.

---

### FS-PAR-005 — Footer Vertical Position

| Field | Value |
|---|---|
| **ID** | FS-PAR-005 |
| **Category** | Parameters |
| **Priority** | Medium |
| **Title** | Footer Y-Coordinate (Points from Top) |

**Description:**  
The system shall allow the user to specify the vertical position of the footer text as a distance in points from the top edge of the page.

**Acceptance Criteria:**  
- AC-PAR-005-01: The default value shall be **820 points** from the top of the page.
- AC-PAR-005-02: The value shall be persisted in the configuration JSON artefact under key `footer_y_pts`.
- AC-PAR-005-03: The specified value shall be applied uniformly to all pages.

---

### FS-PAR-006 — Master Page Number Coordinates

| Field | Value |
|---|---|
| **ID** | FS-PAR-006 |
| **Category** | Parameters |
| **Priority** | Medium |
| **Title** | Master Page Number Overlay Position |

**Description:**  
The system shall allow the user to configure the position and font size of the "Page X of Y" master page number overlay via three numeric input fields: X coordinate (right edge), Y coordinate, and font size in points.

**Acceptance Criteria:**  
- AC-PAR-006-01: Default X (right edge) shall be **540 points** from the left of the page.
- AC-PAR-006-02: Default Y shall be **818 points** from the top of the page.
- AC-PAR-006-03: Default font size shall be **8 points**.
- AC-PAR-006-04: All three values shall be persisted in the configuration JSON artefact under keys `page_number_x`, `page_number_y`, `page_number_font_size`.
- AC-PAR-006-05: The page number text shall be right-aligned to the specified X coordinate using measured text width.

---

## 7. Processing Specifications

### FS-PRO-001 — RTF-to-PDF Conversion Engine

| Field | Value |
|---|---|
| **ID** | FS-PRO-001 |
| **Category** | Processing |
| **Priority** | Critical |
| **Title** | LibreOffice Headless RTF-to-PDF Conversion |

**Description:**  
The system shall convert each source RTF file to an intermediate PDF using LibreOffice in headless mode. The LibreOffice executable shall be automatically detected on the host system without manual path configuration.

**Acceptance Criteria:**  
- AC-PRO-001-01: The system shall locate the LibreOffice executable by checking the system PATH and a set of standard installation paths for Windows, Linux, and macOS.
- AC-PRO-001-02: The conversion command shall be invoked as: `soffice --headless --norestore --nofirststartwizard --convert-to pdf --outdir <rtf_dir> <source.rtf>`
- AC-PRO-001-03: Each intermediate PDF shall be written to the RTF input directory alongside its source RTF file.
- AC-PRO-001-04: The intermediate PDF filename shall be the source RTF stem with a `.pdf` extension.
- AC-PRO-001-05: Intermediate PDFs shall be retained permanently after processing; they shall not be deleted by the application.
- AC-PRO-001-06: Each conversion shall be subject to a configurable timeout (default: 120 seconds). A file exceeding this timeout shall be recorded as an error; processing continues with remaining files.
- AC-PRO-001-07: If LibreOffice is not found, the system shall terminate the job with an informative error before any conversion is attempted.

---

### FS-PRO-002 — Title Extraction from RTF

| Field | Value |
|---|---|
| **ID** | FS-PRO-002 |
| **Category** | Processing |
| **Priority** | High |
| **Title** | Automatic Title Extraction from RTF Content |

**Description:**  
When no CSV mapping is provided, the system shall extract a display title for each RTF file by reading its content and identifying the first non-blank plain-text line after stripping RTF control words.

**Acceptance Criteria:**  
- AC-PRO-002-01: Only the first 16,384 bytes of each RTF file shall be read for title extraction purposes.
- AC-PRO-002-02: RTF control words, control symbols, and structural braces shall be stripped prior to text identification.
- AC-PRO-002-03: The first non-blank line of plain text shall be used as the title, truncated at 256 characters.
- AC-PRO-002-04: If no plain text can be extracted, the RTF filename stem (without extension) shall be used as the fallback title.
- AC-PRO-002-05: Title extraction shall not fail fatally; any error shall result in the filename-stem fallback.

---

### FS-PRO-003 — PDF Document Merging

| Field | Value |
|---|---|
| **ID** | FS-PRO-003 |
| **Category** | Processing |
| **Priority** | Critical |
| **Title** | Sequential Merging of Converted PDFs |

**Description:**  
The system shall merge all converted per-section PDFs into a single contiguous PDF document in the assembly sequence determined by FS-INP-002 or FS-INP-003.

**Acceptance Criteria:**  
- AC-PRO-003-01: Pages from each section shall appear in the correct assembly order.
- AC-PRO-003-02: The system shall track the start page index (0-based) and end page index (0-based, inclusive) for each RTF section within the merged document.
- AC-PRO-003-03: Empty intermediate PDFs (0 pages) shall be silently skipped.
- AC-PRO-003-04: The original page content, fonts, and images of each RTF-derived PDF shall be preserved in the merged output.

---

### FS-PRO-004 — Dual-Layer Page Numbering

| Field | Value |
|---|---|
| **ID** | FS-PRO-004 |
| **Category** | Processing |
| **Priority** | Critical |
| **Title** | Dual-Layer Page Numbering |

**Description:**  
The compiled PDF shall carry two independent page numbering layers: (1) the original page numbers embedded within each RTF source document, preserved at their original position; and (2) a master "Page X of Y" overlay applied to every page of the final document by the application.

**Acceptance Criteria:**  
- AC-PRO-004-01: Original RTF page numbers shall remain visible at their original positions within the content area and shall not be removed or obscured.
- AC-PRO-004-02: The master "Page X of Y" overlay shall appear on every page of the final PDF, including Table of Contents pages.
- AC-PRO-004-03: The master page count (Y) shall reflect the total page count of the final compiled PDF after ToC prepend.
- AC-PRO-004-04: The master overlay shall be right-aligned to the X coordinate specified in FS-PAR-006.
- AC-PRO-004-05: Master page numbers shall be sequentially numbered starting from 1 (page 1 of N … page N of N).

---

### FS-PRO-005 — Header and Footer Application

| Field | Value |
|---|---|
| **ID** | FS-PRO-005 |
| **Category** | Processing |
| **Priority** | High |
| **Title** | Uniform Header and Footer Overlay |

**Description:**  
The system shall apply the user-specified header and footer text on every page of the final compiled PDF, including Table of Contents pages.

**Acceptance Criteria:**  
- AC-PRO-005-01: Header and footer strings shall appear identically on every page with no variation.
- AC-PRO-005-02: Three-slot positioning (Left, Center, Right) shall be applied as specified in FS-PAR-002 and FS-PAR-003.
- AC-PRO-005-03: Header/footer shall be overlaid after all document merging operations and prior to PDF save.
- AC-PRO-005-04: Pages on which all six text slots are empty shall not have any header/footer content added.

---

## 8. Table of Contents Specifications

### FS-TOC-001 — ToC Generation

| Field | Value |
|---|---|
| **ID** | FS-TOC-001 |
| **Category** | Table of Contents |
| **Priority** | Critical |
| **Title** | Automatic Table of Contents Generation |

**Description:**  
The system shall automatically generate a Table of Contents and insert it at the beginning of the compiled PDF, before all RTF-derived content.

**Acceptance Criteria:**  
- AC-TOC-001-01: The ToC shall list every section included in the compiled document.
- AC-TOC-001-02: Each ToC entry shall display the section title as it appears in the CSV `Title` column (or as extracted by FS-PRO-002).
- AC-TOC-001-03: Each entry shall display the table reference number (`Table_Number`) when provided, prefixed to the title.
- AC-TOC-001-04: The ToC heading "TABLE OF CONTENTS" shall appear on the first ToC page.
- AC-TOC-001-05: Entry rows shall be separated by dot leaders between the title and the page number.
- AC-TOC-001-06: The ToC shall be inserted before all RTF-derived content pages.

---

### FS-TOC-002 — Self-Aware ToC Page Count

| Field | Value |
|---|---|
| **ID** | FS-TOC-002 |
| **Category** | Table of Contents |
| **Priority** | Critical |
| **Title** | ToC Page Count Self-Correction |

**Description:**  
The master page numbers displayed in the ToC shall account for the number of pages occupied by the ToC itself. The system shall use a two-pass algorithm to resolve the circular dependency between ToC page count and displayed page numbers.

**Acceptance Criteria:**  
- AC-TOC-002-01: Page numbers displayed in the ToC entries shall be master page numbers (1-based, inclusive of ToC pages).
- AC-TOC-002-02: The displayed page number for any section shall equal: `(section content start page, 1-based) + (number of ToC pages)`.
- AC-TOC-002-03: The two-pass convergence loop shall produce a stable ToC page count within at most two iterations.

---

### FS-TOC-003 — Hyperlinked ToC Entries

| Field | Value |
|---|---|
| **ID** | FS-TOC-003 |
| **Category** | Table of Contents |
| **Priority** | High |
| **Title** | Clickable ToC Navigation Links |

**Description:**  
Each entry row in the Table of Contents shall be a clickable hyperlink that navigates the PDF reader to the first page of the corresponding section.

**Acceptance Criteria:**  
- AC-TOC-003-01: Clicking any part of a ToC entry row (from left margin to right boundary, spanning the full text band height) shall navigate to the first page of the referenced section.
- AC-TOC-003-02: Link targets shall be the absolute page indices within the final compiled PDF, accounting for the prepended ToC pages.
- AC-TOC-003-03: Each link shall navigate to the top-left corner of the target page (coordinate 0, 0).
- AC-TOC-003-04: Links shall function in standard PDF readers (e.g. Adobe Acrobat Reader).

---

## 9. Output Specifications

### FS-OUT-001 — Output File Naming Convention

| Field | Value |
|---|---|
| **ID** | FS-OUT-001 |
| **Category** | Output |
| **Priority** | Critical |
| **Title** | ISO 8601 Timestamped Output Filenames |

**Description:**  
All three output artefacts produced by a processing job shall be named using a common ISO 8601 UTC datetime stem derived from the job start time.

**Acceptance Criteria:**  
- AC-OUT-001-01: The timestamp stem shall follow the format `YYYYMMDDTHHMMSSz` (basic ISO 8601, no colons, UTC timezone indicator `Z`), e.g. `20260224T070829Z`.
- AC-OUT-001-02: The compiled PDF shall be named `output_<timestamp>.pdf`.
- AC-OUT-001-03: The configuration JSON shall be named `output_<timestamp>_config.json`.
- AC-OUT-001-04: The process log shall be named `output_<timestamp>.log`.
- AC-OUT-001-05: All three files shall be written to the user-specified output directory.
- AC-OUT-001-06: The timestamp shall be generated once at job start and used consistently across all three output files.

---

### FS-OUT-002 — Compiled PDF

| Field | Value |
|---|---|
| **ID** | FS-OUT-002 |
| **Category** | Output |
| **Priority** | Critical |
| **Title** | Compiled PDF Specification |

**Description:**  
The system shall produce a single PDF file containing: the Table of Contents, all RTF-derived content pages in assembly sequence, master page number overlays, header and footer overlays, and a PDF bookmark outline.

**Acceptance Criteria:**  
- AC-OUT-002-01: The PDF shall begin with the Table of Contents pages.
- AC-OUT-002-02: RTF content pages shall follow the ToC in assembly sequence order.
- AC-OUT-002-03: All overlays (header, footer, master page numbers) shall be present on every page.
- AC-OUT-002-04: The PDF shall contain a valid bookmark outline (outline tree) as specified in FS-OUT-004.
- AC-OUT-002-05: The PDF shall be a standards-compliant, non-password-protected file readable by ISO 32000-compatible viewers.
- AC-OUT-002-06: The PDF shall be optimised for file size using deflate compression and garbage collection.

---

### FS-OUT-003 — Configuration JSON Artefact

| Field | Value |
|---|---|
| **ID** | FS-OUT-003 |
| **Category** | Output |
| **Priority** | High |
| **Title** | Job Configuration JSON Persistence |

**Description:**  
Upon successful completion of each job, the system shall write the complete set of job parameters to a JSON file, enabling exact reconstruction of processing conditions at any future date.

**Acceptance Criteria:**  
- AC-OUT-003-01: The JSON file shall contain all fields defined in the configuration schema (Section 6 of this document).
- AC-OUT-003-02: The `timestamp` field shall contain the job start time in ISO 8601 UTC format `YYYY-MM-DDTHH:MM:SSZ`.
- AC-OUT-003-03: The JSON file shall be human-readable with 2-space indentation.
- AC-OUT-003-04: All values shall accurately reflect the parameters used to produce the corresponding compiled PDF.
- AC-OUT-003-05: The JSON file shall be loadable by the system to restore all UI fields (FS-INP-004).

**Configuration JSON Schema:**

```json
{
  "timestamp":              "string (ISO 8601 UTC)",
  "rtf_directory":          "string (absolute path)",
  "output_directory":       "string (absolute path)",
  "csv_path":               "string (absolute path or empty string)",
  "header": {
    "left":                 "string",
    "center":               "string",
    "right":                "string"
  },
  "footer": {
    "left":                 "string",
    "center":               "string",
    "right":                "string"
  },
  "header_y_pts":           "number (points from top)",
  "footer_y_pts":           "number (points from top)",
  "page_number_x":          "number (points from left, right-edge of text)",
  "page_number_y":          "number (points from top)",
  "page_number_font_size":  "integer (points)"
}
```

---

### FS-OUT-004 — PDF Bookmarks (Document Outline)

| Field | Value |
|---|---|
| **ID** | FS-OUT-004 |
| **Category** | Output |
| **Priority** | High |
| **Title** | PDF Bookmark Outline |

**Description:**  
The compiled PDF shall include an embedded PDF bookmark outline (navigation tree) with one entry per RTF section, enabling direct navigation from a PDF reader's bookmarks panel.

**Acceptance Criteria:**  
- AC-OUT-004-01: One bookmark entry shall exist for each RTF section included in the compiled document.
- AC-OUT-004-02: The bookmark structure shall be flat (single-level hierarchy; all entries at level 1).
- AC-OUT-004-03: Each bookmark title shall display the table reference number (if provided) followed by the section title.
- AC-OUT-004-04: Each bookmark shall navigate to the first page of its corresponding section.
- AC-OUT-004-05: Bookmark page targets shall use absolute page numbers within the final compiled PDF (inclusive of ToC pages).

---

### FS-OUT-005 — Intermediate PDF Files

| Field | Value |
|---|---|
| **ID** | FS-OUT-005 |
| **Category** | Output |
| **Priority** | Medium |
| **Title** | Intermediate Per-Section PDF Retention |

**Description:**  
The system shall retain the intermediate per-section PDFs produced by LibreOffice conversion in the RTF input directory. These files shall not be deleted at any point during or after processing.

**Acceptance Criteria:**  
- AC-OUT-005-01: Each intermediate PDF shall be written to the same directory as its source RTF file.
- AC-OUT-005-02: The intermediate PDF filename shall be the source RTF filename stem with `.pdf` extension.
- AC-OUT-005-03: Intermediate PDFs shall persist after job completion (success or failure).
- AC-OUT-005-04: Re-running the application shall overwrite existing intermediate PDFs with updated conversions.
- AC-OUT-005-05: No temporary files or directories shall be created in the output directory.

---

## 10. Audit Trail Specifications

### FS-AUD-001 — Process Log Generation

| Field | Value |
|---|---|
| **ID** | FS-AUD-001 |
| **Category** | Audit Trail |
| **Priority** | Critical |
| **Title** | Per-File Conversion Audit Log |

**Description:**  
The system shall produce a plain-text process log file for each job, recording the processing outcome and master page range for every RTF file processed.

**Acceptance Criteria:**  
- AC-AUD-001-01: The log file shall be named per FS-OUT-001 convention (`output_<timestamp>.log`).
- AC-AUD-001-02: Each log entry shall include: UTC timestamp, source filename, status code, and detail.
- AC-AUD-001-03: The log file shall record one entry for each RTF file attempted, with one of the following status codes:

| Code | Condition |
|---|---|
| `OK` | Conversion succeeded; master page range recorded |
| `ERROR` | Conversion or processing failure; exception detail recorded |
| `SKIP` | File referenced in CSV not found in input directory |
| `INFO` | General informational message (system events) |

- AC-AUD-001-04: For `OK` entries, the detail field shall state `Master pages: {start}–{end}` using 1-based master page numbers.
- AC-AUD-001-05: For `ERROR` entries, the detail field shall include the exception class name and message.
- AC-AUD-001-06: The final entry shall be a `SUMMARY` line: `{N} files | {P} pages | {E} errors`.
- AC-AUD-001-07: The log shall be written even when the job terminates due to a fatal error.
- AC-AUD-001-08: All timestamps in the log shall be in UTC ISO 8601 format `[YYYY-MM-DDTHH:MM:SSZ]`.

**Log Line Format:**
```
[YYYY-MM-DDTHH:MM:SSZ] <filename padded to 40 chars>  → <STATUS> | <detail>
```

---

### FS-AUD-002 — Audit Timestamp in Configuration JSON

| Field | Value |
|---|---|
| **ID** | FS-AUD-002 |
| **Category** | Audit Trail |
| **Priority** | High |
| **Title** | Configuration Artefact Timestamping |

**Description:**  
The configuration JSON artefact shall include an ISO 8601 UTC timestamp recording the date and time at which the job was executed. This timestamp shall be generated by the system and shall not be settable by the user.

**Acceptance Criteria:**  
- AC-AUD-002-01: The `timestamp` field shall be present in every configuration JSON artefact.
- AC-AUD-002-02: The timestamp format shall be `YYYY-MM-DDTHH:MM:SSZ` (UTC).
- AC-AUD-002-03: Any user-supplied `timestamp` value shall be silently overwritten by the system-generated value.
- AC-AUD-002-04: The timestamp shall reflect the moment of job completion (config write), not the job start.

---

## 11. Configuration Management Specifications

### FS-CFG-001 — Settings Persistence

| Field | Value |
|---|---|
| **ID** | FS-CFG-001 |
| **Category** | Configuration Management |
| **Priority** | High |
| **Title** | Automatic Parameter Persistence per Job |

**Description:**  
At the successful completion of each processing job, the system shall automatically save all configuration parameters to the JSON artefact without requiring any user action.

**Acceptance Criteria:**  
- AC-CFG-001-01: Configuration saving shall occur automatically upon successful job completion.
- AC-CFG-001-02: No additional user action shall be required to trigger the save.
- AC-CFG-001-03: The save operation shall not be exposed as a separate user-initiated action.

---

### FS-CFG-002 — Settings Forward-Compatibility

| Field | Value |
|---|---|
| **ID** | FS-CFG-002 |
| **Category** | Configuration Management |
| **Priority** | Medium |
| **Title** | Backward-Compatible Configuration Loading |

**Description:**  
When loading a configuration JSON file, the system shall tolerate missing keys by back-filling them with current system defaults. This ensures older configuration files remain loadable after application updates.

**Acceptance Criteria:**  
- AC-CFG-002-01: Keys present in the loaded JSON shall override system defaults.
- AC-CFG-002-02: Keys absent from the loaded JSON shall be populated with system defaults without error.
- AC-CFG-002-03: No user action shall be required to migrate an older configuration file.

---

## 12. Error Handling Specifications

### FS-ERR-001 — Per-File Error Isolation

| Field | Value |
|---|---|
| **ID** | FS-ERR-001 |
| **Category** | Error Handling |
| **Priority** | Critical |
| **Title** | Non-Fatal Per-File Conversion Errors |

**Description:**  
A failure to convert a single RTF file shall not abort the entire job. The failed file shall be recorded in the audit log and processing shall continue with remaining files.

**Acceptance Criteria:**  
- AC-ERR-001-01: If a single RTF conversion fails, the system shall log the error and proceed to the next file.
- AC-ERR-001-02: The failed file shall be excluded from the compiled PDF.
- AC-ERR-001-03: The process log shall record the `ERROR` status and exception detail for the failed file.
- AC-ERR-001-04: If all individual file conversions fail, the system shall abort processing and report a fatal error.

---

### FS-ERR-002 — Fatal Error Reporting

| Field | Value |
|---|---|
| **ID** | FS-ERR-002 |
| **Category** | Error Handling |
| **Priority** | Critical |
| **Title** | Fatal Processing Error Reporting |

**Description:**  
When an unrecoverable error occurs during job processing, the system shall report the error to the user through the web interface and attempt to preserve the partial audit log.

**Acceptance Criteria:**  
- AC-ERR-002-01: The job status shall be set to `error` upon any unhandled exception.
- AC-ERR-002-02: The error message shall be accessible through the `/api/status/<job_id>` endpoint.
- AC-ERR-002-03: The error message and full stack trace shall be appended to the in-memory log for display in the web UI.
- AC-ERR-002-04: A best-effort process log shall be written to the output directory even in the case of a fatal error.
- AC-ERR-002-05: The error state shall not prevent the user from immediately initiating a new job.

---

### FS-ERR-003 — Input Validation

| Field | Value |
|---|---|
| **ID** | FS-ERR-003 |
| **Category** | Error Handling |
| **Priority** | High |
| **Title** | Pre-Processing Input Validation |

**Description:**  
The system shall validate all required inputs before initiating any processing, and shall return informative error messages for any validation failure.

**Acceptance Criteria:**  
- AC-ERR-003-01: The RTF directory field shall be validated as a non-empty string pointing to an existing directory.
- AC-ERR-003-02: The output directory field shall be validated as a non-empty string.
- AC-ERR-003-03: Validation failures shall return HTTP 400 with a descriptive `{"error": "..."}` JSON body.
- AC-ERR-003-04: No processing shall commence when validation fails.

---

## 13. User Interface Specifications

### FS-UI-001 — Web Interface

| Field | Value |
|---|---|
| **ID** | FS-UI-001 |
| **Category** | User Interface |
| **Priority** | High |
| **Title** | Browser-Based Control Interface |

**Description:**  
The system shall provide a web browser interface accessible at `http://<host>:5000` that allows users to configure, execute, monitor, and download output from processing jobs without direct access to the server filesystem.

**Acceptance Criteria:**  
- AC-UI-001-01: The interface shall be accessible via a standard web browser without plugin installation.
- AC-UI-001-02: All configurable parameters defined in Section 6 shall be settable through the web interface.
- AC-UI-001-03: The interface shall not require page reloads during job execution or monitoring.

---

### FS-UI-002 — Asynchronous Processing and Progress Reporting

| Field | Value |
|---|---|
| **ID** | FS-UI-002 |
| **Category** | User Interface |
| **Priority** | High |
| **Title** | Non-Blocking Job Execution with Live Progress |

**Description:**  
Processing shall occur asynchronously so the web interface remains responsive during long-running jobs. The interface shall display real-time progress and log output.

**Acceptance Criteria:**  
- AC-UI-002-01: Submitting a job shall not block the browser; the interface shall remain interactive.
- AC-UI-002-02: The system shall report processing progress as a percentage (0–100%) updated at minimum every 1.5 seconds.
- AC-UI-002-03: Log lines produced during processing shall be displayed in the web interface incrementally without requiring a page refresh.
- AC-UI-002-04: The "Download PDF" button shall become active only when the job status is `complete`.

---

### FS-UI-003 — PDF Download via Browser

| Field | Value |
|---|---|
| **ID** | FS-UI-003 |
| **Category** | User Interface |
| **Priority** | High |
| **Title** | Browser-Initiated PDF Download |

**Description:**  
Upon job completion, the user shall be able to download the compiled PDF directly through the browser interface.

**Acceptance Criteria:**  
- AC-UI-003-01: A "Download PDF" button shall appear and become enabled when a job completes successfully.
- AC-UI-003-02: Clicking the button shall trigger a browser file download.
- AC-UI-003-03: The downloaded filename shall match the output filename on the server (`output_<timestamp>.pdf`).

---

## 14. Specification Traceability Matrix

This matrix cross-references each functional specification with its validation activities. OQ test case IDs shall be assigned during the OQ protocol development phase.

| FS ID | Title | OQ Test Case | Criticality |
|---|---|---|---|
| FS-INP-001 | RTF Input Directory Selection | OQ-INP-001 | Critical |
| FS-INP-002 | RTF File Enumeration and Ordering | OQ-INP-002 | Critical |
| FS-INP-003 | CSV Mapping File | OQ-INP-003 | High |
| FS-INP-004 | Configuration JSON Reload | OQ-INP-004 | Medium |
| FS-PAR-001 | Output Directory | OQ-PAR-001 | Critical |
| FS-PAR-002 | Header Text Fields | OQ-PAR-002 | High |
| FS-PAR-003 | Footer Text Fields | OQ-PAR-003 | High |
| FS-PAR-004 | Header Y-Coordinate | OQ-PAR-004 | Medium |
| FS-PAR-005 | Footer Y-Coordinate | OQ-PAR-005 | Medium |
| FS-PAR-006 | Master Page Number Coordinates | OQ-PAR-006 | Medium |
| FS-PRO-001 | LibreOffice RTF-to-PDF Conversion | OQ-PRO-001 | Critical |
| FS-PRO-002 | Title Extraction from RTF | OQ-PRO-002 | High |
| FS-PRO-003 | Sequential PDF Merging | OQ-PRO-003 | Critical |
| FS-PRO-004 | Dual-Layer Page Numbering | OQ-PRO-004 | Critical |
| FS-PRO-005 | Header and Footer Application | OQ-PRO-005 | High |
| FS-TOC-001 | ToC Generation | OQ-TOC-001 | Critical |
| FS-TOC-002 | Self-Aware ToC Page Count | OQ-TOC-002 | Critical |
| FS-TOC-003 | Hyperlinked ToC Entries | OQ-TOC-003 | High |
| FS-OUT-001 | ISO 8601 Timestamped Output Filenames | OQ-OUT-001 | Critical |
| FS-OUT-002 | Compiled PDF | OQ-OUT-002 | Critical |
| FS-OUT-003 | Configuration JSON Artefact | OQ-OUT-003 | High |
| FS-OUT-004 | PDF Bookmarks | OQ-OUT-004 | High |
| FS-OUT-005 | Intermediate PDF Retention | OQ-OUT-005 | Medium |
| FS-AUD-001 | Process Log Generation | OQ-AUD-001 | Critical |
| FS-AUD-002 | Audit Timestamp in JSON | OQ-AUD-002 | High |
| FS-CFG-001 | Automatic Settings Persistence | OQ-CFG-001 | High |
| FS-CFG-002 | Forward-Compatible Configuration Loading | OQ-CFG-002 | Medium |
| FS-ERR-001 | Per-File Error Isolation | OQ-ERR-001 | Critical |
| FS-ERR-002 | Fatal Error Reporting | OQ-ERR-002 | Critical |
| FS-ERR-003 | Input Validation | OQ-ERR-003 | High |
| FS-UI-001 | Web Interface | OQ-UI-001 | High |
| FS-UI-002 | Asynchronous Processing and Progress | OQ-UI-002 | High |
| FS-UI-003 | PDF Download via Browser | OQ-UI-003 | High |

---

## 15. Document Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| Author | *\<Name\>* | | |
| Reviewer | *\<Name\>* | | |
| Quality Assurance | *\<Name\>* | | |
| System Owner | *\<Name\>* | | |

---

*End of Document: FS-RTF2PDF-001 v1.0*
