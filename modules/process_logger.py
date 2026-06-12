"""
modules/process_logger.py
-------------------------
Maintains an in-memory log buffer during a job run and flushes it to a
`process.log` file in the output directory when the job finishes.

Log line format  (ISO 8601 local timestamp with timezone offset):
    [2026-05-26T14:21:00+10:00] report01.rtf     → OK    | Master pages: 3–8
    [2026-05-26T14:21:02+10:00] report02.rtf     → ERROR | FileNotFoundError: ...
    [2026-05-26T14:21:05+10:00] SUMMARY: 2 files | 12 pages | 0 errors

Each running job holds its own ProcessLogger instance so concurrent jobs
do not cross-contaminate logs.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import NamedTuple


class LogEntry(NamedTuple):
    timestamp: str
    filename: str
    status: str       # "OK" | "ERROR" | "SKIP" | "INFO"
    detail: str       # free-text detail, e.g. "Master pages: 3–8"
    raw: str          # fully formatted line for writing to disk


def _local_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class ProcessLogger:
    """Accumulates log entries and writes process.log to disk on flush."""

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._error_count: int = 0
        self._total_pages: int = 0
        self._log_path: Path | None = None

    # ------------------------------------------------------------------
    # Log file lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        output_dir: str | Path,
        filename_stem: str = "process",
    ) -> Path:
        """Create the log file immediately so entries are written as they arrive.

        Call once at the beginning of a job.  After this, every ``log_*``
        call appends a line to the file in real time instead of buffering
        until :meth:`flush`.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = output_dir / f"{filename_stem}.log"
        self._log_path.write_text("", encoding="utf-8")  # create / truncate
        return self._log_path

    # ------------------------------------------------------------------
    # Entry builders
    # ------------------------------------------------------------------

    def log_conversion_ok(
        self,
        filename: str,
        master_start: int,
        master_end: int,
    ) -> None:
        """Record a successful RTF→PDF conversion with its master page range."""
        detail = f"Master pages: {master_start}–{master_end}"
        self._total_pages += master_end - master_start + 1
        self._append(filename, "OK", detail)

    def log_conversion_error(self, filename: str, exc: Exception) -> None:
        """Record a failed conversion."""
        detail = f"{type(exc).__name__}: {exc}"
        self._error_count += 1
        self._append(filename, "ERROR", detail)

    def log_skip(self, filename: str, reason: str) -> None:
        """Record a skipped file (e.g. CSV entry that has no matching RTF)."""
        self._append(filename, "SKIP", reason)

    def log_info(self, message: str) -> None:
        """Record a general informational message (not file-specific)."""
        self._append("—", "INFO", message)

    def log_params(self, params: dict) -> None:
        """Write a formatted block of job parameters immediately after start()."""
        sep = "─" * 48
        hdr = params.get("header", {})
        ftr = params.get("footer", {})
        csv_name = (params.get("csv_original_filename") or "").strip()

        lines = [
            sep,
            f"RTF Directory         : {params.get('rtf_directory', '')}",
            f"Output Directory      : {params.get('output_directory', '')}",
            f"CSV Mapping           : {csv_name or '(none)'}",
            f"Parallel workers      : {params.get('max_workers', '')}",
            f"Header / Left         : {hdr.get('left', '') or '(empty)'}",
            f"Header / Center       : {hdr.get('center', '') or '(empty)'}",
            f"Header / Right        : {hdr.get('right', '') or '(empty)'}",
            f"Header top margin     : {params.get('header_top_margin_pts', '')} pts",
            f"Footer / Left         : {ftr.get('left', '') or '(empty)'}",
            f"Footer / Center       : {ftr.get('center', '') or '(empty)'}",
            f"Footer / Right        : {ftr.get('right', '') or '(empty)'}",
            f"Footer bottom margin  : {params.get('footer_bottom_margin_pts', '')} pts",
            f"Page no. right margin : {params.get('page_number_right_margin_pts', '')} pts",
            f"Page no. btm margin   : {params.get('page_number_bottom_margin_pts', '')} pts",
            f"Page no. font size    : {params.get('page_number_font_size', '')} pts",
            sep,
        ]
        for line in lines:
            self._append("—", "INFO", line)

    # ------------------------------------------------------------------
    # Flush to disk
    # ------------------------------------------------------------------

    def flush(
        self,
        output_dir: str | Path,
        total_files: int,
        filename_stem: str = "process",
    ) -> Path:
        """Append summary and PASS/FAIL result line to the log file.

        If :meth:`start` was never called (early fatal error before the log
        file was created), all buffered entries are written first.

        Parameters
        ----------
        output_dir:
            Directory for the log file (used only when :meth:`start` was
            not called; otherwise the path recorded by :meth:`start` is used).
        total_files:
            Total number of files attempted (for summary line).
        filename_stem:
            Stem for the output file name when :meth:`start` was not called.

        Returns
        -------
        Path
            Absolute path to the log file.
        """
        if self._log_path is None:
            # start() was never called — write everything from scratch now
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = output_dir / f"{filename_stem}.log"
            prior_lines: list[str] = [e.raw for e in self._entries]
        else:
            prior_lines = []  # already written incrementally by _append()

        detail = (
            f"{total_files} files | "
            f"{self._total_pages} pages | "
            f"{self._error_count} errors"
        )
        result_status = "FAIL" if self._error_count > 0 else "PASS"
        summary_raw = self._format(_local_now(), "SUMMARY", "INFO",          detail)
        result_raw  = self._format(_local_now(), "RESULT",  result_status,   detail)

        with self._log_path.open("a", encoding="utf-8") as fh:
            for line in prior_lines:
                fh.write(line + "\n")
            fh.write(summary_raw + "\n")
            fh.write(result_raw  + "\n")

        return self._log_path

    # ------------------------------------------------------------------
    # Live access (for streaming to UI)
    # ------------------------------------------------------------------

    @property
    def lines(self) -> list[str]:
        """Return all formatted log lines accumulated so far."""
        return [e.raw for e in self._entries]

    @property
    def error_count(self) -> int:
        return self._error_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, filename: str, status: str, detail: str) -> None:
        ts = _local_now()
        raw = self._format(ts, filename, status, detail)
        self._entries.append(LogEntry(ts, filename, status, detail, raw))
        if self._log_path is not None:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(raw + "\n")

    @staticmethod
    def _format(ts: str, filename: str, status: str, detail: str) -> str:
        padded_status = status.ljust(5)
        padded_name = filename.ljust(40)
        return f"[{ts}] {padded_name} → {padded_status} | {detail}"
