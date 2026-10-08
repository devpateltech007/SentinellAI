"""Claude models, through Anthropic's own SDK (the `anthropic` package).

The answer format is enforced with structured outputs (`output_config.format`), and
`output_config.effort` sets how much the model thinks. Current Claude models reject
a temperature, so one is sent only when the settings allow it (older models).

In audits, a refusal by Claude's safety filters can be answered by another Claude
model (server-side fallbacks, a beta feature); the reply then names the model that
really answered. The research experiment turns this off so one model answers everything.
"""

import time

from compliancelens.evaluator.providers.base import (
    COMPLETE,
    MAX_TOKENS,
    OTHER,
    REFUSAL,
    AIReply,
    AIRequest,
    ImagePart,
    NotInstalled,
    translate,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
STOPS = {
    "end_turn": COMPLETE,
    "max_tokens": MAX_TOKENS,
    "model_context_window_exceeded": MAX_TOKENS,
    "refusal": REFUSAL,
}


def create(settings, http_client=None):
    return AnthropicProvider(settings, http_client)


def _block(part) -> dict:
    if isinstance(part, ImagePart):
        source = {"type": "base64", "media_type": part.media_type, "data": part.base64()}
        return {"type": "image", "source": source}
    return {"type": "text", "text": part.text}


class AnthropicProvider:
    def __init__(self, settings, http_client=None):
        try:
            import anthropic
        except ImportError:
            raise NotInstalled("the anthropic package is not installed (run: make setup)")
        self._sdk = anthropic
        self._model = settings.model
        # An explicit key means the SDK reads no credentials from the environment.
        options = {
            "api_key": settings.api_key,
            "base_url": settings.base_url,
            "max_retries": 0,
            "timeout": settings.timeout_s,
        }
        if http_client is not None:
            options["http_client"] = http_client
        self._client = anthropic.Anthropic(**options)

    def send(self, request: AIRequest) -> AIReply:
        params = {
            "model": self._model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": [_block(p) for p in request.parts]}],
            "timeout": request.timeout_s,
        }
        output_config = {}
        if request.json_mode == "schema":
            output_config["format"] = {"type": "json_schema", "schema": request.schema}
        if request.effort:
            output_config["effort"] = request.effort
        if output_config:
            params["output_config"] = output_config
        if request.temperature is not None:  # not a named SDK parameter any more
            params["extra_body"] = {"temperature": request.temperature}

        started = time.monotonic()
        try:
            if request.fallbacks:
                message = self._client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                message = self._client.messages.create(**params)
        except self._sdk.AnthropicError as e:
            raise translate(e, self._sdk)
        elapsed_ms = round((time.monotonic() - started) * 1000)

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return AIReply(
            text=text or None,
            stop=STOPS.get(message.stop_reason, OTHER),
            served_model=message.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            raw=message.to_dict(mode="json"),
            request_id=getattr(message, "_request_id", None),
            elapsed_ms=elapsed_ms,
        )
