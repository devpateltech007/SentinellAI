"""One audit at a time (V5): a lock shared by every audit and the experiment's capture.

Two audits at once would interleave their browser, AI budget and database writes, and
an audit during the research experiment's capture (which changes the test accounts on
purpose) would record the experiment's temporary settings as the real ones. So
`audit.py run`, the dashboard and `python -m experiment.lab capture` all take this
lock first; the second one is refused with who holds it.

The lock is an operating-system file lock (flock) on a file next to the database
(compliance.db.lock). The system releases it when its process ends, even after a crash
or a kill, so it is never left stuck, and a run still marked 'running' while nobody
holds the lock was interrupted. The file also says who holds it (what, process ID,
since when, which run), for the message the second one sees. Locks taken in one process
also exclude each other, so the dashboard's own threads are covered too.

macOS and Linux only (fcntl), like the rest of the tool.
"""

import contextlib
import datetime
import fcntl
import json
import os
import time
from pathlib import Path

from compliancelens.storage import db

AUDIT, EXPERIMENT_CAPTURE = "audit", "experiment capture"
WAIT_SECONDS = 1.0  # a quick look by holder() can hold the file for a moment
_STEP = 0.05
_sleep = time.sleep  # tests replace it


class Busy(RuntimeError):
    """Someone else holds the lock."""

    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(f"{describe(holder)} is already running: wait for it to finish")


def lock_path() -> Path:
    path = db.db_path()
    return path.with_name(f"{path.name}.lock")


def describe(holder: dict) -> str:
    """'an audit (run-0042, pid 123, since 2026-10-29 14:02 UTC)', or as much as is known."""
    what = holder.get("purpose") or "another audit"
    article = "" if what.startswith("another") else ("an " if what[0] in "aeiou" else "a ")
    details = []
    if holder.get("run_id"):
        details.append(f"run-{holder['run_id']:04d}")
    if holder.get("pid"):
        details.append(f"pid {holder['pid']}")
    if holder.get("since"):
        with contextlib.suppress(ValueError):
            since = datetime.datetime.fromisoformat(holder["since"])
            details.append(f"since {since:%Y-%m-%d %H:%M} UTC")
    return f"{article}{what}" + (f" ({', '.join(details)})" if details else "")


def _read(path: Path) -> dict:
    """What the lock file says about its holder ({} if it can't be read)."""
    try:
        holder = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return holder if isinstance(holder, dict) else {}


def holder(path: Path | None = None) -> dict | None:
    """Who holds the lock now ({} if unknown), or None if nobody does.

    Takes a shared lock for a moment to find out, which never blocks anyone for long:
    acquire() waits up to WAIT_SECONDS for such a look to finish.
    """
    path = Path(path or lock_path())
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return _read(path)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


class AuditLock:
    """Hold the lock for one audit or capture batch: `with AuditLock(AUDIT) as lock:`."""

    def __init__(self, purpose: str = AUDIT, path: Path | None = None):
        self.purpose = purpose
        self.path = Path(path or lock_path())
        self._fd: int | None = None
        self._info: dict = {}

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> "AuditLock":
        """Take the lock, or raise Busy with who holds it."""
        if self.held:
            raise RuntimeError("this lock is already held")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = WAIT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline <= 0:
                    os.close(fd)
                    raise Busy(_read(self.path))
                deadline -= _STEP
                _sleep(_STEP)
        self._fd = fd
        self._info = {
            "purpose": self.purpose,
            "pid": os.getpid(),
            "since": datetime.datetime.now(datetime.UTC).isoformat(),
            "run_id": None,
        }
        self._write()
        return self

    def set_run(self, run_id: int) -> None:
        """Say which run holds the lock (once the run is recorded)."""
        self._info["run_id"] = run_id
        self._write()

    def _write(self) -> None:
        data = json.dumps(self._info, sort_keys=True).encode("utf-8")
        os.ftruncate(self._fd, 0)
        os.pwrite(self._fd, data, 0)

    def release(self) -> None:
        if not self.held:
            return
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)  # nobody holds it: no stale holder left in the file
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def __enter__(self) -> "AuditLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
