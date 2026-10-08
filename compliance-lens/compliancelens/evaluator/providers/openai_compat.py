"""OpenAI models, and any service or local program that speaks the OpenAI API.

Uses the `openai` package's Chat Completions call with the address from AISettings:
api.openai.com for openai/, this computer for ollama/ and lmstudio/, and
COMPLIANCELENS_AI_BASE_URL for compatible/. Claude models never come here; they go
through anthropic_api.py.

Local servers need no key, so a placeholder is sent. Passing one also stops the SDK
from looking for OPENAI_API_KEY in the environment by itself.
"""

import time

from compliancelens.evaluator.providers.base import (
    COMPLETE,
    CONTENT_FILTER,
    MAX_TOKENS,
    OTHER,
    REFUSAL,
    AIReply,
    AIRequest,
    ImagePart,
    NotInstalled,
    translate,
)

NO_KEY = "not-needed"
STOPS = {"stop": COMPLETE, "length": MAX_TOKENS, "content_filter": CONTENT_FILTER}


def create(settings, http_client=None):
    return OpenAICompatibleProvider(settings, http_client)


def _content(part) -> dict:
    if isinstance(part, ImagePart):
        url = f"data:{part.media_type};base64,{part.base64()}"
        return {"type": "image_url", "image_url": {"url": url}}
    return {"type": "text", "text": part.text}


class OpenAICompatibleProvider:
    def __init__(self, settings, http_client=None):
        try:
            import openai
        except ImportError:
            raise NotInstalled("the openai package is not installed (run: make setup)")
        self._sdk = openai
        self._model = settings.model
        # OpenAI's newer models want max_completion_tokens; other servers know max_tokens.
        self._token_limit = (
            "max_completion_tokens" if settings.provider == "openai" else "max_tokens"
        )
        options = {
            "api_key": settings.api_key or NO_KEY,
            "base_url": settings.base_url,
            "max_retries": 0,
            "timeout": settings.timeout_s,
        }
        if http_client is not None:
            options["http_client"] = http_client
        self._client = openai.OpenAI(**options)

    def send(self, request: AIRequest) -> AIReply:
        params = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": [_content(p) for p in request.parts]},
            ],
            self._token_limit: request.max_output_tokens,
            "timeout": request.timeout_s,
        }
        if request.json_mode == "schema":
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.schema,
                    "strict": True,
                },
            }
        if request.temperature is not None:
            params["temperature"] = request.temperature

        started = time.monotonic()
        try:
            completion = self._client.chat.completions.create(**params)
        except self._sdk.OpenAIError as e:
            raise translate(e, self._sdk)
        elapsed_ms = round((time.monotonic() - started) * 1000)

        choice = completion.choices[0] if completion.choices else None
        if choice is None:
            text, stop = None, OTHER
        else:
            text = choice.message.content
            stop = REFUSAL if choice.message.refusal else STOPS.get(choice.finish_reason, OTHER)
        usage = completion.usage
        return AIReply(
            text=text or None,
            stop=stop,
            served_model=completion.model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            raw=completion.to_dict(mode="json"),
            request_id=getattr(completion, "_request_id", None),
            elapsed_ms=elapsed_ms,
        )
