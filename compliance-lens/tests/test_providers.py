"""The AI provider adapters, against recorded-style HTTP replies. No real network.

Both adapters get the same contract tests: the neutral reply, the stop reasons, the
errors (and that the SDK never retries by itself), and that the key never leaks.
"""

import json
import sys

import anthropic
import httpx2
import openai
import pytest

from compliancelens.evaluator import prompt, providers
from compliancelens.evaluator import settings as ai
from compliancelens.evaluator.providers import base
from compliancelens.evaluator.providers.anthropic_api import FALLBACK_BETA

KEY = "test-key-not-real-123"
ANSWER = json.dumps(
    {
        "observed": "Read",
        "quote": "Base permissions: Read",
        "evidence_found": True,
        "verdict": "PASS",
        "confidence": "high",
        "reason": "The selected value is Read.",
    }
)
SCHEMA = prompt.answer_schema()
PNG = b"\x89PNG fake image bytes"


def settings_for(model: str, **values) -> ai.AISettings:
    env = {"COMPLIANCELENS_AI_MODEL": model, "COMPLIANCELENS_AI_API_KEY": KEY}
    env.update({f"COMPLIANCELENS_AI_{name}": value for name, value in values.items()})
    return ai.resolve(env)


def request(**changes) -> base.AIRequest:
    fields = {
        "system": "You check one compliance rule.",
        "parts": (base.ImagePart(PNG, "abc123"), base.TextPart("<rule>...</rule>")),
        "schema": SCHEMA,
        "schema_name": prompt.SCHEMA_NAME,
        "json_mode": "schema",
        "max_output_tokens": 8000,
        "timeout_s": 30.0,
    }
    return base.AIRequest(**{**fields, **changes})


# --------------------------------------------------------- fake HTTP replies ----


def claude_reply(text=ANSWER, stop="end_turn", model="claude-opus-5-5"):
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    }


def openai_reply(text=ANSWER, finish="stop", refusal=None, choices=True):
    message = {"role": "assistant", "content": text, "refusal": refusal}
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "some-model-2026-09-01",
        "choices": [{"index": 0, "message": message, "finish_reason": finish, "logprobs": None}]
        if choices
        else [],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60, "total_tokens": 960},
    }


class FakeServer:
    """Answers every request with the next reply; remembers what was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply if isinstance(reply, tuple) else (200, reply)
        return httpx2.Response(
            status, json=body, headers={"request-id": "req_1", "x-request-id": "req_1"}
        )

    @property
    def body(self) -> dict:
        return json.loads(self.requests[-1].content)


ADAPTERS = {
    "anthropic": ("anthropic/claude-opus-5-5", anthropic.DefaultHttpxClient, claude_reply),
    "openai": ("openai/some-model", openai.DefaultHttpxClient, openai_reply),
}


def make(kind: str, *replies, **values):
    model, client_class, _ = ADAPTERS[kind]
    server = FakeServer(*replies)
    client = client_class(transport=httpx2.MockTransport(server.handle))
    provider = providers.get_provider(settings_for(model, **values), http_client=client)
    return provider, server


def error_body(message="something went wrong"):
    return {"type": "error", "error": {"type": "api_error", "message": message}}


# ----------------------------------------------------------- shared contract ----


@pytest.mark.parametrize("kind", ADAPTERS)
def test_a_good_answer(kind):
    provider, server = make(kind, ADAPTERS[kind][2]())
    reply = provider.send(request())
    assert reply.text == ANSWER
    assert reply.stop == base.COMPLETE
    assert reply.served_model in ("claude-opus-5-5", "some-model-2026-09-01")
    assert reply.input_tokens > 0 and reply.output_tokens > 0
    assert reply.request_id == "req_1"
    assert reply.elapsed_ms >= 0
    json.dumps(reply.raw)  # the whole reply can be saved as JSON
    assert KEY not in json.dumps(reply.raw)
    assert len(server.requests) == 1


@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize("status", [408, 409, 429, 500, 503, 529])
def test_temporary_errors_are_transient_and_not_retried_by_the_sdk(kind, status):
    provider, server = make(kind, (status, error_body()))
    with pytest.raises(base.TransientError) as e:
        provider.send(request())
    assert e.value.status_code == status and e.value.retryable
    assert len(server.requests) == 1  # max_retries=0: the evaluator decides about retrying


@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_lasting_errors_are_permanent(kind, status):
    provider, server = make(kind, (status, error_body("bad request")))
    with pytest.raises(base.PermanentError) as e:
        provider.send(request())
    assert e.value.status_code == status and not e.value.retryable
    assert f"HTTP {status}" in str(e.value)
    assert KEY not in str(e.value)
    assert len(server.requests) == 1


@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "error, words",
    [
        (httpx2.ReadTimeout("read timed out"), "no answer within the timeout"),
        (httpx2.ConnectError("connection refused"), "could not connect"),
    ],
)
def test_timeouts_and_connection_problems_are_transient(kind, error, words):
    provider, server = make(kind, error)
    with pytest.raises(base.TransientError, match=words):
        provider.send(request())
    assert len(server.requests) == 1


@pytest.mark.parametrize("kind", ADAPTERS)
def test_the_key_is_sent_only_in_the_auth_header(kind):
    provider, server = make(kind, ADAPTERS[kind][2]())
    provider.send(request())
    sent = server.requests[0]
    assert KEY in (sent.headers.get("x-api-key", "") + sent.headers.get("authorization", ""))
    assert KEY not in sent.content.decode()
    assert "tools" not in server.body


@pytest.mark.parametrize("kind", ADAPTERS)
def test_a_missing_sdk_is_reported(kind, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic" if kind == "anthropic" else "openai", None)
    with pytest.raises(base.NotInstalled, match="not installed"):
        providers.get_provider(settings_for(ADAPTERS[kind][0]))


# ------------------------------------------------------------------ Claude ----


def test_claude_request_shape():
    provider, server = make("anthropic", claude_reply())
    provider.send(request(effort="medium"))
    sent = server.body
    assert server.requests[0].url.path == "/v1/messages"
    assert (sent["model"], sent["max_tokens"]) == ("claude-opus-5-5", 8000)
    assert sent["system"] == "You check one compliance rule."
    [message] = sent["messages"]
    image, text = message["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert image["source"]["data"] == base.ImagePart(PNG, "x").base64()
    assert text == {"type": "text", "text": "<rule>...</rule>"}
    assert sent["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "medium",
    }
    assert "temperature" not in sent and "fallbacks" not in sent


def test_claude_prompt_mode_sends_no_schema_and_temperature_only_when_set():
    provider, server = make("anthropic", claude_reply(), claude_reply())
    provider.send(request(json_mode="prompt"))
    assert "output_config" not in server.body
    provider.send(request(temperature=0.0))
    assert server.body["temperature"] == 0.0


def test_claude_fallbacks_use_the_beta_endpoint():
    provider, server = make("anthropic", claude_reply(model="claude-opus-5"))
    reply = provider.send(request(fallbacks=True))
    sent = server.requests[0]
    assert sent.url.params.get("beta") == "true"
    assert FALLBACK_BETA in sent.headers["anthropic-beta"]
    assert server.body["fallbacks"] == "default"
    assert reply.served_model == "claude-opus-5"  # another model answered


@pytest.mark.parametrize(
    "stop, expected",
    [
        ("end_turn", base.COMPLETE),
        ("max_tokens", base.MAX_TOKENS),
        ("model_context_window_exceeded", base.MAX_TOKENS),
        ("refusal", base.REFUSAL),
        ("tool_use", base.OTHER),
    ],
)
def test_claude_stop_reasons(stop, expected):
    provider, _ = make("anthropic", claude_reply(stop=stop))
    assert provider.send(request()).stop == expected


def test_claude_reply_without_text():
    provider, _ = make("anthropic", claude_reply(text=None, stop="refusal"))
    reply = provider.send(request())
    assert reply.text is None and reply.stop == base.REFUSAL


# ------------------------------------------------------ OpenAI-compatible ----


def test_openai_request_shape():
    provider, server = make("openai", openai_reply())
    provider.send(request())
    sent = server.body
    assert server.requests[0].url.path == "/v1/chat/completions"
    assert str(server.requests[0].url).startswith("https://api.openai.com/v1/")
    system, user = sent["messages"]
    assert system == {"role": "system", "content": "You check one compliance rule."}
    image, text = user["content"]
    assert image["type"] == "image_url"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    assert text == {"type": "text", "text": "<rule>...</rule>"}
    assert sent["max_completion_tokens"] == 8000 and "max_tokens" not in sent
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": prompt.SCHEMA_NAME, "schema": SCHEMA, "strict": True},
    }
    assert "temperature" not in sent


def test_local_servers_get_max_tokens_a_placeholder_key_and_their_address():
    model, client_class, _ = ADAPTERS["openai"]
    server = FakeServer(openai_reply())
    client = client_class(transport=httpx2.MockTransport(server.handle))
    settings = ai.resolve(
        {"COMPLIANCELENS_AI_MODEL": "ollama/llava", "COMPLIANCELENS_AI_TEMPERATURE": "0"}
    )
    providers.get_provider(settings, http_client=client).send(
        request(json_mode="prompt", temperature=0.0)
    )
    sent = server.requests[0]
    assert str(sent.url) == "http://127.0.0.1:11434/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer not-needed"
    body = json.loads(sent.content)
    assert body["max_tokens"] == 8000 and "max_completion_tokens" not in body
    assert body["temperature"] == 0.0 and "response_format" not in body


@pytest.mark.parametrize(
    "reply, expected",
    [
        (openai_reply(finish="length"), base.MAX_TOKENS),
        (openai_reply(finish="content_filter"), base.CONTENT_FILTER),
        (openai_reply(text=None, refusal="I can't help with that."), base.REFUSAL),
        (openai_reply(finish="tool_calls"), base.OTHER),
        (openai_reply(choices=False), base.OTHER),
    ],
)
def test_openai_stop_reasons(reply, expected):
    provider, _ = make("openai", reply)
    assert provider.send(request()).stop == expected


# ------------------------------------------------------------------ helpers ----


def test_get_provider_picks_the_adapter():
    claude = providers.get_provider(settings_for("anthropic/claude-opus-5-5"))
    other = providers.get_provider(settings_for("openai/m"))
    assert type(claude).__name__ == "AnthropicProvider"
    assert type(other).__name__ == "OpenAICompatibleProvider"


def test_translate_unknown_errors_as_permanent():
    error = base.translate(anthropic.AnthropicError("odd\nsecond line"), anthropic)
    assert isinstance(error, base.PermanentError) and str(error) == "odd"


def test_short_error_text():
    assert base.short(ValueError("")) == "ValueError"
    assert len(base.short(ValueError("x" * 1000))) == 300
