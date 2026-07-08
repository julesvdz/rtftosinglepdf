"""
uno_helper/convert_worker.py
----------------------------
RTF → PDF conversion worker with real progress reporting.

Runs under LibreOffice's *bundled* Python (the only interpreter that can
``import uno`` on this machine) — keep this file stdlib + uno only, with no
project imports.

The parent app spawns one worker per conversion slot, alongside a headless
soffice service listening on a localhost UNO socket. The worker connects to
that service, then loops: read one JSON task per line from stdin, convert,
and stream JSON progress events to stdout.

Protocol (one JSON object per line, UTF-8, ensure_ascii, flushed per line):
  stdin  : {"id": N, "action": "convert", "rtf": "<path>", "pdf": "<path>"}
           {"action": "shutdown"}
  stdout : {"event": "ready"}
           {"id": N, "event": "start", "file": "<name>"}
           {"id": N, "event": "progress", "phase": "load"|"export", "pct": 0-100}
           {"id": N, "event": "done", "elapsed": 12.3}
           {"id": N, "event": "error", "message": "..."}
           {"event": "fatal", "message": "..."}   (then exits non-zero)

Per-file percentage: document load maps to 0-<load_span>%, PDF export to the
remainder. Each phase's end() snaps to its ceiling so the bar always reaches
the phase boundary even when LibreOffice emits few or no setValue calls.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import uno
import unohelper
from com.sun.star.connection import NoConnectException
from com.sun.star.lang import DisposedException
from com.sun.star.task import XInteractionHandler, XStatusIndicator

# Plain ints to avoid importing the constant groups:
_MACRO_NEVER_EXECUTE = 0   # com.sun.star.document.MacroExecMode.NEVER_EXECUTE
_UPDATE_NO_UPDATE = 1      # com.sun.star.document.UpdateDocMode.NO_UPDATE


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=True), flush=True)


class SilentHandler(unohelper.Base, XInteractionHandler):
    """Selects no continuation for any interaction request.

    Corrupt, password-protected, or filter-ambiguous documents then fail
    fast with an exception instead of hanging a hidden dialog until the
    parent's per-file timeout kills the whole slot.
    """

    def handle(self, request):  # noqa: N802 (UNO interface casing)
        pass


class ProgressIndicator(unohelper.Base, XStatusIndicator):
    """Maps one phase's local progress range onto a global pct window.

    Emits are monotonic and throttled: LibreOffice import filters interleave
    setValue(0) resets and repeated start() calls with real values, so any
    pct not above the last emitted one is dropped, and emits are at least
    100 ms apart so a chatty filter cannot flood stdout.
    """

    def __init__(self, task_id: int, phase: str, base_pct: float, span_pct: float):
        self._task_id = task_id
        self._phase = phase
        self._base = base_pct
        self._span = span_pct
        self._range = 1
        self._last_pct = -1
        self._last_emit = 0.0

    def _emit_pct(self, pct: float, force: bool = False) -> None:
        ipct = int(pct)
        now = time.monotonic()
        if not force and (ipct <= self._last_pct or now - self._last_emit < 0.1):
            return
        self._last_pct = ipct
        self._last_emit = now
        emit({"id": self._task_id, "event": "progress",
              "phase": self._phase, "pct": ipct})

    # -- XStatusIndicator ---------------------------------------------------
    def start(self, text, maxrange):  # noqa: N802
        self._range = max(int(maxrange), 1)
        self._emit_pct(self._base)

    def setValue(self, value):  # noqa: N802
        frac = min(int(value), self._range) / self._range
        self._emit_pct(self._base + self._span * frac)

    def setText(self, text):  # noqa: N802
        pass

    def end(self):  # noqa: N802
        self._emit_pct(self._base + self._span, force=True)

    def reset(self):  # noqa: N802
        pass


def _props(**kwargs):
    """Build a tuple of com.sun.star.beans.PropertyValue from kwargs."""
    out = []
    for name, value in kwargs.items():
        pv = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        pv.Name = name
        pv.Value = value
        out.append(pv)
    return tuple(out)


def connect(port: int, timeout: float):
    """Connect to the soffice UNO socket, retrying until *timeout*."""
    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx
    )
    url = (
        f"uno:socket,host=127.0.0.1,port={port};urp;"
        "StarOffice.ComponentContext"
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            ctx = resolver.resolve(url)
            break
        except NoConnectException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx
    )
    return ctx, desktop


def convert_one(desktop, task: dict, load_span: int) -> None:
    src_url = uno.systemPathToFileUrl(task["rtf"])
    dst_url = uno.systemPathToFileUrl(task["pdf"])
    task_id = task["id"]

    load_props = _props(
        Hidden=True,
        ReadOnly=True,
        UpdateDocMode=_UPDATE_NO_UPDATE,
        MacroExecutionMode=_MACRO_NEVER_EXECUTE,
        InteractionHandler=SilentHandler(),
        StatusIndicator=ProgressIndicator(task_id, "load", 0, load_span),
    )
    doc = desktop.loadComponentFromURL(src_url, "_blank", 0, load_props)
    if doc is None:
        raise RuntimeError("loadComponentFromURL returned None (unreadable file?)")
    try:
        store_props = _props(
            FilterName="writer_pdf_Export",
            Overwrite=True,
            StatusIndicator=ProgressIndicator(
                task_id, "export", load_span, 100 - load_span
            ),
        )
        doc.storeToURL(dst_url, store_props)
    finally:
        try:
            doc.close(False)
        except Exception:
            try:
                doc.dispose()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--connect-timeout", type=float, default=90.0)
    parser.add_argument("--load-span", type=int, default=70)
    args = parser.parse_args()

    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", line_buffering=True
    )

    try:
        _ctx, desktop = connect(args.port, args.connect_timeout)
    except Exception as exc:
        emit({"event": "fatal",
              "message": f"UNO connect failed: {type(exc).__name__}: {exc}"})
        return 2

    emit({"event": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            task = json.loads(line)
        except ValueError:
            continue
        if task.get("action") == "shutdown":
            break
        if task.get("action") != "convert":
            continue

        emit({"id": task["id"], "event": "start",
              "file": Path(task["rtf"]).name})
        t0 = time.monotonic()
        try:
            convert_one(desktop, task, args.load_span)
            emit({"id": task["id"], "event": "done",
                  "elapsed": round(time.monotonic() - t0, 1)})
        except Exception as exc:
            if isinstance(exc, DisposedException):
                # The soffice service died under us — emit ONLY fatal (no
                # per-task error) so the parent fails just this file via
                # UnoSlotDied and restarts the slot before the next one.
                emit({"event": "fatal", "message": "soffice bridge disposed"})
                return 3
            emit({"id": task["id"], "event": "error",
                  "message": f"{type(exc).__name__}: {exc}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
