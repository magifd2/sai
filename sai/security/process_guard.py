"""ProcessGuard: track child processes and clean up zombies / hung processes."""

import os
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime

from ..utils.logging import get_logger
from ..utils.time import utcnow

logger = get_logger(__name__)


@dataclass
class ProcessEntry:
    pid: int
    user_id: str
    started_at: datetime
    max_runtime_seconds: int


class ProcessGuard:
    def __init__(self) -> None:
        self._processes: dict[int, ProcessEntry] = {}
        self._lock = threading.Lock()

    def register(self, pid: int, user_id: str, max_runtime_seconds: int = 30) -> None:
        with self._lock:
            self._processes[pid] = ProcessEntry(
                pid=pid,
                user_id=user_id,
                started_at=utcnow(),
                max_runtime_seconds=max_runtime_seconds,
            )
        logger.debug("process_guard.register", pid=pid, user_id=user_id)

    def unregister(self, pid: int) -> None:
        with self._lock:
            self._processes.pop(pid, None)

    def check_all(self) -> None:
        """Kill processes that have exceeded their max runtime."""
        now = utcnow()
        with self._lock:
            entries = list(self._processes.values())

        for entry in entries:
            elapsed = (now - entry.started_at).total_seconds()
            if elapsed > entry.max_runtime_seconds:
                self._kill(entry)

    def cleanup_zombies(self) -> None:
        """Reap completed child processes (non-blocking waitpid)."""
        with self._lock:
            pids = list(self._processes.keys())

        for pid in pids:
            try:
                result_pid, _ = os.waitpid(pid, os.WNOHANG)
                if result_pid == pid:
                    self.unregister(pid)
                    logger.debug("process_guard.reaped", pid=pid)
            except ChildProcessError:
                self.unregister(pid)

    def _kill(self, entry: ProcessEntry) -> None:
        logger.warning(
            "process_guard.killing_hung_process",
            pid=entry.pid,
            user_id=entry.user_id,
        )
        try:
            # Kill entire process group
            os.killpg(os.getpgid(entry.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        self.unregister(entry.pid)
