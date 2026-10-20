"""Takes the experiment's pictures, one batch of cases at a time.

For each case: change the account (world.py), wait until the API shows the case's
state (read with the audit's own read-only logins), read the API, take the picture
the way the audit does (or with the case's research profile), read the API again,
and keep the case only if nothing changed in between. At the end of the batch,
everything is put back, even if a case went wrong.

A batch holds the audit lock (compliancelens/locking.py) from the first change until
everything is put back, so no audit runs while the accounts are in a made-up state.

Each case is saved in data/cases/<id>/:
    page.png    the browser's own picture, no banner: exactly what the AI is shown
    api.json    the API data at the time of the picture, and the code's verdict on it
    case.json   the case, how the picture was taken, and the picture's hashes
"""

import contextlib
import datetime
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from compliancelens import __version__, engine, evidence, locking
from compliancelens.connectors import browser
from compliancelens.evaluator import images
from experiment.lab import cases, data_dir

SAVED, FAILED, DISCARDED = "saved", "failed", "discarded"
STATE_WAIT_SECONDS = 120  # IAM and S3 changes can take a while to show everywhere
STATE_POLL_SECONDS = 5


class CaptureError(RuntimeError):
    """A saved case can't be used (missing or changed files)."""


@dataclass
class Outcome:
    case_id: str
    status: str  # saved, failed or discarded
    reason: str


def cases_dir() -> Path:
    return data_dir() / "cases"


def read_api(rule: dict, facts: dict) -> dict:
    """The rule's API data as the audit reads it (read-only logins), for this case."""
    data = engine.get_collector(rule["collector"])(rule.get("params") or {})
    return cases.scope(rule["id"], data, facts.get("bucket"))


def wait_for_state(case, rule, facts, read=read_api, sleep=time.sleep, clock=time.monotonic):
    """Read the API until the code's verdict is the case's state, the same on two reads
    in a row. Returns (data, the code's result). Raises TimeoutError if it never is."""
    deadline = clock() + STATE_WAIT_SECONDS
    last = None
    while True:
        try:
            data = read(rule, facts)
            result = engine.judge(rule, data)
            seen = result["verdict"]
        except Exception as e:  # e.g. a new bucket not listed yet
            data, result, seen = None, None, f"an error ({e})"
        if seen == case.state:
            if data == last:
                return data, result
            last = data
        else:
            last = None
        if clock() >= deadline:
            raise TimeoutError(
                f"the API still shows {seen} after {STATE_WAIT_SECONDS} s, not {case.state}"
            )
        sleep(STATE_POLL_SECONDS)


def _record(case, rule, facts, shot, page, result) -> dict:
    return {
        "case": {
            "id": case.id,
            "rule": case.rule,
            "state": case.state,
            "kind": case.kind,
            "pilot": case.pilot,
            "note": case.note,
            "setup": case.setup,
            "view": case.view,
        },
        "rule": cases.ai_rule(rule),
        "facts": facts,
        "capture": {
            "status": shot.status,
            "reason": shot.reason,
            "profile": shot.profile,
            "requested_url": browser.clean_url(shot.requested_url),
            "final_url": browser.clean_url(shot.final_url),
            "captured_at": shot.captured_at,
            "full_page": shot.full_page,
            "settled": shot.settled,
        },
        "png_sha256": hashlib.sha256(shot.png).hexdigest(),
        "pixel_sha256": images.pixel_sha256(page),
        "width": page.width,
        "height": page.height,
        "code": {"verdict": result["verdict"], "reason": result["reason"]},
        "tool_version": __version__,
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def save_case(root: Path, case, rule, facts, shot, data, result) -> dict:
    folder = root / case.id
    folder.mkdir(parents=True, exist_ok=True)
    page = images.from_capture(shot.png)
    record = _record(case, rule, facts, shot, page, result)
    evidence.write_atomic(folder / "page.png", shot.png)
    evidence.write_atomic(
        folder / "api.json", evidence.to_json_bytes({"data": data, "code": record["code"]})
    )
    evidence.write_atomic(folder / "case.json", evidence.to_json_bytes(record))
    return record


def capture_case(
    case, rules, setup, original, shooter_factory, root, read, sleep, clock
) -> Outcome:
    facts = setup.apply(case, original)
    rule = cases.case_rule(rules, case, facts.get("bucket"))
    try:
        data, result = wait_for_state(case, rule, facts, read, sleep, clock)
    except TimeoutError as e:
        return Outcome(case.id, FAILED, str(e))
    with shooter_factory(case.profile()) as shooter:
        shot = shooter.capture(rule)
    try:
        after = read(rule, facts)
    except Exception as e:
        return Outcome(case.id, DISCARDED, f"the API could not be read again ({e})")
    if after != data:
        return Outcome(case.id, DISCARDED, "the API data changed while the picture was taken")
    if not shot.ok:
        return Outcome(case.id, FAILED, f"no picture: {shot.reason}")
    save_case(root, case, rule, facts, shot, data, result)
    return Outcome(case.id, SAVED, shot.reason)


def capture_batch(
    batch,
    rules: dict,
    setup,
    *,
    shooter_factory=browser.Screenshotter,
    root: Path | None = None,
    read=read_api,
    log=print,
    sleep=time.sleep,
    clock=time.monotonic,
) -> list[Outcome]:
    """Capture every case of the batch, then put the accounts back (always).

    Raises locking.Busy, before changing anything, while an audit is running.
    """
    root = root or cases_dir()
    with locking.AuditLock(locking.EXPERIMENT_CAPTURE):
        return _capture_locked(batch, rules, setup, shooter_factory, root, read, log, sleep, clock)


def _capture_locked(batch, rules, setup, shooter_factory, root, read, log, sleep, clock):
    original = setup.begin({case.rule for case in batch})
    outcomes = []
    try:
        for number, case in enumerate(batch, start=1):
            log(f"[{number}/{len(batch)}] {case.id}: {case.describe()}")
            try:
                outcome = capture_case(
                    case, rules, setup, original, shooter_factory, root, read, sleep, clock
                )
            except Exception as e:  # one case going wrong must not stop the batch
                outcome = Outcome(case.id, FAILED, f"{type(e).__name__}: {e}")
            outcomes.append(outcome)
            log(f"        {outcome.status}: {outcome.reason}")
    finally:
        log("Putting the settings back...")
        for line in setup.restore():
            log(f"  {line}")
    return outcomes


# --------------------------------------------------------------- reading ----


def load_captured(root: Path | None = None) -> list[dict]:
    """Every saved case (case.json), with its picture checked against its hash."""
    root = root or cases_dir()
    found = []
    for path in sorted(root.glob("*/case.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        png = path.with_name("page.png")
        if (
            not png.is_file()
            or hashlib.sha256(png.read_bytes()).hexdigest() != record["png_sha256"]
        ):
            raise CaptureError(f"{png} is missing or changed since it was captured")
        record["folder"] = str(path.parent)
        found.append(record)
    return found


def page_png(record: dict) -> bytes:
    return (Path(record["folder"]) / "page.png").read_bytes()


def api_data(record: dict) -> dict:
    with contextlib.suppress(OSError, ValueError):
        return json.loads((Path(record["folder"]) / "api.json").read_text(encoding="utf-8"))["data"]
    return {}
