"""The neutral contract between the evaluator and the AI providers.

The evaluator builds an AIRequest and gets an AIReply back, whichever company or
local program runs the model. Each adapter (anthropic_api.py, openai_compat.py)
turns these into its SDK's calls and maps the answer back, so nothing outside
providers/ imports an AI SDK.

Every adapter follows the same rules: the key and address come from AISettings
(never from the SDK's own environment lookup), the SDK's retries are off (the
evaluator decides about retrying), each call has a timeout, no tools are sent, and
the full reply is returned for the record.
"""

import base64
from dataclasses import dataclass, field
from typing import Protocol

# Why the model stopped. Each adapter maps its provider's own values to these.
COMPLETE = "complete"
MAX_TOKENS = "max_tokens"  # the answer was cut off
REFUSAL = "refusal"
CONTENT_FILTER = "content_filter"
OTHER = "other"
STOPS = (COMPLETE, MAX_TOKENS, REFUSAL, CONTENT_FILTER, OTHER)


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    png: bytes = field(repr=False)
    sha256: str
    media_type: str = "image/png"

    def base64(self) -> str:
        return base64.standard_b64encode(self.png).decode("ascii")


@dataclass(frozen=True)
class AIRequest:
    """One question to the model: trusted instructions, then the evidence and the rule."""

    system: str
    parts: tuple  # TextPart and ImagePart, in order
    schema: dict  # the JSON schema of the answer
    schema_name: str
    json_mode: str  # "schema": the provider enforces it; "prompt": the prompt asks for it
    max_output_tokens: int
    timeout_s: float
    temperature: float | None = None  # sent only when set
    effort: str | None = None  # Anthropic only
    fallbacks: bool = False  # Anthropic only: let another model answer after a refusal


@dataclass
class AIReply:
    text: str | None
    stop: str  # one of STOPS
    served_model: str | None  # the model that really answered
    input_tokens: int | None
    output_tokens: int | None
    raw: dict = field(repr=False)  # the provider's whole reply, JSON-safe
    request_id: str | None = None
    elapsed_ms: int = 0


class ProviderError(RuntimeError):
    """The provider gave no usable answer. Becomes NEEDS REVIEW with this reason."""

    retryable = False

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TransientError(ProviderError):
    """Worth one more try: a timeout, a dropped connection, rate limiting, a server error."""

    retryable = True


class PermanentError(ProviderError):
    """Trying again won't help: a bad key, no access, an unknown model, a bad request."""


class NotInstalled(ProviderError):
    """The provider's Python package is missing."""


class Provider(Protocol):
    def send(self, request: AIRequest) -> AIReply: ...


def is_transient_status(status: int) -> bool:
    """HTTP statuses worth one more try."""
    return status in (408, 409, 429) or status >= 500


def short(error: Exception, limit: int = 300) -> str:
    """The first line of an error, cut to `limit` characters."""
    lines = str(error).strip().splitlines()
    return (lines[0] if lines else type(error).__name__)[:limit]


def translate(error: Exception, sdk) -> ProviderError:
    """Turn an SDK exception into TransientError or PermanentError.

    `sdk` is the imported package (anthropic or openai); both name their errors alike.
    """
    if isinstance(error, sdk.APITimeoutError):
        return TransientError(f"no answer within the timeout: {short(error)}")
    if isinstance(error, sdk.APIConnectionError):
        return TransientError(f"could not connect: {short(error)}")
    if isinstance(error, sdk.APIStatusError):
        status = error.status_code
        kind = TransientError if is_transient_status(status) else PermanentError
        return kind(f"HTTP {status}: {short(getattr(error, 'message', error))}", status)
    return PermanentError(short(error))
