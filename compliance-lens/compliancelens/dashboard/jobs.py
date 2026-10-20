"""Audits started from the dashboard (V5): one at a time, in a background thread.

The page never waits for an audit. POST /run starts it here and returns at once; the
page then polls the job's progress. The job belongs to the dashboard process, not to a
browser tab, so reloading, moving between pages or closing the tab neither stops it
nor starts another one.

The worker thread opens its own database connection, browser and AI client
(runner.run_audit does). Only the Job below crosses between threads, always under
this module's lock, and pages get a copy.

One audit at a time: a second start is refused while this dashboard's job runs, and
runner.run_audit takes the shared lock (locking.py), so an audit from `audit.py run`
or the experiment's capture refuses it too. If the dashboard stops mid-audit, the run
stays 'running' with nobody holding the lock, and History shows it as interrupted.
"""

import copy
import datetime
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from compliancelens import engine, locking, run_options, runner

log = logging.getLogger(__name__)

STARTING, RUNNING, FINISHED, FAILED, REFUSED = (
    "starting",
    "running",
    "finished",
    "failed",
    "refused",
)
ACTIVE = (STARTING, RUNNING)


class Busy(RuntimeError):
    """An audit is already running; the message says which."""


@dataclass
class Job:
    id: int
    started_at: str  # UTC
    clock: float  # time.monotonic() at the start, for the elapsed time
    state: str = STARTING
    run_id: int | None = None
    total: int = 0
    done: int = 0
    current: str | None = None  # the rule being checked now
    finished: list[tuple[str, str]] = field(default_factory=list)  # (rule ID, verdict)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # rules turned off
    ended: float | None = None  # time.monotonic() at the end

    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    def elapsed(self, now: float) -> float:
        return (self.ended if self.ended is not None else now) - self.clock


class JobManager:
    def __init__(self, rules_file: Path, run=run_options.run, clock=time.monotonic):
        self.rules_file, self._run, self._clock = Path(rules_file), run, clock
        self._lock = threading.Lock()
        self._job: Job | None = None
        self._thread: threading.Thread | None = None
        self._count = 0

    def start(self, options: run_options.RunOptions) -> Job:
        """Start an audit in the background. Raises Busy if one is already running."""
        with self._lock:
            if self._job is not None and self._job.active:
                raise Busy("an audit started from this dashboard is still running")
            holder = locking.holder()
            if holder is not None:
                raise Busy(f"{locking.describe(holder)} is already running")
            self._count += 1
            now = datetime.datetime.now(datetime.UTC).isoformat()
            job = self._job = Job(self._count, now, self._clock())
            # Not a daemon: stopping the dashboard lets a running audit finish saving.
            thread = threading.Thread(
                target=self._work, args=(job, options), name=f"audit-job-{job.id}"
            )
            self._thread = thread
            thread.start()
            return copy.deepcopy(job)

    def current(self) -> Job | None:
        """A copy of the latest job (running or finished), or None."""
        with self._lock:
            return copy.deepcopy(self._job)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the running job's thread. True when no job is running."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def elapsed(self, job: Job) -> float:
        return job.elapsed(self._clock())

    # ------------------------------------------------------------- the worker

    def _work(self, job: Job, options: run_options.RunOptions) -> None:
        try:
            summary = self._run(self.rules_file, options, on_event=lambda e: self._event(job, e))
        except locking.Busy as e:
            self._end(job, REFUSED, str(e))
        except engine.RulebookError as e:
            self._end(job, FAILED, "the rulebook can't be used: " + "; ".join(e.problems))
        except (OSError, ValueError) as e:
            self._end(job, FAILED, f"the rulebook can't be read: {e}")
        except runner.StorageError as e:
            self._end(job, FAILED, str(e))
        except Exception as e:  # never lose the reason, whatever it is
            log.exception("dashboard audit failed")
            self._end(job, FAILED, f"unexpected error: {type(e).__name__}: {e}")
        else:
            with self._lock:
                job.run_id = summary.run_id
                job.warnings = list(summary.warnings)
                job.skipped = list(summary.skipped)
            self._end(job, FINISHED)

    def _event(self, job: Job, event: runner.Progress) -> None:
        with self._lock:
            job.run_id, job.total, job.done = event.run_id, event.total, event.done
            if event.kind == runner.RUN_STARTED:
                job.state = RUNNING
            elif event.kind == runner.RULE_STARTED:
                job.current = event.rule_id
            elif event.kind == runner.RULE_FINISHED:
                job.current = None
                job.finished.append((event.rule_id, event.verdict))

    def _end(self, job: Job, state: str, error: str | None = None) -> None:
        with self._lock:
            job.state, job.error, job.current, job.ended = state, error, None, self._clock()
