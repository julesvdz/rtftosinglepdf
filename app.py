"""
app.py
------
Flask entry point for the RTF-to-PDF Compiler.

Routing
-------
  GET  /                              Serve the main UI
  POST /api/run                       Accept form submission, spawn background job
  GET  /api/status/<job_id>           Poll job progress and live log
  POST /api/load-config               Parse an uploaded config JSON, return field values
  GET  /api/download/<job_id>         Stream the finished PDF to the browser
  POST /api/preview-layout                 Generate a 2-page layout-preview PDF
  GET  /api/sample-mapping-template        Download a blank .xlsx CSV mapping template
  POST /api/generate-mapping-template      Scan RTF dir, extract titles, return populated .xlsx

Background Processing
---------------------
Each job runs in a daemon Thread.  A module-level `JOBS` dict keyed on a
UUID string holds job state.  On completion the PDF path, process.log path,
and config.json path are stored there for download/inspection.
"""

from __future__ import annotations

import base64
import datetime
import os
import re
import shutil
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl

import fitz  # PyMuPDF
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)
from werkzeug.utils import secure_filename

from modules.bookmarks import build_toc_list, inject_bookmarks
from modules.config_manager import build_params_from_form, load_config, save_config
from modules.csv_handler import parse_csv, resolve_entries_against_directory
from modules.header_footer import apply_headers_and_footers
from modules.libreoffice import convert_rtf_to_pdf, find_soffice
from modules.page_numbering import apply_master_page_numbers
from modules.pdf_merger import merge_pdfs, prepend_pages, shift_section_info
from modules.process_logger import ProcessLogger
from modules.rtf_parser import extract_title
from modules.toc_generator import build_toc, inject_toc_links
import config as _cfg

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload cap

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------
# Structure per job_id:
# {
#     "status":   "running" | "complete" | "error",
#     "progress": 0..100,
#     "log":      [str, ...],
#     "pdf_path": str | None,
#     "error":    str | None,
# }
JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _update_job(job_id: str, **kwargs: Any) -> None:
    with _JOBS_LOCK:
        JOBS[job_id].update(kwargs)


def _append_log(job_id: str, line: str) -> None:
    with _JOBS_LOCK:
        JOBS[job_id]["log"].append(line)


# ---------------------------------------------------------------------------
# Background processing pipeline
# ---------------------------------------------------------------------------

def _run_job(job_id: str, params: dict, csv_file_path: str | None) -> None:
    """Full RTF → PDF pipeline executed in a background thread."""
    plogger = ProcessLogger()

    try:
        rtf_dir = Path(params["rtf_directory"])
        output_dir = Path(params["output_directory"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # Filesystem-safe ISO 8601 timestamp (basic format, no colons)
        # used as the stem for all three output files.
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        pdf_stem    = f"output_{ts}"           # compiled_output → output_<ts>.pdf
        config_stem = f"output_{ts}_config"   # config.json    → output_<ts>_config.json
        log_stem    = f"output_{ts}"           # process.log    → output_<ts>.log

        # Subfolder inside output_dir that receives the individual converted PDFs.
        indiv_dir = output_dir / pdf_stem
        indiv_dir.mkdir(parents=True, exist_ok=True)

        # Save config and open the process log immediately so both files
        # survive even if the run fails partway through.
        # Include output filenames so the config is a complete run record.
        params_snapshot = {
            **params,
            "output_pdf_filename": f"{pdf_stem}.pdf",
            "log_filename":        f"{log_stem}.log",
            "config_filename":     f"{config_stem}.json",
        }
        cfg_path = save_config(params_snapshot, output_dir, filename_stem=config_stem)
        _append_log(job_id, f"[INFO] Config saved → {cfg_path.name}")
        log_path = plogger.start(output_dir, log_stem)
        _append_log(job_id, f"[INFO] Process log → {log_path.name}")
        plogger.log_params(params_snapshot)

        # ── Copy CSV into output folder (audit trail) ────────────────────
        if csv_file_path:
            csv_orig_name = Path(params.get("csv_original_filename") or "mapping.csv").name
            csv_dest = output_dir / csv_orig_name
            shutil.copy2(csv_file_path, csv_dest)
            msg = f"CSV mapping copied: {csv_file_path} → {csv_dest}"
            plogger.log_info(msg)
            _append_log(job_id, f"[INFO] CSV mapping copied → {csv_dest}")

        # ── Detect LibreOffice once ──────────────────────────────────────
        _append_log(job_id, "[INFO] Detecting LibreOffice…")
        try:
            soffice = find_soffice()
            _append_log(job_id, f"[INFO] Found soffice: {soffice}")
            plogger.log_info(f"soffice: {soffice}")
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc

        # ── Resolve file list ────────────────────────────────────────────
        if csv_file_path:
            _append_log(job_id, "[INFO] Parsing CSV mapping…")
            from modules.csv_handler import SectionEntry
            csv_entries = parse_csv(csv_file_path)
            resolved = resolve_entries_against_directory(csv_entries, rtf_dir)
            file_list: list[tuple[Path, str, str]] = [
                (path, entry.title, entry.table_number)
                for entry, path in resolved
            ]
            # Warn about CSV entries with no matching file
            resolved_names = {entry.rtf_filename for entry, _ in resolved}
            for entry in csv_entries:
                if entry.rtf_filename not in resolved_names:
                    plogger.log_skip(
                        entry.rtf_filename,
                        "File not found in RTF directory",
                    )
                    _append_log(
                        job_id,
                        f"[SKIP] {entry.rtf_filename} — not found in RTF directory",
                    )
        else:
            _append_log(job_id, "[INFO] No CSV — using alphanumeric file order…")
            rtf_files = sorted(rtf_dir.glob("*.rtf"), key=lambda p: p.name.lower())
            rtf_files += sorted(rtf_dir.glob("*.RTF"), key=lambda p: p.name.lower())
            # De-duplicate (case-insensitive systems); skip temp/hidden files
            # whose names start with ~ (Office lock files) or . (hidden files).
            seen: set[str] = set()
            unique_rtf: list[Path] = []
            for p in rtf_files:
                key = p.name.lower()
                if key not in seen and not p.name.startswith(("~", ".")):
                    seen.add(key)
                    unique_rtf.append(p)

            title_workers = max(1, min(8, len(unique_rtf)))
            titles: list[str] = [""] * len(unique_rtf)
            with ThreadPoolExecutor(max_workers=title_workers) as tex:
                future_to_i = {
                    tex.submit(extract_title, p): i
                    for i, p in enumerate(unique_rtf)
                }
                for f in as_completed(future_to_i):
                    titles[future_to_i[f]] = f.result()
            file_list = [(p, titles[i], "") for i, p in enumerate(unique_rtf)]

        if not file_list:
            raise ValueError(
                "No RTF files found in the specified directory "
                "(or none matched the CSV mapping)."
            )

        total_files = len(file_list)
        _append_log(job_id, f"[INFO] {total_files} RTF file(s) queued for conversion.")
        _update_job(job_id, progress=5)

        # ── LibreOffice RTF → PDF conversion (parallel) ───────────────────
        n_workers = max(1, min(int(params.get("max_workers", _cfg.MAX_PARALLEL_CONVERSIONS)), total_files))
        _append_log(job_id, f"[INFO] Starting parallel conversion ({n_workers} worker(s))…")

        # Each soffice instance needs its own user-profile directory; without
        # isolation, concurrent instances corrupt each other's lock files.
        profile_base = output_dir / "lo_profiles"
        shutil.rmtree(profile_base, ignore_errors=True)
        profile_base.mkdir()
        profile_dirs = [profile_base / f"slot_{i}" for i in range(n_workers)]
        for pd in profile_dirs:
            pd.mkdir()

        # Thread-local slot assignment: each worker thread gets a stable slot
        # index and reuses the same profile directory for all its files.
        _slot_local: threading.local = threading.local()
        _slot_counter: dict[str, int] = {"next": 0}
        _slot_counter_lock = threading.Lock()

        def _assign_slot() -> int:
            if not hasattr(_slot_local, "slot"):
                with _slot_counter_lock:
                    _slot_local.slot = _slot_counter["next"] % n_workers
                    _slot_counter["next"] += 1
            return _slot_local.slot  # type: ignore[return-value]

        def _convert_one(
            idx: int, rtf_path: Path, title: str, table_num: str
        ) -> tuple[int, str | None, Exception | None]:
            slot = _assign_slot()
            try:
                pdf_path = convert_rtf_to_pdf(
                    rtf_path, indiv_dir,
                    soffice_path=soffice,
                    user_profile_dir=profile_dirs[slot],
                )
                return (idx, str(pdf_path), None)
            except Exception as exc:
                return (idx, None, exc)

        # Pre-allocated results list preserves original file_list order
        # regardless of completion order from the thread pool.
        results_by_index: list[tuple[str, str, str, str] | None] = [None] * total_files
        ok_count = 0

        try:
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                future_to_idx = {
                    executor.submit(_convert_one, idx, rtf_path, title, table_num): idx
                    for idx, (rtf_path, title, table_num) in enumerate(file_list)
                }
                completed_count = 0
                for future in as_completed(future_to_idx):
                    orig_idx, pdf_path_str, exc = future.result()
                    rtf_path, title, table_num = file_list[orig_idx]
                    completed_count += 1
                    pct = 5 + int(60 * completed_count / total_files)
                    _update_job(job_id, progress=pct)
                    file_tag = f"[file {completed_count} of {total_files}]"
                    if exc is not None:
                        plogger.log_conversion_error(rtf_path.name, exc)
                        _append_log(job_id, f"[ERR]  {file_tag} {rtf_path.name}: {exc}")
                    else:
                        _append_log(
                            job_id,
                            f"[OK]   {file_tag} {rtf_path.name} → {Path(pdf_path_str).name}",
                        )
                        results_by_index[orig_idx] = (pdf_path_str, title, table_num, rtf_path.name)
                        plogger.log_info(f"Converted: {rtf_path.name}")
                        ok_count += 1
        finally:
            shutil.rmtree(profile_base, ignore_errors=True)

        # Rebuild in original order, skipping any failed files.
        converted: list[tuple[str, str, str, str]] = [
            r for r in results_by_index if r is not None
        ]

        if not converted:
            raise RuntimeError("All RTF conversions failed — no PDFs to compile.")

        _update_job(job_id, progress=65)

        # ── Merge PDFs ────────────────────────────────────────────────────
        _append_log(job_id, "[INFO] Merging converted PDFs…")
        merged_doc, sections = merge_pdfs(converted)

        # ── Generate ToC (two-pass) ───────────────────────────────────────
        n_toc_entries = len(sections)
        _append_log(job_id, f"[INFO] Generating Table of Contents ({n_toc_entries} entries)…")
        plogger.log_info(f"ToC: building ({n_toc_entries} entries)")
        # Read paper size from the first source RTF (more reliable than relying
        # on LibreOffice to reproduce the exact dimensions in its PDF output).
        # Fall back to the first merged page if RTF reading fails.
        _rtf_size = _rtf_paper_size(file_list[0][0]) if file_list else None
        if _rtf_size:
            page_rect = fitz.Rect(0, 0, _rtf_size[0], _rtf_size[1])
        else:
            _raw_rect = merged_doc[0].rect if merged_doc.page_count > 0 else fitz.Rect(0, 0, 595, 842)
            _w, _h = _raw_rect.width, _raw_rect.height
            if _w > _h:
                _w, _h = _h, _w
            page_rect = fitz.Rect(0, 0, _w, _h)

        def _toc_progress(msg: str) -> None:
            _append_log(job_id, msg)
            plogger.log_info(msg)

        # Two-pass build: estimates ToC page count then renders final text.
        # Links cannot be embedded in the standalone toc_doc (it doesn't
        # contain the content pages), so inject_toc_links() is called below
        # on combined_doc after assembly.
        toc_doc, toc_page_count = build_toc(sections, page_rect, progress_cb=_toc_progress)
        _append_log(job_id, f"[INFO] ToC complete: {toc_page_count} page(s)")
        plogger.log_info(f"ToC: {toc_page_count} page(s) generated")

        # Prepend ToC pages into a fresh combined document
        combined_doc, prepended = prepend_pages(merged_doc, toc_doc)
        toc_doc.close()
        merged_doc.close()

        # Shift section page indices to account for the prepended ToC pages
        sections = shift_section_info(sections, prepended)

        # Inject clickable GOTO links into the ToC pages of combined_doc.
        # sections now carry absolute page indices within combined_doc, so
        # links are valid and point correctly to the first page of each section.
        _append_log(job_id, f"[INFO] Injecting {n_toc_entries} ToC hyperlink(s)…")
        plogger.log_info(f"ToC: injecting {n_toc_entries} hyperlinks")
        inject_toc_links(combined_doc, sections, prepended, page_rect)

        _update_job(job_id, progress=75)

        # ── Header / Footer overlay ───────────────────────────────────────
        hdr = params.get("header", {})
        ftr = params.get("footer", {})
        has_hf = any(hdr.values()) or any(ftr.values())

        if has_hf:
            _append_log(job_id, "[INFO] Applying headers and footers…")
            apply_headers_and_footers(combined_doc, hdr, ftr, overlay_config=params)

        _update_job(job_id, progress=82)

        # ── Master page numbering overlay ─────────────────────────────────
        _append_log(job_id, "[INFO] Applying master page numbers…")
        apply_master_page_numbers(
            combined_doc,
            toc_page_count=prepended,
            overlay_config=params,
        )

        _update_job(job_id, progress=88)

        # ── PDF Bookmarks ─────────────────────────────────────────────────
        _append_log(job_id, "[INFO] Injecting PDF bookmarks…")
        bookmark_entries = [
            {
                "title": s.title,
                "table_number": s.table_number,
                "page_index": s.start_page,
                "level": 1,
            }
            for s in sections
        ]
        bm_toc = build_toc_list(bookmark_entries)
        inject_bookmarks(combined_doc, bm_toc)

        _update_job(job_id, progress=92)

        # ── Save final PDF ────────────────────────────────────────────────
        output_pdf = output_dir / f"{pdf_stem}.pdf"
        _append_log(job_id, f"[INFO] Writing PDF → {output_pdf.name}")
        combined_doc.save(str(output_pdf), garbage=4, deflate=True, clean=True)
        combined_doc.close()

        # ── Log page ranges now that we know final positions ──────────────
        for s in sections:
            plogger.log_conversion_ok(s.rtf_filename, s.master_start, s.master_end)
            _append_log(
                job_id,
                f"[PAGE] {s.rtf_filename} → master pages {s.master_start}–{s.master_end}",
            )

        # ── Finalize process log (append summary + PASS/FAIL) ────────────────
        plogger.flush(output_dir, total_files, filename_stem=log_stem)
        _append_log(job_id, f"[INFO] Log finalized → {log_path.name}")

        _update_job(
            job_id,
            status="complete",
            progress=100,
            pdf_path=str(output_pdf),
        )
        _append_log(job_id, f"[DONE] Compiled {ok_count}/{total_files} RTF files.")

    except Exception as exc:
        tb = traceback.format_exc()
        _update_job(job_id, status="error", error=str(exc))
        _append_log(job_id, f"[FATAL] {exc}")
        _append_log(job_id, tb)
        plogger.log_info(f"FATAL: {exc}")
        try:
            output_dir = Path(params.get("output_directory", "."))
            err_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            plogger.flush(output_dir, 0, filename_stem=f"output_{err_ts}")
        except Exception:
            pass  # best effort


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def api_run() -> Response:
    """Start a new compilation job.

    Accepts multipart/form-data.
    Returns: {"job_id": "<uuid>"}
    """
    try:
        params = build_params_from_form(request.form)
    except Exception as exc:
        return jsonify({"error": f"Invalid form data: {exc}"}), 400

    # Validate required fields
    if not params.get("rtf_directory"):
        return jsonify({"error": "RTF directory is required."}), 400
    if not params.get("output_directory"):
        return jsonify({"error": "Output directory is required."}), 400
    if not Path(params["rtf_directory"]).is_dir():
        return jsonify({"error": f"RTF directory not found: {params['rtf_directory']}"}), 400

    # Handle optional CSV upload
    csv_file_path: str | None = None
    csv_file = request.files.get("csv_file")
    if csv_file and csv_file.filename:
        safe_name = secure_filename(csv_file.filename)
        upload_tmp = tempfile.mktemp(suffix="_" + safe_name)
        csv_file.save(upload_tmp)
        csv_file_path = upload_tmp
        params["csv_original_filename"] = csv_file.filename
        params["csv_path"] = csv_file.filename
    else:
        params["csv_original_filename"] = ""

    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "progress": 0,
            "log": [],
            "pdf_path": None,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, params, csv_file_path),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str) -> Response:
    """Poll job status.

    Returns:
    {
        "status":   "running" | "complete" | "error",
        "progress": 0..100,
        "log":      ["line1", "line2", ...],
        "error":    null | "message"
    }
    """
    with _JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404

    return jsonify({
        "status":   job["status"],
        "progress": job["progress"],
        "log":      job["log"],
        "error":    job.get("error"),
    })


@app.route("/api/load-config", methods=["POST"])
def api_load_config() -> Response:
    """Parse an uploaded config.json and return field values.

    Input: multipart/form-data with file key "config_file"
    Returns: the config dict for UI pre-population.
    """
    cfg_file = request.files.get("config_file")
    if not cfg_file or not cfg_file.filename:
        return jsonify({"error": "No config file uploaded."}), 400

    tmp_path = tempfile.mktemp(suffix=".json")
    try:
        cfg_file.save(tmp_path)
        data = load_config(tmp_path)
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify(data)


@app.route("/api/download/<job_id>")
def api_download(job_id: str) -> Response:
    """Stream the compiled PDF to the browser."""
    with _JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job["status"] != "complete":
        return jsonify({"error": "Job is not yet complete."}), 400
    pdf_path = job.get("pdf_path")
    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({"error": "Output PDF not found."}), 404

    download_name = Path(pdf_path).name  # preserves the output_<ts>.pdf filename
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/api/generate-mapping-template", methods=["POST"])
def api_generate_mapping_template() -> Response:
    """Scan the given RTF directory, extract titles, and return a pre-populated .xlsx."""
    rtf_directory = request.form.get("rtf_directory", "").strip()
    if not rtf_directory:
        return jsonify({"error": "rtf_directory is required."}), 400

    rtf_dir = Path(rtf_directory)
    if not rtf_dir.is_dir():
        return jsonify({"error": f"Directory not found: {rtf_directory}"}), 400

    # Discover RTF files — same de-dup + temp-file filter as _run_job
    rtf_files = sorted(rtf_dir.glob("*.rtf"), key=lambda p: p.name.lower())
    rtf_files += sorted(rtf_dir.glob("*.RTF"), key=lambda p: p.name.lower())
    seen: set[str] = set()
    unique_rtf: list[Path] = []
    for p in rtf_files:
        key = p.name.lower()
        if key not in seen and not p.name.startswith(("~", ".")):
            seen.add(key)
            unique_rtf.append(p)

    log: list[str] = []
    rows: list[tuple[str, str, str]] = []
    fail_count = 0

    if not unique_rtf:
        log.append(f"[WARN] No RTF files found in: {rtf_directory}")
    else:
        for rtf_path in unique_rtf:
            try:
                title = extract_title(rtf_path)
                rows.append((rtf_path.name, "", title))
                log.append(f"[OK]   {rtf_path.name} → {title}")
            except Exception as exc:
                rows.append((rtf_path.name, "", ""))
                log.append(f"[FAIL] {rtf_path.name} → {exc}")
                fail_count += 1

    ok_count = len(rows) - fail_count
    log.append(f"[INFO] Template ready: {ok_count} title(s) extracted, {fail_count} failure(s).")

    # openpyxl raises IllegalCharacterError for XML-illegal control characters
    # (U+0000–U+0008, U+000B–U+000C, U+000E–U+001F) that may survive RTF
    # decoding.  Strip them before writing.
    _illegal = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def _xlsx_safe(s: str) -> str:
        return _illegal.sub("", s)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mapping"
    ws.append(["RTF_Filename", "Table_Number", "Title"])
    for row in rows:
        ws.append([_xlsx_safe(cell) for cell in row])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 60

    buf = BytesIO()
    wb.save(buf)
    xlsx_b64 = base64.b64encode(buf.getvalue()).decode()

    return jsonify({"log": log, "xlsx_base64": xlsx_b64})


# ---------------------------------------------------------------------------
# Layout preview helpers
# ---------------------------------------------------------------------------

def _rtf_paper_size(rtf_path: Path) -> tuple[float, float] | None:
    """Read \\paperw/\\paperh from a single RTF file.

    RTF header sections (font tables, colour tables, style sheets) can easily
    exceed 4 KB in complex documents, so we read up to 32 KB to be safe.

    Returns (portrait_width_pts, portrait_height_pts) or None on any failure.
    """
    try:
        raw = rtf_path.read_bytes()[:32768].decode("cp1252", errors="replace")
        pw = re.search(r"\\paperw(\d+)", raw)
        ph = re.search(r"\\paperh(\d+)", raw)
        if pw and ph:
            w = int(pw.group(1)) / 20.0   # twips → points
            h = int(ph.group(1)) / 20.0
            return (min(w, h), max(w, h))  # normalise to portrait
    except Exception:
        pass
    return None


def _preview_page_size(rtf_directory: str) -> tuple[float, float]:
    """Return (portrait_width_pts, portrait_height_pts) for the preview.

    Reads the first RTF in the directory.  Falls back to A4.
    """
    a4 = (595.0, 842.0)
    if not rtf_directory:
        return a4
    rtf_dir = Path(rtf_directory)
    if not rtf_dir.is_dir():
        return a4
    candidates = sorted(rtf_dir.glob("*.rtf"), key=lambda p: p.name.lower())
    if not candidates:
        candidates = sorted(rtf_dir.glob("*.RTF"), key=lambda p: p.name.lower())
    if not candidates:
        return a4
    result = _rtf_paper_size(candidates[0])
    return result if result is not None else a4


def _paper_name(w_pts: float, h_pts: float) -> str | None:
    """Return a standard paper name for portrait dimensions, or None if unknown."""
    tol = 3.0
    for sw, sh, name in [
        (595, 842, "A4"), (612, 792, "Letter"), (612, 1008, "Legal"),
        (420, 595, "A5"), (842, 1191, "A3"), (499, 709, "B5"), (729, 1032, "B4"),
    ]:
        if abs(w_pts - sw) <= tol and abs(h_pts - sh) <= tol:
            return name
    return None


def _draw_preview_center(page: fitz.Page, paper_name: str | None, orientation: str) -> None:
    """Draw centred page-info text on a preview page."""
    pw, ph = page.rect.width, page.rect.height
    cy = ph / 2.0
    gray = (0.65, 0.65, 0.65)

    w_mm = round(pw * 25.4 / 72)
    h_mm = round(ph * 25.4 / 72)
    parts = ([paper_name] if paper_name else []) + [f"{w_mm} × {h_mm} mm", orientation]
    dim_line = "  ·  ".join(parts)

    # Use insert_textbox with centre alignment — guaranteed accurate regardless
    # of font metrics, unlike manual cx - width/2 approximations.
    page.insert_textbox(
        fitz.Rect(0, cy - 30, pw, cy - 10),
        "LAYOUT PREVIEW",
        fontname="hebo",
        fontsize=16,
        color=gray,
        align=fitz.TEXT_ALIGN_CENTER,
    )
    page.insert_textbox(
        fitz.Rect(0, cy + 2, pw, cy + 20),
        dim_line,
        fontname="helv",
        fontsize=10,
        color=gray,
        align=fitz.TEXT_ALIGN_CENTER,
    )


@app.route("/api/preview-layout", methods=["POST"])
def api_preview_layout() -> Response:
    """Generate a 2-page layout-preview PDF (portrait + landscape)."""
    overlay_config = {
        "header_top_margin_pts":         float(request.form.get("header_top_margin_pts", 28)),
        "footer_bottom_margin_pts":      float(request.form.get("footer_bottom_margin_pts", 35)),
        "page_number_right_margin_pts":  float(request.form.get("page_number_right_margin_pts", 55)),
        "page_number_bottom_margin_pts": float(request.form.get("page_number_bottom_margin_pts", 18)),
        "page_number_font_size":         int(request.form.get("page_number_font_size", 8)),
    }
    header = {k: request.form.get(f"header_{k}", "") for k in ("left", "center", "right")}
    footer = {k: request.form.get(f"footer_{k}", "") for k in ("left", "center", "right")}

    port_w, port_h = _preview_page_size(request.form.get("rtf_directory", "").strip())
    name = _paper_name(port_w, port_h)

    doc = fitz.open()
    for orientation, (pw, ph) in [("Portrait", (port_w, port_h)),
                                   ("Landscape", (port_h, port_w))]:
        page = doc.new_page(width=pw, height=ph)
        _draw_preview_center(page, name, orientation)

    apply_headers_and_footers(doc, header, footer, overlay_config=overlay_config)
    apply_master_page_numbers(doc, toc_page_count=0, overlay_config=overlay_config)

    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False, download_name="layout_preview.pdf")


@app.route("/api/sample-mapping-template")
def api_sample_mapping_template() -> Response:
    """Return a pre-formatted .xlsx file the user can fill in and save as CSV."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mapping"
    ws.append(["RTF_Filename", "Table_Number", "Title"])
    ws.append(["example_file.rtf", "Table 14.1.1", "Summary of Adverse Events"])

    # Widen columns so the content is readable on first open
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 50

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="csv_mapping_template.xlsx",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
