"""The audit lock (V5): one audit or experiment capture at a time, never left stuck."""

import json
import os
import subprocess
import sys

import pytest

from compliancelens import locking
from compliancelens.storage import db

# A separate process that takes the lock the same way, then waits to be killed.
HOLD = """
import fcntl, json, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
os.write(fd, json.dumps({"purpose": "audit", "pid": os.getpid(), "run_id": 7}).encode())
print("held", flush=True)
time.sleep(60)
"""


def test_the_lock_file_is_next_to_the_database(temp_storage):
    assert locking.lock_path() == temp_storage / "compliance.db.lock"
    assert locking.lock_path().parent == db.db_path().parent


def test_nobody_holds_it_at_first():
    assert locking.holder() is None


def test_holding_and_releasing(temp_storage):
    with locking.AuditLock() as lock:
        assert lock.held
        holder = locking.holder()
        assert holder["purpose"] == locking.AUDIT
        assert holder["pid"] == os.getpid()
        assert holder["run_id"] is None
        assert holder["since"].endswith("+00:00")
        lock.set_run(42)
        assert locking.holder()["run_id"] == 42
        assert oct(locking.lock_path().stat().st_mode & 0o777) == "0o600"
    assert not lock.held
    assert locking.holder() is None
    assert locking.lock_path().read_text() == ""  # no stale holder left behind


def test_a_second_lock_is_refused_with_who_holds_it(no_sleep):
    with locking.AuditLock() as first:
        first.set_run(7)
        with pytest.raises(locking.Busy) as e:
            locking.AuditLock(locking.EXPERIMENT_CAPTURE).acquire()
    message = str(e.value)
    assert message.startswith(f"an audit (run-0007, pid {os.getpid()}, since ")
    assert message.endswith("UTC) is already running: wait for it to finish")
    assert e.value.holder["run_id"] == 7
    assert len(no_sleep) == round(locking.WAIT_SECONDS / 0.05)  # it waited a moment first


def test_a_lock_freed_while_waiting_is_taken(monkeypatch):
    first = locking.AuditLock().acquire()
    monkeypatch.setattr(locking, "_sleep", lambda seconds: first.release())
    with locking.AuditLock(locking.EXPERIMENT_CAPTURE) as second:
        assert locking.holder()["purpose"] == "experiment capture"
    assert not second.held


def test_the_same_lock_cannot_be_taken_twice():
    with locking.AuditLock() as lock, pytest.raises(RuntimeError, match="already held"):
        lock.acquire()


def test_releasing_a_lock_not_held_does_nothing():
    lock = locking.AuditLock()
    lock.release()
    assert not lock.held


def test_a_crashed_holder_never_leaves_it_stuck(temp_storage):
    path = locking.lock_path()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        assert locking.holder() == {"purpose": "audit", "pid": holder.pid, "run_id": 7}
        with pytest.raises(locking.Busy, match=f"pid {holder.pid}"):
            locking.AuditLock().acquire()
    finally:
        holder.kill()
        holder.wait()
        holder.stdout.close()
    assert locking.holder() is None  # the system let go when the process died
    with locking.AuditLock():
        pass


@pytest.mark.parametrize(
    ("holder", "text"),
    [
        ({}, "another audit"),
        ({"purpose": "audit"}, "an audit"),
        ({"purpose": "experiment capture", "pid": 9}, "an experiment capture (pid 9)"),
        ({"purpose": "audit", "since": "yesterday"}, "an audit"),
        (
            {"purpose": "audit", "run_id": 3, "since": "2026-10-29T14:02:11+00:00"},
            "an audit (run-0003, since 2026-10-29 14:02 UTC)",
        ),
        ({"purpose": "dashboard job"}, "a dashboard job"),
    ],
)
def test_describe(holder, text):
    assert locking.describe(holder) == text


@pytest.mark.parametrize("content", ["not json", json.dumps(["a", "list"])])
def test_an_unreadable_lock_file_means_an_unknown_holder(content):
    with locking.AuditLock():
        locking.lock_path().write_text(content)
        assert locking.holder() == {}
        with pytest.raises(locking.Busy, match="^another audit is already running"):
            locking.AuditLock().acquire()
