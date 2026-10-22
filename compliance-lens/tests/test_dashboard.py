"""The web dashboard (V5) through FastAPI's TestClient: sign-in, every page, reviews,
the queue, rules, starting an audit and the evidence files. No real accounts or network."""

import datetime
import json
import os
import re
import types

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from compliancelens import config, engine, evidence, locking, runner
from compliancelens.dashboard import app as dashboard
from compliancelens.dashboard import auth, jobs
from compliancelens.storage import db

RULES = """
- {id: AWS-01, title: Passwords, severity: high, collector: fake.ok,
   check: {field: value, op: '>=', value: 12}}
- {id: AWS-02, title: MFA, severity: high, collector: fake.users,
   check: {field: count, op: '==', value: 0}}
- {id: GH-01, title: Reviews, severity: medium, collector: fake.boom,
   check: {field: value, op: '>=', value: 1}}
- id: GH-06
  title: Base permission
  severity: medium
  screenshot: {site: github, url: "https://github.com/orgs/a", wait_for: {text: Base}}
"""
PASSWORD = "correct horse battery staple"
PAGES = [
    "/",
    "/run",
    "/run/progress",
    "/runs",
    "/runs/1",
    "/results/1",
    "/queue",
    "/compare",
    "/rules",
    "/evidence/2026-10-29/run-0001/AWS-01.json",
]


@pytest.fixture
def rules(tmp_path, monkeypatch):
    def boom(params):
        raise RuntimeError("GITHUB_TOKEN not set")

    fake = types.SimpleNamespace(
        ok=lambda params: {"value": 14},
        users=lambda params: {"count": 1, "users": ["intern-bob"]},
        boom=boom,
    )
    monkeypatch.setitem(engine.COLLECTORS, "fake", fake)
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


@pytest.fixture
def settings(rules):
    return auth.Settings(
        password=PASSWORD,
        secret="test-secret",
        reviewer="tester",
        rules_file=rules,
        hosts=("127.0.0.1", "localhost"),
    )


@pytest.fixture
def client(settings):
    manager = jobs.JobManager(settings.rules_file)
    with TestClient(dashboard.create_app(settings, manager), base_url="http://127.0.0.1") as c:
        c.manager = manager
        yield c
    assert manager.wait(10)


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def sign_in(client, password=PASSWORD, next="/"):
    form = client.get("/login")
    return client.post(
        "/login",
        data={"password": password, "csrf": csrf_of(form.text), "next": next},
        follow_redirects=False,
    )


@pytest.fixture
def admin(client):
    assert sign_in(client).status_code == 303
    return client


def post(client, path, data=None, page="/"):
    """POST a form with the CSRF token from `page`."""
    token = csrf_of(client.get(page).text)
    return client.post(path, data={"csrf": token, **(data or {})}, follow_redirects=False)


def audit(rules):
    return runner.run_audit(rules, screenshots=False)


def result_ids(run_id=1):
    conn = db.connect()
    try:
        return {r["rule_id"]: r["id"] for r in db.get_results(conn, run_id)}
    finally:
        conn.close()


# --- signing in ---------------------------------------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_every_page_needs_the_admin(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_a_post_without_signing_in_changes_nothing(client, rules):
    response = client.post("/rules/AWS-01", data={"enabled": "false"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/login")
    assert config.disabled_rules() == []


def test_signing_in_goes_where_you_were_going(client, rules):
    audit(rules)
    response = client.get("/runs/1?verdict=FAIL")
    assert "Admin password" in response.text and "run-0001" not in response.text
    assert 'name="next" value="/runs/1?verdict=FAIL"' in response.text
    signed = sign_in(client, next="/runs/1?verdict=FAIL")
    assert (signed.status_code, signed.headers["location"]) == (303, "/runs/1?verdict=FAIL")
    assert "run-0001" in client.get("/runs/1").text
    assert client.get("/login", follow_redirects=False).headers["location"] == "/"


def test_a_wrong_password_shows_nothing_and_waits(client, rules, no_sleep):
    audit(rules)
    response = sign_in(client, password="guess")
    assert response.status_code == 401
    assert "Wrong password." in response.text and "run-0001" not in response.text
    assert no_sleep == [auth.FAILED_LOGIN_DELAY]
    assert client.get("/", follow_redirects=False).status_code == 303


def test_no_password_set_means_nobody_signs_in(settings, no_sleep):
    unset = auth.Settings(None, "s", "tester", settings.rules_file, ("127.0.0.1",))
    with TestClient(dashboard.create_app(unset), base_url="http://127.0.0.1") as c:
        assert "No dashboard password is set" in c.get("/login").text
        response = sign_in(c, password="")
        assert response.status_code == 401 and "No password is set." in response.text
    assert no_sleep == [auth.FAILED_LOGIN_DELAY]


@pytest.mark.parametrize("target", ["//evil.example/x", "https://evil.example", "x", "/\\evil"])
def test_after_signing_in_you_stay_on_the_dashboard(client, target):
    assert sign_in(client, next=target).headers["location"] == "/"


def test_forms_need_the_session_token(admin):
    for path, data in [("/logout", {}), ("/run", {}), ("/rules/AWS-01", {})]:
        response = admin.post(path, data={"csrf": "forged", **data})
        assert response.status_code == 403 and "This form has expired" in response.text
    fresh = TestClient(admin.app, base_url="http://127.0.0.1")
    response = fresh.post("/login", data={"password": PASSWORD})  # no token, no session
    assert response.status_code == 403
    assert admin.get("/", follow_redirects=False).status_code == 200  # still signed in


def test_signing_out(admin):
    response = post(admin, "/logout")
    assert (response.status_code, response.headers["location"]) == (303, "/login")
    assert admin.get("/", follow_redirects=False).status_code == 303


def test_the_session_cookie(client):
    response = sign_in(client)
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("compliancelens_session=")
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert f"max-age={auth.SESSION_HOURS * 3600}" in cookie
    assert PASSWORD.lower() not in cookie


def test_security_headers(admin):
    headers = admin.get("/").headers
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store"
    static = admin.get("/static/app.js")
    assert static.status_code == 200 and "cache-control" not in static.headers


def test_only_this_computers_names_are_served(settings):
    with TestClient(dashboard.create_app(settings), base_url="http://evil.example") as c:
        assert c.get("/login").status_code == 400


def test_settings_from_the_environment(rules, monkeypatch):
    monkeypatch.setenv(auth.PASSWORD_ENV, "  ")
    first = auth.Settings.from_env(rules)
    assert first.password is None and first.reviewer == "admin"
    assert first.secret != auth.Settings.from_env(rules).secret  # random when not set
    monkeypatch.setenv(auth.PASSWORD_ENV, "pw")
    monkeypatch.setenv(auth.SECRET_ENV, "fixed")
    monkeypatch.setenv(auth.REVIEWER_ENV, "  Dana  ")
    second = auth.Settings.from_env(rules, ("127.0.0.1",))
    assert (second.password, second.secret, second.reviewer) == ("pw", "fixed", "Dana")
    assert "pw" not in repr(second) and "fixed" not in repr(second)


# --- pages on an empty database -----------------------------------------------------


def test_an_empty_dashboard(admin):
    assert "No complete full audit yet" in admin.get("/").text
    assert "No audits recorded yet" in admin.get("/runs").text
    assert "No complete audits yet" in admin.get("/queue").text
    assert "No audit has been started" in admin.get("/run/progress").text
    assert "4 of 4 rules are on" in admin.get("/rules").text
    for path in ["/runs/1", "/results/1", "/compare?a=1&b=2", "/nowhere"]:
        response = admin.get(path)
        assert response.status_code == 404 and "Not found" in response.text


# --- home, history, results ---------------------------------------------------------


def test_home_scores_the_latest_full_audit(admin, rules):
    audit(rules)
    runner.run_audit(rules, ["AWS-01"], screenshots=False)  # newer, partial
    page = admin.get("/").text
    assert 'Latest full audit: <a href="/runs/1">run-0001</a>' in page
    assert "25%" in page  # 1 PASS of 4 results
    assert "2 to review" in page
    assert "Newer runs, not in the score" in page and "run-0002" in page
    assert "Trend (complete full audits)" in page


def test_the_trend_marks_a_changed_rulebook(admin, rules):
    audit(rules)
    rules.write_text(RULES.replace("value: 12", "value: 10"))
    audit(rules)
    assert admin.get("/").text.count("rulebook changed") == 1


def test_changed_settings_are_marked(admin, rules):
    # V6: same rulebook, another organization: the trend and the comparison say so.
    rules.write_text(RULES.replace("https://github.com/orgs/a", "https://github.com/orgs/{org}"))
    settings_file = config.settings_path()
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("github: {org: one}\n")
    audit(rules)
    settings_file.write_text("github: {org: two}\n")
    audit(rules)
    audit(rules)
    home = admin.get("/").text
    assert home.count("settings changed") == 1 and "rulebook changed" not in home
    assert "the settings changed between the two runs" in admin.get("/compare?a=1&b=2").text
    assert "the settings changed" not in admin.get("/compare?a=2&b=3").text
    run_folder = next(evidence.evidence_root().glob("*/run-0001"))
    (run_folder / evidence.RUN_CONTEXT).unlink()  # unknown for a run without one
    assert "the settings changed" not in admin.get("/compare?a=1&b=2").text
    rules.write_text(rules.read_text().replace("value: 12", "value: 10"))
    settings_file.write_text("github: {org: three}\n")
    audit(rules)
    compared = admin.get("/compare?a=3&b=4").text
    assert "the rulebook changed" in compared and "the settings changed" not in compared


def test_history_pages_and_compares(admin, rules):
    for _ in range(dashboard.PAGE_SIZE + 2):
        runner.run_audit(rules, ["AWS-01"], screenshots=False)
    first = admin.get("/runs").text
    assert f"{dashboard.PAGE_SIZE + 2} run(s)" in first and "Page 1 of 2" in first
    assert "run-0027" in first and "run-0002" not in first
    assert "/compare?a=26&amp;b=27" in first
    second = admin.get("/runs?page=2").text
    assert "run-0002" in second and "run-0001" in second and "Newer" in second
    assert "Page 1 of 2" in admin.get("/runs?page=0").text


def test_results_with_filters_and_verified_evidence(admin, rules):
    audit(rules)
    page = admin.get("/runs/1").text
    assert "verified: " in page and "NOT verified" not in page
    assert page.count('href="/results/') == 4
    failed = admin.get("/runs/1?verdict=FAIL").text
    assert "AWS-02" in failed and "AWS-01</a>" not in failed
    github = admin.get("/runs/1?system=GitHub&severity=medium").text
    assert "GH-01" in github and "GH-06" in github and "AWS-0" not in github
    assert admin.get("/runs/1?verdict=MAYBE").text.count('href="/results/') == 4


def test_edited_evidence_never_shows_as_verified(admin, rules):
    summary = audit(rules)
    (summary.run_dir / "AWS-02.json").write_text('{"count": 0}')
    page = admin.get("/runs/1").text
    assert "NOT verified" in page and "AWS-02.json was changed" in page
    detail = admin.get(f"/results/{result_ids()['AWS-02']}").text
    assert "NOT verified" in detail and "AWS-02.json was changed" in detail


def test_verify_errors_show_as_not_verified(admin, rules, monkeypatch):
    audit(rules)
    monkeypatch.setattr(runner, "verify", lambda name: 1 / 0)
    assert "verify could not run: division by zero" in admin.get("/runs/1").text


# --- rule detail and reviews --------------------------------------------------------


def test_detail_shows_the_evidence_and_the_rule_as_run(admin, rules):
    audit(rules)
    rules.write_text(RULES.replace("value: 0", "value: 7"))  # changed since the run
    page = admin.get(f"/results/{result_ids()['AWS-02']}").text
    assert "&#34;users&#34;: [" in page and "intern-bob" in page  # escaped JSON
    assert "value: 0" in page and "value: 7" not in page  # the rule as the run read it
    assert "Approve FAIL" in page and "Change to PASS" in page
    assert "Reopen as NEEDS REVIEW" in page and "Mark PASS" not in page
    open_page = admin.get(f"/results/{result_ids()['GH-01']}").text
    assert "Mark PASS" in open_page and "Keep NEEDS REVIEW" in open_page


def test_reviewing_a_result(admin, rules):
    audit(rules)
    gh01 = result_ids()["GH-01"]
    url = f"/results/{gh01}"
    response = post(admin, f"{url}/review", {"action": "FAIL", "note": "no protection rule"}, url)
    assert (response.status_code, response.headers["location"]) == (303, f"{url}?saved=1")
    page = admin.get(f"{url}?saved=1").text
    assert "Review saved." in page and "set by a reviewer" in page
    assert "tester" in page and "no protection rule" in page
    assert "Approve FAIL" in page
    assert "1 to review" in admin.get("/").text


def test_review_mistakes_keep_the_note(admin, rules):
    audit(rules)
    url = f"/results/{result_ids()['GH-01']}"
    response = post(admin, f"{url}/review", {"action": "PASS", "note": "  "}, url)
    assert response.status_code == 400 and "a note is required" in response.text
    response = post(admin, f"{url}/review", {"action": "approve", "note": "fine"}, url)
    assert response.status_code == 400 and "approve only confirms a PASS or FAIL" in response.text
    assert ">fine</textarea>" in response.text
    response = post(admin, f"{url}/review", {"action": "", "note": "x"}, url)
    assert response.status_code == 400 and "choose what to do" in response.text
    response = post(admin, f"{url}/review", {"action": "PASS", "note": "x", "seen": "x"}, url)
    assert response.status_code == 400 and "The form was damaged" in response.text
    assert post(admin, "/results/999/review", {"action": "PASS", "note": "x"}).status_code == 404


def test_a_stale_review_form_is_refused(admin, rules):
    audit(rules)
    url = f"/results/{result_ids()['GH-01']}"
    old_form = admin.get(url).text  # opened before someone else's review
    post(admin, f"{url}/review", {"action": "FAIL", "note": "first"}, url)
    response = admin.post(
        f"{url}/review",
        data={"csrf": csrf_of(old_form), "action": "PASS", "note": "second", "seen": ""},
    )
    assert response.status_code == 409 and "was reviewed since you opened it" in response.text


def test_notes_and_documents_are_shown_as_text(admin, rules):
    audit(rules)
    url = f"/results/{result_ids()['GH-01']}"
    post(admin, f"{url}/review", {"action": "FAIL", "note": "<script>alert(1)</script>"}, url)
    page = admin.get(url).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def png_bytes():
    path = evidence.evidence_root() / "tmp.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), "white").save(path)
    data = path.read_bytes()
    path.unlink()
    return data


def rich_run(status=db.COMPLETE, files=True):
    """A run from before V5 (no rulebook copy) with a document, a screenshot and AI answers."""
    conn = db.connect()
    run_id = db.start_run(conn, "2026-10-29T14:00:00+00:00", db.FULL, "0.4.0", "r.yaml", "c" * 64)
    run_dir = evidence.create_run_dir(evidence.evidence_root(), datetime.date(2026, 10, 29), run_id)
    rel = f"2026-10-29/{evidence.run_name(run_id)}"
    db.set_run_dir(conn, run_id, rel)
    document = {"pages": [{"number": 1, "text": "Passwords need <b>12</b> characters."}]}
    entries = {
        "DOC-01.json": evidence.to_json_bytes(document),
        "DOC-01.source.md": b"# Policy\n",
        "GH-06.json": b"{}",
        "GH-06.png": png_bytes(),
        "GH-06.ai-input.png": png_bytes(),
        "GH-06.ai.json": b"{}",
        "DOC-01.pdf.txt": b"x",
    }
    if files:
        for name, data in entries.items():
            evidence.write_file(run_dir, name, data)
    sha = {name: evidence.sha256_bytes(data) for name, data in entries.items()}
    base = {"method": "ai-text", "reason": "r", "confidence": "high", "collected_at": "now"}
    doc = db.add_result(
        conn,
        run_id,
        {**base, "id": "DOC-01", "verdict": "PASS", "collector": "files.read_document"},
        {"path": f"{rel}/DOC-01.json", "sha256": sha["DOC-01.json"]},
        {"path": f"{rel}/DOC-01.json", "sha256": sha["DOC-01.json"]},
        None,
        {"path": f"{rel}/DOC-01.source.md", "sha256": sha["DOC-01.source.md"]},
    )
    shot = {
        "status": "captured",
        "path": f"{rel}/GH-06.png",
        "sha256": sha["GH-06.png"],
        "url": "https://github.com/orgs/a",
        "captured_at": "2026-10-29T14:00:05+00:00",
    }
    gh06 = db.add_result(
        conn,
        run_id,
        {**base, "id": "GH-06", "verdict": "NEEDS REVIEW", "method": "ai-vision"},
        {"path": f"{rel}/GH-06.json", "sha256": sha["GH-06.json"]},
        {"path": f"{rel}/GH-06.json", "sha256": sha["GH-06.json"]},
        shot,
    )
    for result_id, role, method in [
        (gh06, "primary", "ai-vision"),
        (doc, "primary", "ai-text"),
        (doc, "cross_check", "ai-vision"),
    ]:
        db.add_ai_evaluation(
            conn,
            {
                "result_id": result_id,
                "role": role,
                "method": method,
                "status": "accepted",
                "verdict": "PASS",
                "model_verdict": "PASS",
                "confidence": "high",
                "reason": "it says Read",
                "quote": "Base permissions: Read",
                "observed": "Read",
                "comparison": "agree" if role == "cross_check" else None,
                "provider": "openai",
                "model": "gpt-6-luna",
                "served_model": "gpt-6-luna-2026",
                "from_cache": int(role == "primary"),
                "cache_source": "run-0007" if role == "primary" else None,
                "attempts": 1,
                "input_tokens": 900,
                "output_tokens": 40,
                "cost_usd": 0.0002,
                "replies_path": f"{rel}/GH-06.ai.json",
                "input_path": f"{rel}/GH-06.ai-input.png" if method == "ai-vision" else None,
                "created_at": "now",
            },
        )
    if status == db.COMPLETE:
        db.finish_run(conn, run_id, "2026-10-29T14:01:00+00:00", f"{rel}/manifest.json", "0" * 64)
    conn.close()
    return run_id, {"DOC-01": doc, "GH-06": gh06}, rel


def test_detail_of_a_document_screenshot_and_ai_answer(admin):
    _, ids, rel = rich_run()
    doc = admin.get(f"/results/{ids['DOC-01']}").text
    assert "Passwords need &lt;b&gt;12&lt;/b&gt; characters." in doc
    assert f'href="/evidence/{rel}/DOC-01.source.md"' in doc
    assert "Cross-check (never changes the verdict)" in doc and "<strong>agree</strong>" in doc
    assert "the rulebook it used was not saved" in doc
    assert "(AI-generated verdict)" in doc
    shot = admin.get(f"/results/{ids['GH-06']}").text
    assert f'<img src="/evidence/{rel}/GH-06.png"' in shot
    assert "openai/gpt-6-luna (served: gpt-6-luna-2026)" in shot
    assert "the cache (run-0007)" in shot and "$0.0002" in shot
    assert f'href="/evidence/{rel}/GH-06.ai-input.png"' in shot
    assert "NOT verified" in shot  # the made-up manifest hash can't match


def test_detail_when_files_are_missing_or_the_run_did_not_finish(admin):
    _, ids, _ = rich_run(status=db.RUNNING, files=False)
    page = admin.get(f"/results/{ids['GH-06']}").text
    assert "Not available: the file is missing." in page
    assert "This run did not finish, so its results can't be reviewed." in page
    assert "run did not finish" in page
    response = post(admin, f"/results/{ids['GH-06']}/review", {"action": "PASS", "note": "x"})
    assert response.status_code == 400 and "did not finish" in response.text


def test_a_damaged_evidence_file_or_rulebook_copy(admin, rules):
    summary = audit(rules)
    (summary.run_dir / "AWS-01.json").write_text("{not json")
    (summary.run_dir / "rulebook.yaml").write_text("- [broken")
    page = admin.get(f"/results/{result_ids()['AWS-01']}").text
    assert "Not available: the file can&#39;t be read" in page
    assert "copy of the rulebook can&#39;t be read" in page
    (summary.run_dir / "rulebook.yaml").write_text("- {id: OTHER-1}\n")
    assert "has no such rule" in admin.get(f"/results/{result_ids()['AWS-01']}").text
    (summary.run_dir / "rulebook.yaml").unlink()
    assert "copy of the rulebook is missing" in admin.get(f"/results/{result_ids()['AWS-01']}").text


# --- review queue -------------------------------------------------------------------


def test_working_through_the_queue(admin, rules):
    audit(rules)
    ids = result_ids()
    queue = admin.get("/queue").text
    assert "<strong>2</strong> result(s) still NEEDS REVIEW" in queue
    assert f'href="/results/{ids["GH-01"]}?queue=1">Start with GH-01' in queue
    first = admin.get(f"/results/{ids['GH-01']}?queue=1").text
    assert f'href="/results/{ids["GH-06"]}?queue=1">Next open result' in first
    url = f"/results/{ids['GH-01']}"
    response = post(admin, f"{url}/review", {"action": "FAIL", "note": "a", "queue": "true"}, url)
    assert response.headers["location"] == f"/results/{ids['GH-06']}?queue=1"
    url = f"/results/{ids['GH-06']}"
    response = post(admin, f"{url}/review", {"action": "PASS", "note": "b", "queue": "true"}, url)
    assert response.headers["location"] == "/queue?run=1&done=1"
    done = admin.get("/queue?run=1&done=1").text
    assert "Nothing left to review" in done and "<strong>0</strong>" in done


def test_keeping_an_item_open_moves_on_but_keeps_it(admin, rules):
    audit(rules)
    ids = result_ids()
    url = f"/results/{ids['GH-06']}"
    data = {"action": "NEEDS REVIEW", "note": "page cut off", "queue": "true"}
    response = post(admin, f"{url}/review", data, url)
    assert response.headers["location"] == f"/results/{ids['GH-01']}?queue=1"
    assert "kept open: page cut off" in admin.get("/queue").text


def test_the_queue_of_another_run(admin, rules):
    audit(rules)
    runner.run_audit(rules, ["AWS-01"], screenshots=False)
    assert "run-0002 (partial, 0 open)" in admin.get("/queue").text
    assert "<strong>0</strong>" in admin.get("/queue?run=2").text
    assert admin.get("/queue?run=99").status_code == 404


def test_the_queue_without_a_full_audit(admin, rules):
    runner.run_audit(rules, ["GH-01"], screenshots=False)
    assert "<strong>1</strong> result(s)" in admin.get("/queue").text


# --- compare ------------------------------------------------------------------------


def test_comparing_two_runs(admin, rules):
    audit(rules)
    runner.run_audit(rules, ["AWS-01", "GH-01"], screenshots=False)
    form = admin.get("/compare").text
    assert '<option value="2" selected>' in form
    page = admin.get("/compare?a=2&b=1").text
    assert "run-0002 is partial (2 of 4 rules)" in page
    assert page.count("not run now") == 2  # AWS-02 and GH-06
    assert "/results/1" in page


# --- rules --------------------------------------------------------------------------


def test_turning_rules_off_and_on(admin):
    response = post(admin, "/rules/AWS-02", {}, "/rules")  # no "enabled": turn off
    assert (response.status_code, response.headers["location"]) == (303, "/rules#AWS-02")
    assert config.disabled_rules() == ["AWS-02"]
    page = admin.get("/rules").text
    assert "3 of 4 rules are on" in page and 'class="off"' in page
    assert "3 of 4 rules are turned on" in admin.get("/run").text
    post(admin, "/rules/AWS-02", {"enabled": "true"}, "/rules")
    assert config.disabled_rules() == []
    assert post(admin, "/rules/NOPE-1", {}, "/rules").status_code == 404


def test_rules_page_shows_how_each_rule_is_judged(admin, rules):
    rules.write_text(
        RULES
        + """
- {id: DOC-01, title: Policy, collector: files.read_document, params: {path: p.md},
   ai_check: {expect: "12 characters"}}
- {id: HR-01, title: Leavers, collector: fake.ok, check: {custom: no_unmatched_accounts}}
"""
    )
    page = admin.get("/rules").text
    for text in [
        "MinimumPasswordLength" if False else "value &gt;= 12",
        "a person reads the screenshot",
        "AI: 12 characters",
        "custom check: no_unmatched_accounts",
        "Policy documents",
    ]:
        assert text in page


def test_a_broken_settings_file_or_rulebook_is_shown(admin, rules):
    path = config.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("nope: 1\n")
    assert "nope: unknown setting" in admin.get("/rules").text
    response = post(admin, "/rules/AWS-01", {}, "/rules")
    assert response.status_code == 400 and "unknown setting" in response.text
    assert "The settings have a problem" in admin.get("/run").text
    rules.write_text("- {id: X}\n")
    assert "The rulebook has problems" in admin.get("/rules").text


# --- running an audit ---------------------------------------------------------------


def test_running_an_audit_from_the_dashboard(admin):
    response = post(admin, "/run", {"screenshots": "true"}, "/run")  # AI left off
    assert (response.status_code, response.headers["location"]) == (303, "/run")
    assert admin.manager.wait(10)
    progress = admin.get("/run/progress").text
    assert "Audit run-0001:" in progress and "finished" in progress
    assert 'data-active="0"' in progress and "See the results of run-0001" in progress
    assert "4 of 4 rules" in progress and "intern-bob" not in progress
    run = runner.history()[0]
    assert (run["status"], run["scope"], run["ai_settings"]) == ("complete", "full", None)
    assert "Audit run-0001:" in admin.get("/").text


def test_the_ai_and_screenshot_choices_are_checked(admin, monkeypatch):
    response = post(admin, "/run", {"cross_check": "true"}, "/run")
    assert response.status_code == 400 and "need the AI turned on" in response.text
    response = post(admin, "/run", {"ai": "true", "cross_check": "true"}, "/run")
    assert response.status_code == 400 and "A cross-check reads screenshots" in response.text
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "no-provider")
    response = post(admin, "/run", {"ai": "true"}, "/run")
    assert response.status_code == 400 and "The AI settings in .env have problems" in response.text
    assert "<li>" in response.text.split("have problems")[1][:200]
    assert runner.history() == []


def test_a_run_with_every_rule_off_or_a_broken_setup_is_refused(admin, rules):
    for rule_id in ["AWS-01", "AWS-02", "GH-01", "GH-06"]:
        config.set_rule_enabled(rule_id, False, ["AWS-01", "AWS-02", "GH-01", "GH-06"])
    response = post(admin, "/run", {}, "/run")
    assert response.status_code == 400 and "every rule is turned off" in response.text
    config.settings_path().write_text("nope: 1\n")
    response = post(admin, "/run", {}, "/run")
    assert response.status_code == 400 and "config/settings.yaml has problems" in response.text
    config.settings_path().unlink()
    rules.write_text("- {id: X}\n")
    response = post(admin, "/run", {}, "/run")
    assert response.status_code == 400 and "The rulebook can&#39;t be used" in response.text
    rules.unlink()
    assert post(admin, "/run", {}, "/run").status_code == 400
    assert runner.history() == []


def test_no_second_audit_while_one_runs(admin, no_sleep):
    with locking.AuditLock(locking.EXPERIMENT_CAPTURE):
        response = post(admin, "/run", {}, "/run")
    assert response.status_code == 409
    assert "Not started: an experiment capture (pid " in response.text
    assert runner.history() == []


def test_the_page_shows_what_is_missing(admin):
    page = admin.get("/run").text
    assert "Missing · GitHub:" in page and "GITHUB_TOKEN not set" in page
    assert "Missing · Settings:" in page and "github.org and github.repo not set" in page
    assert "python audit.py login github" in page


# --- evidence files -----------------------------------------------------------------


def test_evidence_files_are_served_safely(admin, rules, temp_storage):
    summary = audit(rules)
    rel = f"{summary.run_dir.relative_to(evidence.evidence_root()).as_posix()}"
    data = admin.get(f"/evidence/{rel}/AWS-02.json")
    assert data.status_code == 200 and data.headers["content-type"].startswith("text/plain")
    assert "sandbox" in data.headers["content-security-policy"]
    assert json.loads(data.text)["users"] == ["intern-bob"]
    rulebook = admin.get(f"/evidence/{rel}/rulebook.yaml")
    assert rulebook.headers["content-type"].startswith("text/plain")
    (summary.run_dir / "x.pdf").write_bytes(b"%PDF-1.4")
    pdf = admin.get(f"/evidence/{rel}/x.pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("attachment")
    (summary.run_dir / "page.html").write_text("<script>alert(1)</script>")
    secret = temp_storage / "secret.png"
    secret.write_bytes(b"not evidence")
    os.symlink(secret, summary.run_dir / "link.png")
    for path in [
        f"{rel}/page.html",
        "../compliance.db",
        "%2e%2e/compliance.db",
        f"{rel}/link.png",
        rel,
        f"{rel}/missing.json",
    ]:
        assert admin.get(f"/evidence/{path}").status_code == 404, path


def test_screenshots_are_images(admin):
    _, _, rel = rich_run()
    response = admin.get(f"/evidence/{rel}/GH-06.png")
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


# --- formatting helpers -------------------------------------------------------------


def test_formatting():
    assert dashboard.when(None) == "—"
    assert dashboard.when("not a time") == "not a time"
    assert dashboard.when("2026-10-29T16:02:00+02:00") == "2026-10-29 14:02 UTC"
    assert (dashboard.percent(None), dashboard.percent(0.255)) == ("—", "26%")
    assert (dashboard.money(None), dashboard.money(0.00012)) == ("unknown", "$0.0001")
    assert dashboard.duration(None) == "—"
    assert (dashboard.duration(9.74), dashboard.duration(12.9)) == ("9.7 s", "12 s")
    assert dashboard.duration(75) == "1 min 15 s"
    assert dashboard.verdict_class("FAIL") == "fail" and dashboard.verdict_class(None) == "none"
    assert dashboard.evidence_file(None) is None
    assert dashboard.evidence_file("\0bad") is None


def test_notes_and_comparisons_stay_calm(settings, rules):
    """From the live walkthrough: a model note is a quiet hint, and live pages always
    differ pixel by pixel, so the comparison doesn't call that out."""

    def finished(rules_file, options, on_event):
        return types.SimpleNamespace(
            run_id=1, warnings=["the model is not in the list"], skipped=[]
        )

    manager = jobs.JobManager(settings.rules_file, run=finished)
    with TestClient(dashboard.create_app(settings, manager), base_url="http://127.0.0.1") as c:
        sign_in(c)
        post(c, "/run", {}, "/run")
        assert manager.wait(10)
        progress = c.get("/run/progress").text
        assert '<p class="hint">Note: the model is not in the list</p>' in progress
        assert 'class="notice"' not in progress
    rich_run()
    again, _, _ = rich_run()
    with TestClient(dashboard.create_app(settings), base_url="http://127.0.0.1") as c:
        sign_in(c)
        assert "screenshot differs" not in c.get(f"/compare?a=1&b={again}").text
