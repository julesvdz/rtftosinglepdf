"""
modules/uno_converter.py
------------------------
Persistent per-slot LibreOffice services driven via the UNO API, giving real
per-file conversion progress.

The app's Python cannot ``import uno``; only LibreOffice's bundled Python
can. Each :class:`UnoSlot` therefore manages two child processes:

  1. A headless ``soffice`` service listening on a localhost UNO socket,
     with an isolated user profile (concurrent instances corrupt each
     other's lock files otherwise — same constraint as the CLI path).
  2. ``uno_helper/convert_worker.py`` running under LO's bundled python,
     which connects to that socket and converts one file per JSON task,
     streaming progress events back over stdout.

A slot is used by exactly one worker thread at a time; the only cross-thread
traffic is the stdout-reader daemon feeding the event queue.

Falls back are the caller's job: :func:`find_lo_python` returning ``None``
or :class:`UnoBootstrapError` mean "use the CLI converter instead".
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import config

_HELPER_PATH = Path(__file__).resolve().parent.parent / "uno_helper" / "convert_worker.py"

# Timed-out tasks are abandoned, never reused: ids must stay unique across
# restarts so a late event from a killed helper can't match a new task.
_task_counter = 0
_task_counter_lock = threading.Lock()

# Every live slot registers here so atexit can reap soffice processes when
# the interpreter exits mid-job (Ctrl+C, werkzeug reloader). A hard kill of
# the app still orphans them — swept at the next job start by the caller.
_LIVE_SLOTS: set["UnoSlot"] = set()
_LIVE_SLOTS_LOCK = threading.Lock()


def _next_task_id() -> int:
    global _task_counter
    with _task_counter_lock:
        _task_counter += 1
        return _task_counter


class UnoBootstrapError(RuntimeError):
    """The slot's soffice/helper pair never became ready."""


class UnoSlotDied(RuntimeError):
    """The soffice service or helper died mid-conversion."""


class UnoTimeout(RuntimeError):
    """A conversion exceeded its (activity-based) deadline."""


def find_lo_python(soffice_path: str) -> str | None:
    """Return LibreOffice's bundled python.exe next to soffice, if present."""
    candidate = Path(soffice_path).parent / "python.exe"
    return str(candidate) if candidate.is_file() else None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def force_rmtree(path: str | Path) -> None:
    """Best-effort rmtree that handles read-only files and long paths.

    LibreOffice marks its extension-registry files read-only (which makes
    plain ``rmtree(ignore_errors=True)`` silently leave litter), and its
    profile trees can exceed Windows' 260-char MAX_PATH — deleting those
    entries fails with WinError 3 unless the ``\\\\?\\`` long-path prefix
    is used. Clear the attribute and retry each failing entry.
    """
    def _onexc(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    path = Path(path)
    if os.name == "nt":
        raw = str(path.resolve())
        if not raw.startswith("\\\\?\\"):
            path = Path("\\\\?\\" + raw)
    try:
        shutil.rmtree(path, onexc=_onexc)
    except Exception:
        pass


def kill_stale_soffice(profile_marker: str) -> int:
    """Kill orphaned soffice processes from a previous crashed/killed run.

    A hard kill of the app orphans the per-slot soffice services. They keep
    their profile directories open, so the stale-dir sweep at job start
    would silently fail and the processes would leak memory until reboot.
    Only processes whose command line contains *profile_marker* (the
    output dir's ``lo_profiles_`` profile URI prefix) are touched — a
    user's interactive LibreOffice session never matches.

    Returns the number of processes killed.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'soffice%'\" | "
             "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return 0
    killed = 0
    for line in out.splitlines():
        pid, _, cmdline = line.partition("|")
        if profile_marker in cmdline:
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid.strip(), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                killed += 1
            except Exception:
                pass
    return killed


def kill_all_slots() -> None:
    """Reap every live slot's processes (atexit / job-end safety net)."""
    with _LIVE_SLOTS_LOCK:
        slots = list(_LIVE_SLOTS)
    for slot in slots:
        slot.kill()


class UnoSlot:
    """One persistent soffice service + helper worker pair."""

    def __init__(
        self,
        slot_idx: int,
        soffice_path: str,
        lo_python: str,
        profile_dir: str | Path,
        log_cb: Callable[[str], None] | None = None,
    ):
        self.slot_idx = slot_idx
        self._soffice_path = soffice_path
        self._lo_python = lo_python
        self._profile_dir = Path(profile_dir)
        self._log = log_cb or (lambda msg: None)

        self._soffice: subprocess.Popen | None = None
        self._helper: subprocess.Popen | None = None
        self._events: queue.Queue[dict] = queue.Queue()
        self._conversions_done = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Spawn soffice + helper and wait for the helper's ready event.

        Retries with a fresh port up to ``config.UNO_START_RETRIES`` times;
        raises :class:`UnoBootstrapError` when all attempts fail.
        """
        last_err = "unknown"
        for attempt in range(1, config.UNO_START_RETRIES + 1):
            port = _free_port()
            t0 = time.monotonic()
            try:
                self._spawn(port)
                self._wait_ready()
                with _LIVE_SLOTS_LOCK:
                    _LIVE_SLOTS.add(self)
                self._log(
                    f"[INFO] UNO slot {self.slot_idx} ready "
                    f"({time.monotonic() - t0:.1f}s, port {port})"
                )
                return
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                self._log(
                    f"[WARN] UNO slot {self.slot_idx} start attempt "
                    f"{attempt}/{config.UNO_START_RETRIES} failed: {last_err}"
                )
                self.kill()
        raise UnoBootstrapError(last_err)

    def _spawn(self, port: int) -> None:
        self._events = queue.Queue()  # fresh queue: drop stale events

        soffice_cmd = [
            self._soffice_path,
            "--headless", "--invisible", "--nologo", "--norestore",
            "--nodefault", "--nofirststartwizard",
            f"--accept=socket,host=127.0.0.1,port={port};urp;",
            f"-env:UserInstallation={self._profile_dir.resolve().as_uri()}",
        ]
        self._soffice = subprocess.Popen(
            soffice_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        helper_cmd = [
            self._lo_python, str(_HELPER_PATH),
            "--port", str(port),
            "--connect-timeout", str(config.UNO_READY_TIMEOUT),
            "--load-span", str(config.UNO_LOAD_SPAN),
        ]
        self._helper = subprocess.Popen(
            helper_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=Path(self._soffice_path).parent,
        )
        threading.Thread(
            target=self._read_stdout, args=(self._helper,), daemon=True
        ).start()
        threading.Thread(
            target=self._drain_stderr, args=(self._helper,), daemon=True
        ).start()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + config.UNO_READY_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for helper ready")
            try:
                ev = self._events.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("timed out waiting for helper ready")
            if ev.get("event") == "ready":
                return
            if ev.get("event") in ("fatal", "__eof__"):
                raise RuntimeError(ev.get("message", "helper died"))

    def restart(self) -> None:
        """Kill both processes and start over with a pristine profile.

        A force-killed soffice can leave stale lock state in its profile,
        so the profile dir is wiped and recreated.
        """
        self.kill()
        force_rmtree(self._profile_dir)
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._conversions_done = 0
        self.start()

    def kill(self) -> None:
        with _LIVE_SLOTS_LOCK:
            _LIVE_SLOTS.discard(self)
        if self._helper is not None:
            try:
                self._helper.stdin.close()
            except Exception:
                pass
            try:
                self._helper.kill()
            except Exception:
                pass
            self._helper = None
        if self._soffice is not None:
            # taskkill /T catches the soffice.bin child that Popen.kill()
            # would miss (soffice.exe is just a launcher on Windows).
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self._soffice.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            # Wait for the launcher to actually exit; Windows releases the
            # profile-dir file handles a beat after taskkill returns, and
            # the caller may rmtree the profile right after kill().
            try:
                self._soffice.wait(timeout=5)
            except Exception:
                pass
            self._soffice = None

    # ------------------------------------------------------------------ #
    # Conversion
    # ------------------------------------------------------------------ #

    def convert(
        self,
        rtf_path: Path,
        pdf_path: Path,
        timeout: float,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> None:
        """Convert one file, dispatching progress callbacks.

        The deadline is activity-based: it resets to ``now + timeout`` on
        every event from the helper, capped at ``3 * timeout`` total — a
        huge file that is demonstrably progressing isn't killed by the
        size heuristic, while a hung load dies after *timeout* of silence.

        Raises ``RuntimeError`` (file failed), :class:`UnoSlotDied`
        (service/helper gone — caller should ``restart()``), or
        :class:`UnoTimeout` (caller should ``restart()``).
        """
        if self._helper is None or self._helper.poll() is not None:
            raise UnoSlotDied("helper process is not running")

        if self._conversions_done >= config.UNO_RECYCLE_AFTER:
            self._log(
                f"[INFO] UNO slot {self.slot_idx} recycling after "
                f"{self._conversions_done} conversions"
            )
            self.restart()

        task_id = _next_task_id()
        task = {
            "id": task_id,
            "action": "convert",
            "rtf": str(rtf_path),
            "pdf": str(pdf_path),
        }
        try:
            self._helper.stdin.write(json.dumps(task, ensure_ascii=True) + "\n")
            self._helper.stdin.flush()
        except OSError as exc:
            raise UnoSlotDied(f"helper stdin write failed: {exc}") from exc

        deadline = time.monotonic() + timeout
        hard_deadline = time.monotonic() + 3 * timeout
        while True:
            remaining = min(deadline, hard_deadline) - time.monotonic()
            if remaining <= 0:
                raise UnoTimeout(
                    f"conversion of '{rtf_path.name}' timed out ({timeout:.0f}s idle limit)"
                )
            try:
                ev = self._events.get(timeout=remaining)
            except queue.Empty:
                continue  # loop re-checks the deadline

            if ev.get("event") == "__eof__":
                raise UnoSlotDied("helper stdout closed unexpectedly")
            if ev.get("event") == "fatal":
                raise UnoSlotDied(ev.get("message", "helper reported fatal"))
            if ev.get("id") != task_id:
                continue  # stale event from an abandoned task

            deadline = time.monotonic() + timeout  # activity resets the clock
            event = ev.get("event")
            if event == "progress" and progress_cb is not None:
                progress_cb(int(ev.get("pct", 0)), str(ev.get("phase", "")))
            elif event == "done":
                self._conversions_done += 1
                return
            elif event == "error":
                raise RuntimeError(ev.get("message", "conversion failed"))

    # ------------------------------------------------------------------ #
    # Reader threads
    # ------------------------------------------------------------------ #

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        events = self._events  # bound to this process generation's queue
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.put(json.loads(line))
                except ValueError:
                    self._log(
                        f"[WARN] UNO slot {self.slot_idx} unparseable "
                        f"helper output: {line[:200]}"
                    )
        except Exception:
            pass
        events.put({"event": "__eof__"})

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:
                line = line.strip()
                if line:
                    self._log(f"[DEBUG] UNO slot {self.slot_idx} stderr: {line[:300]}")
        except Exception:
            pass
