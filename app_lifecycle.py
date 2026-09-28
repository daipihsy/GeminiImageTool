"""Keep the local web UI and its background process in sync."""

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable


class BrowserLifecycle:
    """Stop the server after the last browser tab closes.

    Gradio calls unload on both tab close and refresh, so a short grace period
    lets a refreshed page reconnect before the server is stopped.
    """

    def __init__(self, stop: Callable[[], None], grace_seconds: float = 5.0):
        self._stop = stop
        self._grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._open_tabs = 0
        self._timer: threading.Timer | None = None
        self._stopping = False
        self._exit_requested = False
        self._generation = 0

    def opened(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._open_tabs += 1
            if self._timer is not None and not self._exit_requested:
                self._generation += 1
                self._timer.cancel()
                self._timer = None

    def closed(self) -> None:
        with self._lock:
            if self._stopping or self._exit_requested or self._open_tabs == 0:
                return
            self._open_tabs -= 1
            if self._open_tabs == 0:
                self._schedule_stop(self._grace_seconds)

    def request_exit(self) -> None:
        """An explicit Exit click stops every tab and the server."""
        with self._lock:
            if not self._stopping:
                self._exit_requested = True
                self._schedule_stop(0.5)

    def _schedule_stop(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._generation += 1
        self._timer = threading.Timer(delay, self._stop_if_idle, args=(self._generation,))
        self._timer.daemon = True
        self._timer.start()

    def _stop_if_idle(self, generation: int) -> None:
        with self._lock:
            if self._stopping or generation != self._generation:
                return
            if self._open_tabs > 0 and not self._exit_requested:
                return
            self._stopping = True
            self._timer = None
        self._stop()


class InstanceLock:
    """Only one server may run from a given installation directory."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.record_path = base_dir / "runtime" / "instance.json"
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            name_hash = hashlib.sha256(str(self.base_dir.resolve()).casefold().encode("utf-8")).hexdigest()[:20]
            handle = kernel32.CreateMutexW(None, False, f"Local\\GeminiImageTool_{name_hash}")
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            return True

        import fcntl

        self._file = (self.record_path.parent / ".instance.lock").open("a+b")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            self._file = None
            return False
        return True

    def publish(self, url: str) -> None:
        record = {"pid": os.getpid(), "url": url}
        temporary = self.record_path.with_name(f"instance.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record), encoding="utf-8")
        temporary.replace(self.record_path)

    def wait_for_url(self, timeout_seconds: float = 45.0) -> str | None:
        deadline = time.monotonic() + timeout_seconds
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            try:
                record = json.loads(self.record_path.read_text(encoding="utf-8"))
                url = record["url"]
                if url.startswith("http://127.0.0.1:"):
                    with opener.open(f"{url.rstrip('/')}/config", timeout=1.0) as response:
                        config = json.load(response)
                    if config.get("title") == "AI 本地图像生成工具":
                        return url
            except (OSError, ValueError, KeyError, TypeError):
                pass
            time.sleep(0.5)
        return None

    def release(self) -> None:
        try:
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
            if record.get("pid") == os.getpid():
                self.record_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        if self._handle is not None:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._file is not None:
            self._file.close()
            self._file = None
