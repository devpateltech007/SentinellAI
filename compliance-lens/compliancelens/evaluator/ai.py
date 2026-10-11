"""The AI checks (V4): ask the model about one document or screenshot, then decide
what its answer is worth.

The first row that applies decides. Only `accepted` gives PASS or FAIL; every other
status is NEEDS REVIEW with its reason. Rows marked * share one retry per evaluation.

     1  no evidence (document not read, screenshot not taken)   evidence_missing
        a screenshot too big to send at a readable size          image_too_big
     2  --no-ai / no key / budget used / SDK missing             disabled, not_configured,
                                                                 budget_exhausted, not_installed
     3* timeout, dropped connection (3 more tries), 429, 5xx      provider_error
     4  bad key, unknown model, bad request, no credit           provider_error
     5  the model refused, or a content filter stopped it        refusal
     6  the answer was cut off                                   truncated
     7* not exactly the answer's JSON (see answer.py)            invalid_reply
     8* reason, quote or observed too short or too long          invalid_reply
     9  the model answered UNSURE                                unsure
    10  low confidence                                           low_confidence
    11  a document that never states the requirement, with       accepted (FAIL)
        missing_means: fail, a FAIL with no evidence found and
        no quote, high confidence
    12  PASS or FAIL, but the model found no evidence             inconsistent
    13  a document's PASS or FAIL whose quote isn't in the text  quote_not_found
    14  a screenshot's PASS or FAIL with no quote                inconsistent
    15  otherwise                                                accepted

Accepted answers are kept in the cache and reused for the same evidence, rule,
model and prompt (see cache.py). Every attempt is kept for the evidence file.
"""

import datetime
import hashlib
import html
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

from compliancelens import engine
from compliancelens.connectors import files
from compliancelens.evaluator import answer, images, prompt, providers
from compliancelens.evaluator.budget import Budget
from compliancelens.evaluator.providers import base

# Changes whenever the rules above change (it is part of the cache key).
VALIDATION_VERSION = 1
CACHE_VERSION = 1
RETRY_WAIT_SECONDS = 2
# Extra tries for a dropped connection, before the shared retry: pictures are large
# uploads, and on one network 10-40% of them broke mid-way (nothing reached the model).
CONNECTION_RETRIES = 3
MIN_QUOTE_CHARS = 8  # a shorter "quote" can be found almost anywhere

ACCEPTED = "accepted"
EVIDENCE_MISSING = "evidence_missing"
IMAGE_TOO_BIG = "image_too_big"
DISABLED = "disabled"
NOT_CONFIGURED = "not_configured"
BUDGET_EXHAUSTED = "budget_exhausted"
NOT_INSTALLED = "not_installed"
PROVIDER_ERROR = "provider_error"
REFUSAL = "refusal"
TRUNCATED = "truncated"
INVALID_REPLY = "invalid_reply"
UNSURE = "unsure"
LOW_CONFIDENCE = "low_confidence"
INCONSISTENT = "inconsistent"
QUOTE_NOT_FOUND = "quote_not_found"
ERROR = "error"  # a bug in the AI check itself; the audit goes on
STATUSES = (
    ACCEPTED,
    EVIDENCE_MISSING,
    IMAGE_TOO_BIG,
    DISABLED,
    NOT_CONFIGURED,
    BUDGET_EXHAUSTED,
    NOT_INSTALLED,
    PROVIDER_ERROR,
    REFUSAL,
    TRUNCATED,
    INVALID_REPLY,
    UNSURE,
    LOW_CONFIDENCE,
    INCONSISTENT,
    QUOTE_NOT_FOUND,
    ERROR,
)
# The model gave an answer, but it was not good enough to use (for cross-checks).
ABSTAINED = (REFUSAL, UNSURE, LOW_CONFIDENCE, INCONSISTENT, QUOTE_NOT_FOUND)

DOCUMENT, SCREENSHOT = "document", "screenshot"
AGREE, DISAGREE, AI_ABSTAINED, UNAVAILABLE, INCOMPARABLE = (
    "agree",
    "disagree",
    "ai_abstained",
    "unavailable",
    "incomparable",
)

# Typographic quotes and dashes a model may write instead of the document's own.
_PUNCTUATION = str.maketrans(
    dict.fromkeys("\u2018\u2019\u201a\u201b\u2032", "'")
    | dict.fromkeys("\u201c\u201d\u201e\u201f\u2033", '"')
    | dict.fromkeys("\u2010\u2011\u2012\u2013\u2014", "-")
    | {"\u00a0": " "}
)


_sleep = time.sleep  # tests replace this so they never really wait


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


# ----------------------------------------------------------------- quotes ----


def normalize(text: str) -> str:
    """Text as compared for quotes: entities, ligatures, quote marks, broken words, spaces."""
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(_PUNCTUATION)
    text = re.sub(r"(\w)-[ \t]*\n\s*(\w)", r"\1\2", text)  # "pass-\nword" -> "password"
    return re.sub(r"\s+", " ", text).strip()


def quote_found(quote: str, text: str) -> bool:
    """The quote, after normalize(), is in the text and long enough to mean something."""
    wanted = normalize(quote)
    return len(wanted) >= MIN_QUOTE_CHARS and wanted in normalize(text)


def document_text(document: dict) -> str:
    return "\n".join(page["text"] for page in document["pages"])


# ---------------------------------------------------------------- outcome ----


@dataclass
class AIOutcome:
    """What the AI check decided, and everything needed to explain and repeat it."""

    method: str  # ai-text or ai-vision
    status: str
    verdict: str  # what the rule gets: PASS, FAIL or NEEDS REVIEW
    reason: str
    confidence: str  # the result's confidence: the model's when accepted, else low
    answer: dict | None = None  # the model's last valid answer
    attempts: list = field(default_factory=list)
    settings: dict | None = None
    evidence: dict = field(default_factory=dict)  # hashes of what was judged
    input: images.Prepared | None = None  # the picture that was sent
    cache_key: str | None = None
    from_cache: bool = False
    cache_source: dict | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0  # None: a price was unknown
    elapsed_ms: int = 0

    @property
    def model_verdict(self) -> str | None:
        return (self.answer or {}).get("verdict")

    @property
    def quote(self) -> str | None:
        return (self.answer or {}).get("quote")

    @property
    def observed(self) -> str | None:
        return (self.answer or {}).get("observed")

    def record(self) -> dict:
        """The <ID>.ai.json evidence: the decision and every attempt. No key, no pixels."""
        return {
            "method": self.method,
            "status": self.status,
            "verdict": self.verdict,
            "reason": self.reason,
            "confidence": self.confidence,
            "answer": self.answer,
            "settings": self.settings,
            "versions": versions(),
            "evidence": self.evidence,
            "ai_input": self.input.describe() if self.input else None,
            "cache_key": self.cache_key,
            "from_cache": self.from_cache,
            "cache_source": self.cache_source,
            "usage": {
                "calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd,
                "elapsed_ms": self.elapsed_ms,
            },
            "attempts": self.attempts,
        }


def versions() -> dict:
    return {
        "prompt": prompt.PROMPT_VERSION,
        "schema": prompt.PROMPT_VERSION,
        "prep": images.PREP_VERSION,
        "validation": VALIDATION_VERSION,
    }


def cache_key(rule: dict, evidence: dict, settings, fallbacks: bool) -> str:
    """SHA-256 of everything that can change the answer (never the key)."""
    material = {
        "cache_version": CACHE_VERSION,
        "versions": versions(),
        "rule": {k: rule.get(k) for k in ("id", "title", "ai_check")},
        "settings": settings.identity(),
        "fallbacks": fallbacks,
        "evidence": evidence,
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare(code_verdict: str, outcome: AIOutcome, comparable: bool = True) -> str:
    """A cross-check: does the AI's reading of the screenshot agree with the code?"""
    if not comparable:
        return INCOMPARABLE
    if outcome.status in ABSTAINED:
        return AI_ABSTAINED
    if outcome.status != ACCEPTED or code_verdict not in (engine.PASS, engine.FAIL):
        return UNAVAILABLE
    return AGREE if outcome.verdict == code_verdict else DISAGREE


# -------------------------------------------------------------- evaluator ----


@dataclass
class _Reading:
    """What one attempt amounts to."""

    status: str
    reason: str
    verdict: str = engine.NEEDS_REVIEW
    confidence: str = engine.LOW
    answer: dict | None = None
    retry: bool = False
    dropped: bool = False  # the connection broke: nothing came back


class Evaluator:
    """The AI checks of one audit run: the settings, the provider (created on first use),
    the budget and the cache.

    `enabled=False` is `run --no-ai` (then `settings` may be None). `cache` is a
    cache.Cache or None; `read_cache=False` is `--refresh-ai`. `fallbacks` lets Claude
    answer a refusal with another model (audits); the research experiment turns it off.
    """

    def __init__(
        self,
        settings,
        *,
        enabled: bool = True,
        cache=None,
        read_cache: bool = True,
        fallbacks: bool = True,
        make_provider=None,
    ):
        if settings is None and enabled:
            raise ValueError("AI settings are needed unless the AI checks are turned off")
        self.settings = settings
        self.enabled = enabled
        self.cache = cache
        self.read_cache = read_cache
        self.fallbacks = fallbacks
        self.budget = Budget(settings) if settings is not None else None
        self._make_provider = make_provider or providers.get_provider
        self._provider = None
        self._not_installed: str | None = None

    # ------------------------------------------------------------ entry points

    def document(self, rule: dict, document: dict) -> AIOutcome:
        """DOC rules: judge the text of a document read by files.read_document."""
        outcome = self._outcome(engine.AI_TEXT)
        if document.get("status") != files.OK:
            why = document.get("reason") or document.get("status") or "not read"
            return self._finish(outcome, EVIDENCE_MISSING, f"the document was not read: {why}")
        outcome.evidence = {
            "kind": DOCUMENT,
            "sha256": document["sha256"],
            "extractor": document.get("extractor"),
            "extract_version": document.get("extract_version"),
        }
        named = {"name": document.get("path", "document"), "pages": document["pages"]}
        parts = prompt.document_parts(rule, named)
        return self._ask(rule, outcome, parts, document=document)

    def screenshot(self, rule: dict, page, missing: str | None = None) -> AIOutcome:
        """Vision rules and cross-checks: judge the page's pixels (images.from_capture or
        images.from_saved). `page` is None when no screenshot was taken, with the reason."""
        outcome = self._outcome(engine.AI_VISION)
        if page is None:
            why = missing or "no screenshot was taken"
            return self._finish(outcome, EVIDENCE_MISSING, f"no screenshot to judge: {why}")
        if not self.enabled:
            return self._finish(outcome, DISABLED, "AI checks are turned off (--no-ai)")
        try:
            prepared = images.prepare(page, self.settings.image)
        except images.Unusable as e:
            outcome.evidence = {"kind": SCREENSHOT, "pixel_sha256": images.pixel_sha256(page)}
            return self._finish(outcome, IMAGE_TOO_BIG, str(e))
        outcome.input = prepared
        outcome.evidence = {
            "kind": SCREENSHOT,
            "pixel_sha256": prepared.pixel_sha256,
            "ai_input_sha256": prepared.sha256,
        }
        parts = prompt.image_parts(rule, base.ImagePart(prepared.png, prepared.sha256))
        return self._ask(rule, outcome, parts)

    def totals(self) -> dict:
        if self.budget is None:
            return {
                "calls": 0,
                "cache_hits": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
        return self.budget.totals()

    # ----------------------------------------------------------------- asking

    def _outcome(self, method: str) -> AIOutcome:
        return AIOutcome(
            method=method,
            status=DISABLED,
            verdict=engine.NEEDS_REVIEW,
            reason="",
            confidence=engine.LOW,
            settings=self.settings.identity() if self.settings is not None else None,
        )

    @staticmethod
    def _finish(outcome: AIOutcome, status: str, reason: str) -> AIOutcome:
        outcome.status, outcome.reason = status, reason
        return outcome

    def _provider_or_none(self):
        if self._provider is None and self._not_installed is None:
            try:
                self._provider = self._make_provider(self.settings)
            except base.NotInstalled as e:
                self._not_installed = str(e)
        return self._provider

    def _ask(self, rule: dict, outcome: AIOutcome, parts: tuple, document=None) -> AIOutcome:
        if not self.enabled:
            return self._finish(outcome, DISABLED, "AI checks are turned off (--no-ai)")
        fallbacks = self.fallbacks and self.settings.fallbacks
        outcome.cache_key = cache_key(rule, outcome.evidence, self.settings, fallbacks)
        if self.cache is not None and self.read_cache:
            hit = self.cache.lookup(outcome.cache_key)
            if hit is not None:
                return self._from_cache(outcome, hit)
        if not self.settings.configured:
            reason = f"AI not configured: add COMPLIANCELENS_AI_API_KEY for {self.settings.name}"
            return self._finish(outcome, NOT_CONFIGURED, reason + " to .env")
        provider = self._provider_or_none()
        if provider is None:
            return self._finish(outcome, NOT_INSTALLED, self._not_installed)

        request = prompt.build_request(self.settings, parts, fallbacks=self.fallbacks)
        reading, shared, dropped = None, 1, CONNECTION_RETRIES  # retries left
        while True:
            if reading is not None:
                if reading.dropped and dropped:
                    dropped -= 1
                elif reading.retry and shared:
                    shared -= 1
                else:
                    break
                _sleep(RETRY_WAIT_SECONDS)
            problem = self.budget.reserve(request)
            if problem:
                if reading is None:
                    return self._finish(outcome, BUDGET_EXHAUSTED, f"AI budget used up: {problem}")
                break  # keep the last attempt's result
            number = len(outcome.attempts) + 1
            reading = self._attempt(rule, outcome, provider, request, number, document)
        outcome.status, outcome.reason = reading.status, reading.reason
        outcome.verdict, outcome.confidence = reading.verdict, reading.confidence
        outcome.answer = reading.answer
        return outcome

    def _attempt(self, rule, outcome, provider, request, number, document) -> _Reading:
        record = {"attempt": number, "sent_at": _now(), "request": _describe(request)}
        outcome.attempts.append(record)
        try:
            reply = provider.send(request)
        except base.ProviderError as e:
            record["error"] = {"kind": type(e).__name__, "message": str(e)}
            if e.status_code is not None:
                record["error"]["status_code"] = e.status_code
            dropped = isinstance(e, base.DroppedConnection)
            reason = f"AI provider error: {e}"
            return _Reading(PROVIDER_ERROR, reason, retry=e.retryable, dropped=dropped)
        except Exception as e:  # a bug in an adapter must not stop the audit
            record["error"] = {"kind": type(e).__name__, "message": base.short(e)}
            return _Reading(PROVIDER_ERROR, f"AI provider error: {base.short(e)}")

        cost = self.budget.charge(reply.input_tokens, reply.output_tokens)
        outcome.calls += 1
        outcome.input_tokens += reply.input_tokens or 0
        outcome.output_tokens += reply.output_tokens or 0
        outcome.elapsed_ms += reply.elapsed_ms
        if cost is None or outcome.cost_usd is None:
            outcome.cost_usd = None
        else:
            outcome.cost_usd = round(outcome.cost_usd + cost, 6)
        record.update(
            stop=reply.stop,
            text=reply.text,
            served_model=reply.served_model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=cost,
            elapsed_ms=reply.elapsed_ms,
            request_id=reply.request_id,
            raw=reply.raw,
        )

        if reply.stop in (base.REFUSAL, base.CONTENT_FILTER):
            return _Reading(REFUSAL, f"the AI declined to answer ({reply.stop})")
        if reply.stop == base.MAX_TOKENS:
            return _Reading(TRUNCATED, "the AI's answer was cut off (output token limit)")
        if reply.stop != base.COMPLETE:
            reason = f"the AI stopped for an unexpected reason ({reply.stop})"
            return _Reading(INVALID_REPLY, reason, retry=True)
        try:
            parsed = answer.parse_answer(reply.text, request.schema)
        except answer.AnswerError as e:
            record["invalid"] = str(e)
            return _Reading(
                INVALID_REPLY, f"the AI's reply was not a valid answer: {e}", retry=True
            )
        record["answer"] = parsed
        return _judge(rule, parsed, document)

    def _from_cache(self, outcome: AIOutcome, hit) -> AIOutcome:
        self.budget.cache_hits += 1
        outcome.from_cache = True
        outcome.cache_source = hit.source
        outcome.answer = hit.answer
        outcome.attempts = hit.attempts
        outcome.status = ACCEPTED
        outcome.verdict, outcome.confidence, outcome.reason = (
            hit.verdict,
            hit.confidence,
            hit.reason,
        )
        return outcome


def _describe(request) -> dict:
    """What was sent, for the record: the text itself, pictures by hash (no pixels, no key)."""
    parts = []
    for part in request.parts:
        if isinstance(part, base.ImagePart):
            parts.append({"type": "image", "sha256": part.sha256, "media_type": part.media_type})
        else:
            parts.append({"type": "text", "text": part.text})
    return {
        "system_sha256": hashlib.sha256(request.system.encode("utf-8")).hexdigest(),
        "json_mode": request.json_mode,
        "max_output_tokens": request.max_output_tokens,
        "fallbacks": request.fallbacks,
        "parts": parts,
    }


def _judge(rule: dict, parsed: dict, document: dict | None) -> _Reading:
    """Rows 9 to 15: what a well-formed answer is worth."""
    said, confidence, reason = parsed["verdict"], parsed["confidence"], parsed["reason"].strip()
    if said == "UNSURE":
        return _Reading(UNSURE, f"the AI could not decide: {reason}", answer=parsed)
    if confidence == engine.LOW:
        reason = f"the AI said {said} with low confidence: {reason}"
        return _Reading(LOW_CONFIDENCE, reason, answer=parsed)
    quote = parsed["quote"].strip()
    if (
        document is not None
        and (rule.get("ai_check") or {}).get("missing_means") == "fail"
        and said == engine.FAIL
        and not parsed["evidence_found"]
        and not quote
        and confidence == engine.HIGH
    ):
        reason = f"the policy never states the requirement: {reason}"
        return _Reading(ACCEPTED, reason, engine.FAIL, engine.HIGH, parsed)
    if not parsed["evidence_found"]:
        reason = f"the AI said {said} but found nothing about the setting: {reason}"
        return _Reading(INCONSISTENT, reason, answer=parsed)
    if document is not None and not quote_found(quote, document_text(document)):
        reason = f"the AI's quote is not in the document ({quote[:120]!r}); its answer was {said}"
        return _Reading(QUOTE_NOT_FOUND, reason, answer=parsed)
    if document is None and not quote:
        reason = f"the AI said {said} without naming what it saw: {reason}"
        return _Reading(INCONSISTENT, reason, answer=parsed)
    return _Reading(ACCEPTED, reason, said, confidence, parsed)
