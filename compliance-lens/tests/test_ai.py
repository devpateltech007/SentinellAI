"""The AI checks: every row of the table in evaluator/ai.py, the budget and the cache.

A fake provider plays the model, so every answer is known in advance. No network.
"""

import json

import pytest
from PIL import Image, ImageDraw

from compliancelens import engine
from compliancelens.evaluator import ai, budget, images, prompt
from compliancelens.evaluator import cache as ai_cache
from compliancelens.evaluator import settings as ai_settings
from compliancelens.evaluator.providers import base
from compliancelens.storage import db

KEY = "test-key-not-real-456"
SENTENCE = "Every password must be at least 14 characters long."
DOCUMENT = {
    "status": "ok",
    "path": "password-policy.pdf",
    "folder": "policies/examples/compliant",
    "sha256": "d" * 64,
    "extractor": "pypdf 6.19.0",
    "extract_version": 1,
    "pages": [{"number": 1, "text": f"Example Labs Password Policy\n{SENTENCE}\nNo exceptions."}],
}
DOC_RULE = {
    "id": "DOC-01",
    "title": "Password policy requires 12+ characters",
    "ai_check": {"expect": "Passwords must be at least 12 characters", "missing_means": "fail"},
}
VISION_RULE = {
    "id": "GH-06",
    "title": "Organization base repository permission is Read or None",
    "ai_check": {"expect": "The base permission is Read or No permission"},
}


def settings(**values):
    env = {
        "COMPLIANCELENS_AI_MODEL": "openai/gpt-6-luna",
        "COMPLIANCELENS_AI_API_KEY": KEY,
        "COMPLIANCELENS_AI_PRICE_INPUT": "0.10",
        "COMPLIANCELENS_AI_PRICE_OUTPUT": "0.50",
    }
    env.update({f"COMPLIANCELENS_AI_{name}": value for name, value in values.items()})
    return ai_settings.resolve({k: v for k, v in env.items() if v is not None})


def answer(**changes) -> dict:
    return {
        "observed": "14 characters",
        "quote": SENTENCE,
        "evidence_found": True,
        "verdict": "PASS",
        "confidence": "high",
        "reason": "The policy requires at least 14 characters, more than 12.",
        **changes,
    }


def reply(content=None, stop=base.COMPLETE, tokens=(1000, 100), text=None) -> base.AIReply:
    if text is None:
        text = json.dumps(answer() if content is None else content)
    return base.AIReply(
        text=text,
        stop=stop,
        served_model="gpt-6-luna",
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        raw={"id": "chatcmpl-1", "choices": []},
        request_id="req_1",
        elapsed_ms=900,
    )


class FakeProvider:
    """Plays the model: gives back the queued replies (or raises the queued errors)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def waits(monkeypatch):
    waited = []
    monkeypatch.setattr(ai, "_sleep", waited.append)
    return waited


def evaluator(*replies, settings_=None, **options):
    provider = FakeProvider(*replies)
    made = []

    def make(s):
        made.append(s)
        return provider

    found = ai.Evaluator(settings_ or settings(), make_provider=make, **options)
    return found, provider, made


def judge_document(*replies, rule=DOC_RULE, document=DOCUMENT, **options):
    found, provider, _ = evaluator(*replies, **options)
    return found.document(rule, document), provider


def page() -> Image.Image:
    image = Image.new("RGB", (1440, 900), "white")
    ImageDraw.Draw(image).text((40, 100), "Base permissions: Read", fill="black")
    return image


# ------------------------------------------------------------ 1: no evidence ----


def test_a_document_that_was_not_read_is_never_sent():
    missing = {"status": "not_found", "reason": "password-policy.pdf not found", "path": "x"}
    outcome, provider = judge_document(document=missing)
    assert (outcome.status, outcome.verdict) == (ai.EVIDENCE_MISSING, engine.NEEDS_REVIEW)
    assert outcome.reason == "the document was not read: password-policy.pdf not found"
    assert provider.requests == [] and outcome.calls == 0


def test_no_screenshot_is_never_sent():
    found, provider, made = evaluator()
    outcome = found.screenshot(VISION_RULE, None, "GitHub login expired")
    assert (outcome.status, outcome.method) == (ai.EVIDENCE_MISSING, engine.AI_VISION)
    assert outcome.reason == "no screenshot to judge: GitHub login expired"
    assert made == []


def test_a_screenshot_too_big_to_read_is_never_sent():
    found, provider, _ = evaluator(settings_=settings(IMAGE_MAX_EDGE="400"))
    outcome = found.screenshot(VISION_RULE, page())
    assert outcome.status == ai.IMAGE_TOO_BIG
    assert "would have to shrink to 28%" in outcome.reason
    assert outcome.evidence["pixel_sha256"] == images.pixel_sha256(page())
    assert provider.requests == []


# --------------------------------------------------------- 2: no call at all ----


def test_settings_are_needed_unless_the_ai_is_off():
    with pytest.raises(ValueError, match="AI settings are needed"):
        ai.Evaluator(None)
    off = ai.Evaluator(None, enabled=False)
    assert off.document(DOC_RULE, DOCUMENT).status == ai.DISABLED
    assert off.screenshot(VISION_RULE, page()).status == ai.DISABLED
    assert off.totals() == {
        "calls": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    }


def test_ai_turned_off():
    outcome, provider = judge_document(enabled=False)
    assert (outcome.status, outcome.reason) == (ai.DISABLED, "AI checks are turned off (--no-ai)")
    assert provider.requests == []


def test_no_key():
    outcome, provider = judge_document(settings_=settings(API_KEY=None))
    assert outcome.status == ai.NOT_CONFIGURED
    assert "add COMPLIANCELENS_AI_API_KEY for openai/gpt-6-luna" in outcome.reason
    assert provider.requests == []


def test_the_sdk_is_missing_and_is_looked_for_once():
    tries = []

    def missing(s):
        tries.append(s)
        raise base.NotInstalled("the openai package is not installed (run: make setup)")

    found = ai.Evaluator(settings(), make_provider=missing)
    first = found.document(DOC_RULE, DOCUMENT)
    second = found.screenshot(VISION_RULE, page())
    assert (first.status, second.status) == (ai.NOT_INSTALLED, ai.NOT_INSTALLED)
    assert first.reason == "the openai package is not installed (run: make setup)"
    assert len(tries) == 1


def test_the_call_limit():
    outcome, provider = judge_document(settings_=settings(MAX_CALLS_PER_RUN="0"))
    assert outcome.status == ai.BUDGET_EXHAUSTED
    assert outcome.reason == "AI budget used up: the limit of 0 AI calls per run was reached"
    assert provider.requests == []


def test_the_dollar_limit():
    outcome, provider = judge_document(settings_=settings(MAX_COST_PER_RUN_USD="0.001"))
    assert outcome.status == ai.BUDGET_EXHAUSTED
    assert "which would pass the $0.0010 limit per run ($0.0000 spent)" in outcome.reason
    assert budget.dollars(2) == "$2.00" and budget.dollars(0.0045) == "$0.0045"
    assert provider.requests == []


# ------------------------------------------------------ 3, 4: provider errors ----


def test_a_temporary_error_is_tried_once_more(waits):
    outcome, provider = judge_document(base.TransientError("HTTP 503: busy", 503), reply())
    assert (outcome.status, outcome.verdict) == (ai.ACCEPTED, engine.PASS)
    assert len(provider.requests) == 2 and waits == [ai.RETRY_WAIT_SECONDS]
    first, second = outcome.attempts
    assert first["error"] == {
        "kind": "TransientError",
        "message": "HTTP 503: busy",
        "status_code": 503,
    }
    assert second["answer"]["verdict"] == "PASS"
    assert outcome.calls == 1  # the failed attempt cost nothing


def test_a_dropped_connection_gets_three_more_tries(waits):
    dropped = base.DroppedConnection("could not connect: [SSL: SSLV3_ALERT_BAD_RECORD_MAC]")
    outcome, provider = judge_document(dropped, dropped, dropped, reply())
    assert (outcome.status, outcome.verdict) == (ai.ACCEPTED, engine.PASS)
    assert len(outcome.attempts) == 4 and len(waits) == 3
    assert [a["attempt"] for a in outcome.attempts] == [1, 2, 3, 4]
    assert outcome.calls == 1  # dropped uploads reached no model and cost nothing


def test_dropped_connections_then_the_shared_retry_then_give_up(waits):
    dropped = base.DroppedConnection("could not connect: connection reset")
    outcome, provider = judge_document(*[dropped] * 5)
    assert outcome.status == ai.PROVIDER_ERROR
    assert outcome.reason == "AI provider error: could not connect: connection reset"
    assert len(provider.requests) == 5 and len(waits) == 4


def test_a_second_temporary_error_gives_up(waits):
    outcome, provider = judge_document(
        base.TransientError("could not connect: refused"), base.TransientError("timeout")
    )
    assert (outcome.status, outcome.verdict) == (ai.PROVIDER_ERROR, engine.NEEDS_REVIEW)
    assert outcome.reason == "AI provider error: timeout"
    assert len(outcome.attempts) == 2


def test_a_lasting_error_is_not_retried(waits):
    outcome, provider = judge_document(base.PermanentError("HTTP 401: bad key", 401))
    assert (outcome.status, outcome.reason) == (
        ai.PROVIDER_ERROR,
        "AI provider error: HTTP 401: bad key",
    )
    assert len(provider.requests) == 1 and waits == []


def test_a_bug_in_an_adapter_does_not_stop_the_audit(waits):
    outcome, provider = judge_document(KeyError("choices"))
    assert (outcome.status, outcome.reason) == (ai.PROVIDER_ERROR, "AI provider error: 'choices'")
    assert outcome.attempts[0]["error"]["kind"] == "KeyError"


# --------------------------------------------- 5, 6: refused or cut off ----


@pytest.mark.parametrize("stop", [base.REFUSAL, base.CONTENT_FILTER])
def test_a_refusal(stop, waits):
    outcome, provider = judge_document(reply(stop=stop, text=""))
    assert (outcome.status, outcome.verdict) == (ai.REFUSAL, engine.NEEDS_REVIEW)
    assert outcome.reason == f"the AI declined to answer ({stop})"
    assert len(provider.requests) == 1


def test_a_cut_off_answer(waits):
    outcome, provider = judge_document(reply(stop=base.MAX_TOKENS, text='{"observed": "14'))
    assert outcome.status == ai.TRUNCATED
    assert len(provider.requests) == 1


# ------------------------------------------------- 7, 8: invalid answers ----


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "the reply is empty"),
        ("The policy looks fine to me.", "not JSON"),
        (json.dumps({**answer(), "extra": 1}), "wrong fields"),
        (json.dumps({**answer(), "confidence": "certain"}), "confidence must be one of"),
        ('{"verdict": "PASS", "verdict": "FAIL"}', "appears twice"),
        (json.dumps(answer(reason="ok")), "reason must be 10 to 600 characters"),
        (json.dumps(answer(quote="x" * 501)), "quote must be 0 to 500 characters"),
        (json.dumps(answer(observed="x" * 201)), "observed must be 0 to 200 characters"),
    ],
)
def test_an_invalid_answer_is_asked_once_more(text, problem, waits):
    outcome, provider = judge_document(reply(text=text), reply(text=text))
    assert outcome.status == ai.INVALID_REPLY
    assert problem in outcome.reason
    assert len(provider.requests) == 2 and len(waits) == 1
    assert problem in outcome.attempts[0]["invalid"]


def test_a_valid_second_answer_is_used(waits):
    outcome, _ = judge_document(reply(text="not json"), reply())
    assert (outcome.status, outcome.verdict, outcome.calls) == (ai.ACCEPTED, engine.PASS, 2)


def test_an_unexpected_stop_counts_as_invalid(waits):
    outcome, provider = judge_document(reply(stop=base.OTHER), reply(stop=base.OTHER))
    assert outcome.status == ai.INVALID_REPLY
    assert outcome.reason == "the AI stopped for an unexpected reason (other)"


def test_only_one_retry_is_shared(waits):
    outcome, provider = judge_document(base.TransientError("busy"), reply(text="not json"))
    assert outcome.status == ai.INVALID_REPLY
    assert len(provider.requests) == 2


def test_no_retry_when_the_budget_is_used_up(waits):
    outcome, provider = judge_document(
        reply(text="not json"), settings_=settings(MAX_CALLS_PER_RUN="1")
    )
    assert outcome.status == ai.INVALID_REPLY  # the first attempt's result is kept
    assert len(provider.requests) == 1 and waits == [ai.RETRY_WAIT_SECONDS]


# ------------------------------------------------ 9 to 15: what it is worth ----


def test_unsure():
    outcome, _ = judge_document(
        reply(answer(verdict="UNSURE", reason="The two sections disagree."))
    )
    assert (outcome.status, outcome.verdict) == (ai.UNSURE, engine.NEEDS_REVIEW)
    assert outcome.reason == "the AI could not decide: The two sections disagree."
    assert outcome.model_verdict == "UNSURE"


def test_low_confidence():
    outcome, _ = judge_document(reply(answer(confidence="low")))
    assert (outcome.status, outcome.verdict, outcome.confidence) == (
        ai.LOW_CONFIDENCE,
        engine.NEEDS_REVIEW,
        engine.LOW,
    )
    assert outcome.reason.startswith("the AI said PASS with low confidence: ")


SILENT = answer(
    observed="",
    quote="",
    evidence_found=False,
    verdict="FAIL",
    reason="The policy never states a minimum password length.",
)


def test_a_policy_that_never_states_the_requirement_fails():
    outcome, _ = judge_document(reply(SILENT))
    assert (outcome.status, outcome.verdict, outcome.confidence) == (
        ai.ACCEPTED,
        engine.FAIL,
        engine.HIGH,
    )
    assert outcome.reason.startswith("the policy never states the requirement: ")


@pytest.mark.parametrize(
    "rule, content",
    [
        ({**DOC_RULE, "ai_check": {"expect": "x", "missing_means": "review"}}, SILENT),
        ({**DOC_RULE, "ai_check": {"expect": "x"}}, SILENT),
        (DOC_RULE, {**SILENT, "confidence": "medium"}),
        (DOC_RULE, {**SILENT, "quote": SENTENCE}),
        (DOC_RULE, {**SILENT, "verdict": "PASS"}),
    ],
)
def test_no_evidence_found_is_otherwise_inconsistent(rule, content):
    outcome, _ = judge_document(reply(content), rule=rule)
    assert (outcome.status, outcome.verdict) == (ai.INCONSISTENT, engine.NEEDS_REVIEW)
    assert "found nothing about the setting" in outcome.reason


@pytest.mark.parametrize(
    "quote",
    [
        "Every password must be at least 12 characters long.",  # not what the text says
        "long.",  # in the text, but too short to mean anything
        "",
    ],
)
def test_a_quote_that_is_not_in_the_document(quote):
    outcome, _ = judge_document(reply(answer(quote=quote)))
    assert (outcome.status, outcome.verdict) == (ai.QUOTE_NOT_FOUND, engine.NEEDS_REVIEW)
    assert outcome.reason.endswith("its answer was PASS")


@pytest.mark.parametrize(
    "quote",
    [
        "Every password must be at least 14\ncharacters long.",
        "“Every password must be at least 14 characters long.”"[1:-1],
        "Every pass-\nword must be at least 14 characters long.",
        "  Every password   must be at least 14 characters long.  ",
    ],
)
def test_a_quote_copied_with_different_spacing_or_marks_is_found(quote):
    outcome, _ = judge_document(reply(answer(quote=quote)))
    assert outcome.status == ai.ACCEPTED


def test_quotes_match_ligatures_entities_and_typographic_marks():
    text = "The ﬁrst rule: “Access is removed” &amp; logged — always."
    assert ai.quote_found('The first rule: "Access is removed" & logged - always.', text)
    assert not ai.quote_found("The second rule", text)


def test_a_screenshot_answer_must_name_what_it_saw():
    found, _, _ = evaluator(reply(answer(quote="", observed="Read")))
    outcome = found.screenshot(VISION_RULE, page())
    assert (outcome.status, outcome.verdict) == (ai.INCONSISTENT, engine.NEEDS_REVIEW)
    assert outcome.reason.startswith("the AI said PASS without naming what it saw")


def test_an_accepted_document_answer():
    outcome, provider = judge_document(reply())
    assert (outcome.status, outcome.verdict, outcome.confidence) == (
        ai.ACCEPTED,
        engine.PASS,
        engine.HIGH,
    )
    assert outcome.reason == "The policy requires at least 14 characters, more than 12."
    assert (outcome.quote, outcome.observed, outcome.model_verdict) == (
        SENTENCE,
        "14 characters",
        "PASS",
    )
    assert outcome.method == engine.AI_TEXT
    sent = provider.requests[0]
    assert '<document name="password-policy.pdf" pages="1">' in sent.parts[0].text
    assert "ID: DOC-01" in sent.parts[1].text
    assert sent.system == prompt.system_prompt() and sent.json_mode == "schema"


def test_medium_confidence_is_kept():
    outcome, _ = judge_document(reply(answer(verdict="FAIL", confidence="medium")))
    assert (outcome.status, outcome.verdict, outcome.confidence) == (
        ai.ACCEPTED,
        engine.FAIL,
        engine.MEDIUM,
    )


def test_an_accepted_screenshot_answer():
    found, provider, _ = evaluator(reply(answer(quote="Base permissions: Read", observed="Read")))
    outcome = found.screenshot(VISION_RULE, page())
    assert (outcome.status, outcome.verdict, outcome.method) == (
        ai.ACCEPTED,
        engine.PASS,
        engine.AI_VISION,
    )
    image = provider.requests[0].parts[0]
    assert isinstance(image, base.ImagePart) and image.sha256 == outcome.input.sha256
    assert outcome.evidence == {
        "kind": "screenshot",
        "pixel_sha256": images.pixel_sha256(page()),
        "ai_input_sha256": outcome.input.sha256,
    }


# ------------------------------------------------------- the record and cost ----


def test_the_record_holds_every_attempt_but_no_key_or_pixels(waits):
    found, _, _ = evaluator(reply(text="not json"), reply(answer(quote="Base permissions: Read")))
    outcome = found.screenshot(VISION_RULE, page())
    record = outcome.record()
    text = json.dumps(record)
    assert KEY not in text
    assert outcome.input.png.hex()[:40] not in text
    assert record["status"] == "accepted" and len(record["attempts"]) == 2
    assert record["attempts"][0]["invalid"].startswith("the reply is not JSON")
    assert record["attempts"][1]["request"]["parts"][0] == {
        "type": "image",
        "sha256": outcome.input.sha256,
        "media_type": "image/png",
    }
    assert record["ai_input"]["width"] == outcome.input.width
    assert record["versions"] == {"prompt": "v1", "schema": "v1", "prep": 1, "validation": 1}
    assert record["settings"]["model"] == "gpt-6-luna"
    assert record["usage"] == {
        "calls": 2,
        "input_tokens": 2000,
        "output_tokens": 200,
        "cost_usd": 0.0003,
        "elapsed_ms": 1800,
    }


def test_an_unknown_price_makes_the_cost_unknown():
    unknown = settings(PRICE_INPUT=None, PRICE_OUTPUT=None)
    found, _, _ = evaluator(reply(), settings_=unknown)
    outcome = found.document(DOC_RULE, DOCUMENT)
    assert outcome.status == ai.ACCEPTED and outcome.cost_usd is None
    assert found.totals()["cost_usd"] is None


# --------------------------------------------------------------- the budget ----


def test_the_budget_counts_calls_tokens_and_dollars(waits):
    found, _, _ = evaluator(reply(), base.TransientError("busy"), reply(tokens=(3000, 50)))
    found.document(DOC_RULE, DOCUMENT)
    found.document(DOC_RULE, DOCUMENT)
    assert found.totals() == {
        "calls": 2,
        "cache_hits": 0,
        "input_tokens": 4000,
        "output_tokens": 150,
        "cost_usd": 0.000475,
    }


def test_the_worst_case_of_a_call():
    found, _, _ = evaluator()
    text = prompt.build_request(found.settings, prompt.document_parts(DOC_RULE, DOCUMENT))
    tokens = budget.estimate_input_tokens(text, found.settings.image)
    assert tokens == -(-(len(text.system) + sum(len(p.text) for p in text.parts)) // 3)
    assert found.budget.worst_case(text) == pytest.approx((tokens * 0.10 + 8000 * 0.50) / 1e6)


def test_picture_tokens_by_patches_or_by_pixels():
    picture = images.prepare(page(), ai_settings.ImageLimits(max_edge=2576, max_pixels=5_000_000))
    part = base.ImagePart(picture.png, picture.sha256)
    patches = ai_settings.ImageLimits(max_edge=2576, max_visual_tokens=4784, patch_px=28)
    assert budget.image_tokens(part, patches) == 52 * 33
    pixels = ai_settings.ImageLimits(max_edge=2576, max_pixels=5_000_000)
    assert budget.image_tokens(part, pixels) == 1728  # 1440 x 900 / 750


def test_without_a_price_only_the_call_limit_applies():
    found, _, _ = evaluator(settings_=settings(PRICE_INPUT=None, PRICE_OUTPUT=None))
    request = prompt.build_request(found.settings, prompt.document_parts(DOC_RULE, DOCUMENT))
    assert found.budget.worst_case(request) is None
    assert found.budget.reserve(request) is None


# ----------------------------------------------------------------- compare ----


@pytest.mark.parametrize(
    ("code", "status", "ai_verdict", "comparable", "expected"),
    [
        ("PASS", ai.ACCEPTED, "PASS", True, ai.AGREE),
        ("FAIL", ai.ACCEPTED, "FAIL", True, ai.AGREE),
        ("PASS", ai.ACCEPTED, "FAIL", True, ai.DISAGREE),
        ("PASS", ai.UNSURE, "NEEDS REVIEW", True, ai.AI_ABSTAINED),
        ("PASS", ai.REFUSAL, "NEEDS REVIEW", True, ai.AI_ABSTAINED),
        ("PASS", ai.PROVIDER_ERROR, "NEEDS REVIEW", True, ai.UNAVAILABLE),
        ("NEEDS REVIEW", ai.ACCEPTED, "PASS", True, ai.UNAVAILABLE),
        ("PASS", ai.ACCEPTED, "PASS", False, ai.INCOMPARABLE),
    ],
)
def test_compare(code, status, ai_verdict, comparable, expected):
    outcome = ai.AIOutcome(engine.AI_VISION, status, ai_verdict, "r", engine.HIGH)
    assert ai.compare(code, outcome, comparable) == expected


# ------------------------------------------------------------------ cache ----


def test_the_cache_key_changes_with_anything_that_changes_the_answer():
    s = settings()
    evidence = {"kind": "document", "sha256": "d" * 64}
    key = ai.cache_key(DOC_RULE, evidence, s, False)
    assert key == ai.cache_key(dict(DOC_RULE), dict(evidence), settings(), False)
    changed = [
        ai.cache_key({**DOC_RULE, "title": "other"}, evidence, s, False),
        ai.cache_key({**DOC_RULE, "ai_check": {"expect": "x"}}, evidence, s, False),
        ai.cache_key(DOC_RULE, {**evidence, "sha256": "e" * 64}, s, False),
        ai.cache_key(DOC_RULE, evidence, settings(MODEL="openai/gpt-5.4-nano"), False),
        ai.cache_key(DOC_RULE, evidence, settings(MAX_TOKENS="4000"), False),
        ai.cache_key(DOC_RULE, evidence, s, True),
    ]
    assert key not in changed and len(set(changed)) == len(changed)
    assert KEY not in key


@pytest.fixture
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def saved_result(conn) -> int:
    run_id = db.start_run(conn, "2026-10-11T00:00:00+00:00", db.FULL, "0.4.0", "r.yaml", "c")
    files = {"path": "x", "sha256": "a"}
    result = {
        "id": "DOC-01",
        "verdict": "PASS",
        "method": "ai-text",
        "reason": "r",
        "confidence": "high",
        "collected_at": "now",
    }
    return db.add_result(conn, run_id, result, files, files)


def test_an_accepted_answer_is_reused_for_free(conn):
    cache = ai_cache.Cache(conn)
    first_eval, provider, _ = evaluator(reply(), cache=cache)
    first = first_eval.document(DOC_RULE, DOCUMENT)
    assert cache.store(first, "DOC-01", saved_result(conn))

    again, provider, _ = evaluator(cache=cache)  # no replies queued: a call would fail
    second = again.document(DOC_RULE, DOCUMENT)
    assert (second.status, second.verdict, second.confidence) == (ai.ACCEPTED, engine.PASS, "high")
    assert second.reason == first.reason and second.answer == first.answer
    assert second.from_cache and second.calls == 0 and second.cost_usd == 0.0
    assert second.cache_source["run"] == "run-0001"
    assert second.cache_source["rule_id"] == "DOC-01"
    assert second.cache_source["served_model"] == "gpt-6-luna"
    assert second.attempts == json.loads(json.dumps(first.attempts))
    assert again.totals()["cache_hits"] == 1 and again.totals()["calls"] == 0
    assert provider.requests == []
    assert not cache.store(second, "DOC-01", None)  # a reused answer is not stored again


@pytest.mark.parametrize(
    "content", [answer(verdict="UNSURE"), answer(confidence="low"), answer(quote="nowhere")]
)
def test_only_accepted_answers_are_kept(conn, content):
    cache = ai_cache.Cache(conn)
    found, _, _ = evaluator(reply(content), cache=cache)
    outcome = found.document(DOC_RULE, DOCUMENT)
    assert not cache.store(outcome, "DOC-01", None)
    assert cache.lookup(outcome.cache_key) is None


def test_refresh_asks_again_and_replaces_the_answer(conn):
    cache = ai_cache.Cache(conn)
    old, _, _ = evaluator(reply(), cache=cache)
    cache.store(old.document(DOC_RULE, DOCUMENT), "DOC-01", None)

    fresh, provider, _ = evaluator(reply(answer(verdict="FAIL")), cache=cache, read_cache=False)
    outcome = fresh.document(DOC_RULE, DOCUMENT)
    assert len(provider.requests) == 1 and not outcome.from_cache
    cache.store(outcome, "DOC-01", None)
    hit = cache.lookup(outcome.cache_key)
    assert hit.verdict == engine.FAIL
    assert hit.source["run"] is None and hit.source["rule_id"] == "DOC-01"


def test_the_cache_is_used_even_without_a_key(conn):
    cache = ai_cache.Cache(conn)
    first, _, _ = evaluator(reply(), cache=cache)
    cache.store(first.document(DOC_RULE, DOCUMENT), "DOC-01", None)
    offline, _, made = evaluator(cache=cache, settings_=settings(API_KEY=None))
    assert offline.document(DOC_RULE, DOCUMENT).from_cache
    assert made == []


def test_turned_off_ai_ignores_the_cache(conn):
    cache = ai_cache.Cache(conn)
    first, _, _ = evaluator(reply(), cache=cache)
    cache.store(first.document(DOC_RULE, DOCUMENT), "DOC-01", None)
    off, _, _ = evaluator(cache=cache, enabled=False)
    assert off.document(DOC_RULE, DOCUMENT).status == ai.DISABLED
