"""Which AI model to use, read from .env, and what that model can do.

    COMPLIANCELENS_AI_MODEL=anthropic/claude-opus-5-5     # <provider>/<model name>
    COMPLIANCELENS_AI_API_KEY=...

The provider part picks the adapter: anthropic/ (a bare claude-... name works too),
openai/, ollama/ and lmstudio/ (both run on this computer, no key), or compatible/
(any other service that speaks the OpenAI API; also set COMPLIANCELENS_AI_BASE_URL).
Known models (price, image size, whether they take a temperature) are listed in
models.json; any other model gets cautious defaults. Every value can be overridden
in .env with a COMPLIANCELENS_AI_* line.

Nothing here talks to the network. The API key never appears in AISettings' repr,
in identity() (what gets recorded with each answer) or in describe().
"""

import json
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from urllib.parse import urlsplit

PREFIX = "COMPLIANCELENS_AI_"
DEFAULT_MODEL = "anthropic/claude-opus-5-5"
ANTHROPIC, OPENAI_COMPATIBLE = "anthropic", "openai_compatible"
SCHEMA, PROMPT = "schema", "prompt"  # who enforces the answer's JSON format
EFFORTS = ("low", "medium", "high", "xhigh", "max")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
EXAMPLES = (
    "anthropic/claude-opus-5-5",
    "openai/<model>",
    "ollama/<model>",
    "lmstudio/<model>",
    "compatible/<model> with COMPLIANCELENS_AI_BASE_URL",
)
# A secret pasted into the wrong line, or an Anthropic key about to go elsewhere.
KEY_LIKE = re.compile(r"^(sk-|sk_|ghp_|github_pat_|AKIA)|sk-ant-", re.IGNORECASE)
ANTHROPIC_KEY = re.compile(r"^sk-ant-")

# Cautious limits for models not in models.json: most vision models read this size.
DEFAULT_IMAGE = {"max_edge": 1568, "max_pixels": 1_200_000, "max_bytes": 5_000_000}
DEFAULT_MAX_OUTPUT_TOKENS = 8000
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_CALLS_PER_RUN = 25
DEFAULT_MAX_COST_PER_RUN_USD = 2.00


@dataclass(frozen=True)
class ProviderInfo:
    adapter: str
    base_url: str | None  # None: COMPLIANCELENS_AI_BASE_URL is required
    needs_key: bool
    key_env: str | None = None  # the provider's usual key variable, used as a fallback
    local: bool = False  # runs on this computer: free, nothing leaves the machine
    json_mode: str = PROMPT


ANTHROPIC_URL, OPENAI_URL = "https://api.anthropic.com", "https://api.openai.com/v1"
PROVIDERS = {
    "anthropic": ProviderInfo(
        ANTHROPIC, ANTHROPIC_URL, True, "ANTHROPIC_API_KEY", json_mode=SCHEMA
    ),
    "openai": ProviderInfo(OPENAI_COMPATIBLE, OPENAI_URL, True, "OPENAI_API_KEY", json_mode=SCHEMA),
    "ollama": ProviderInfo(OPENAI_COMPATIBLE, "http://127.0.0.1:11434/v1", False, local=True),
    "lmstudio": ProviderInfo(OPENAI_COMPATIBLE, "http://127.0.0.1:1234/v1", False, local=True),
    "compatible": ProviderInfo(OPENAI_COMPATIBLE, None, False),
}


class AISettingsError(ValueError):
    """The AI settings in .env can't be used (a configuration error, not a verdict)."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class ImageLimits:
    """The largest image the model reads without shrinking it."""

    max_edge: int
    max_visual_tokens: int | None = None  # with patch_px: tokens = ceil(w/patch) * ceil(h/patch)
    patch_px: int | None = None
    max_pixels: int | None = None
    max_bytes: int | None = None

    def describe(self) -> str:
        if self.max_visual_tokens:
            size = f"{self.max_visual_tokens} visual tokens"
        else:
            size = f"{self.max_pixels / 1e6:.1f} MP"
        return f"up to {self.max_edge} px long edge, {size}"


@dataclass(frozen=True)
class AISettings:
    provider: str  # the prefix: anthropic, openai, ollama, lmstudio, compatible
    adapter: str  # anthropic or openai_compatible
    model: str
    base_url: str
    api_key: str | None = field(repr=False)
    key_source: str | None  # which variable the key came from
    needs_key: bool
    local: bool
    known: bool  # listed in models.json
    json_mode: str
    temperature: float | None
    effort: str | None
    fallbacks: bool  # the model supports Anthropic's server-side refusal fallbacks
    max_output_tokens: int
    timeout_s: float
    image: ImageLimits
    price_input: float | None  # $ per million tokens; None = unknown
    price_output: float | None
    price_source: str
    max_calls_per_run: int
    max_cost_per_run: float | None
    warnings: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return f"{self.provider}/{self.model}"

    @property
    def configured(self) -> bool:
        """False when the provider needs a key and none was given."""
        return bool(self.api_key) or not self.needs_key

    @property
    def base_url_host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        """US dollars for one call, or None if the price or the token counts are unknown."""
        if None in (self.price_input, self.price_output, input_tokens, output_tokens):
            return None
        return (input_tokens * self.price_input + output_tokens * self.price_output) / 1_000_000

    def identity(self) -> dict:
        """Everything that can change an answer, for records and cache keys. No key."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url_host": self.base_url_host,
            "json_mode": self.json_mode,
            "temperature": self.temperature,
            "effort": self.effort,
            "max_output_tokens": self.max_output_tokens,
            "image": {
                "max_edge": self.image.max_edge,
                "max_visual_tokens": self.image.max_visual_tokens,
                "patch_px": self.image.patch_px,
                "max_pixels": self.image.max_pixels,
            },
        }

    def describe(self) -> list[str]:
        """What `ai-test` prints about the settings. Never the key itself."""
        if not self.needs_key:
            key = (
                "not needed"
                if self.local
                else (f"set ({self.key_source})" if self.api_key else "none")
            )
        else:
            key = f"set ({self.key_source})" if self.api_key else "NOT SET"
        enforced = (
            "enforced by the provider" if self.json_mode == SCHEMA else "asked for in the prompt"
        )
        answers = [f"JSON {enforced}"]
        if self.effort:
            answers.append(f"effort {self.effort}")
        answers.append(
            f"temperature {self.temperature}" if self.temperature is not None else "no temperature"
        )
        answers.append(f"up to {self.max_output_tokens} output tokens")
        if self.price_input is None:
            price = f"unknown ({self.price_source})"
        else:
            price = (
                f"${self.price_input:.2f} / ${self.price_output:.2f} per million input / output"
                f" tokens ({self.price_source})"
            )
        return [
            f"AI model:  {self.provider} / {self.model}   (key: {key})",
            f"Address:   {self.base_url}",
            f"Answers:   {' · '.join(answers)}",
            f"Images:    {self.image.describe()}",
            f"Price:     {price}",
        ]


# --------------------------------------------------------------- resolving ----


def catalog() -> dict:
    """models.json: the models whose price and limits are known."""
    text = resources.files("compliancelens.evaluator").joinpath("models.json").read_text()
    return json.loads(text)


def parse_model(value: str) -> tuple[str, str]:
    """Split "<provider>/<model>" (or a bare "claude-...") into its parts. Raises ValueError."""
    value = value.strip()
    if KEY_LIKE.search(value):
        raise ValueError(
            f"{PREFIX}MODEL looks like an API key: put the key in {PREFIX}API_KEY instead"
        )
    provider, slash, model = value.partition("/")
    if not slash:
        if value.startswith("claude-"):
            return "anthropic", value
        raise ValueError(f"model {value!r} needs a provider, e.g. {'; '.join(EXAMPLES)}")
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r} (choose from: {', '.join(PROVIDERS)})")
    if not model or len(model) > 200 or any(c.isspace() for c in model):
        raise ValueError(f"model name {model!r} is not valid")
    return provider, model


def url_problem(url: str) -> str | None:
    """Why an AI address may not be used, or None. http:// only for this computer."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as e:
        return f"is not a valid URL ({e})"
    if parts.username or parts.password:
        return "must not contain a user name or password"
    if parts.scheme == "https" and host:
        return None
    if parts.scheme == "http" and host in LOCAL_HOSTS:
        return None
    return f"must start with https:// (http:// only for this computer), got {url!r}"


class _Reader:
    """Reads COMPLIANCELENS_AI_* values and collects every problem, not just the first."""

    def __init__(self, env):
        self.env = env
        self.problems: list[str] = []

    def text(self, name: str) -> str | None:
        return (self.env.get(PREFIX + name) or "").strip() or None

    def number(self, name, kind, low, high, default=None):
        raw = self.text(name)
        if raw is None:
            return default
        try:
            value = kind(raw)
        except ValueError:
            value = None
        if value is None or not low <= value <= high:
            self.problems.append(
                f"{PREFIX}{name} must be a number from {low} to {high}, got {raw!r}"
            )
            return default
        return value


def resolve(env=None, model: str | None = None) -> AISettings:
    """The AI settings from the environment (.env is loaded by the CLI).

    `model` (from --ai-model) replaces COMPLIANCELENS_AI_MODEL for one run.
    Raises AISettingsError listing every problem. A missing key is not an error
    here: AI rules then become NEEDS REVIEW ("AI not configured").
    """
    read = _Reader(os.environ if env is None else env)
    try:
        provider, name = parse_model(model or read.text("MODEL") or DEFAULT_MODEL)
    except ValueError as e:
        raise AISettingsError([str(e)])
    info = PROVIDERS[provider]
    data = catalog()
    known = data["models"].get(f"{provider}/{name}")
    spec = known or {}
    warnings = []

    base_url = read.text("BASE_URL") or info.base_url
    if base_url is None:
        read.problems.append(
            f"{provider}/ models need {PREFIX}BASE_URL (the service's API address)"
        )
        base_url = ""
    elif problem := url_problem(base_url):
        read.problems.append(f"{PREFIX}BASE_URL {problem}")

    api_key, key_source = None, None
    if not info.local:
        for variable in (PREFIX + "API_KEY", info.key_env):
            value = (read.env.get(variable) or "").strip() if variable else ""
            if value:
                api_key, key_source = value, variable
                break
    if api_key and provider != "anthropic" and ANTHROPIC_KEY.match(api_key):
        read.problems.append(
            f"{key_source} holds an Anthropic key, but the model is {provider}/{name}:"
            " put that provider's key there (an Anthropic key is never sent elsewhere)"
        )

    json_mode = read.text("JSON") or spec.get("json") or info.json_mode
    if json_mode not in (SCHEMA, PROMPT):
        read.problems.append(f"{PREFIX}JSON must be {SCHEMA} or {PROMPT}, got {json_mode!r}")
        json_mode = PROMPT

    temperature = read.number("TEMPERATURE", float, 0.0, 2.0)
    if temperature is not None and spec.get("temperature") is False:
        read.problems.append(
            f"{name} does not accept a temperature: remove {PREFIX}TEMPERATURE from .env"
        )

    effort = read.text("EFFORT")
    if effort is not None:
        if info.adapter != ANTHROPIC:
            read.problems.append(f"{PREFIX}EFFORT only works with anthropic/ models")
        elif effort not in EFFORTS:
            read.problems.append(f"{PREFIX}EFFORT must be one of {', '.join(EFFORTS)}")
    else:
        effort = spec.get("effort")

    image = dict(spec.get("image") or DEFAULT_IMAGE)
    max_edge = read.number("IMAGE_MAX_EDGE", int, 200, 8000)
    max_pixels = read.number("IMAGE_MAX_PIXELS", int, 40_000, 50_000_000)
    if max_edge is not None:
        image["max_edge"] = max_edge
    if max_pixels is not None:  # a pixel limit replaces a visual-token limit
        image.update(max_pixels=max_pixels, max_visual_tokens=None, patch_px=None)

    price_input = read.number("PRICE_INPUT", float, 0.0, 1000.0)
    price_output = read.number("PRICE_OUTPUT", float, 0.0, 1000.0)
    if (price_input is None) != (price_output is None):
        read.problems.append(f"set both {PREFIX}PRICE_INPUT and {PREFIX}PRICE_OUTPUT, or neither")
        price_input = price_output = None
    if price_input is not None:
        price_source = f"{PREFIX}PRICE_INPUT/OUTPUT"
    elif known and "price_per_mtok" in known:
        price_input = known["price_per_mtok"]["input"]
        price_output = known["price_per_mtok"]["output"]
        note = f", {known['price_note']}" if known.get("price_note") else ""
        price_source = f"built-in list, checked {data['checked']}{note}"
    elif info.local:
        price_input = price_output = 0.0
        price_source = "runs on this computer: free"
    else:
        price_source = f"not in the built-in list: set {PREFIX}PRICE_INPUT/OUTPUT"
        warnings.append(
            f"the price of {name} is unknown, so the $ limit can't be checked:"
            f" set {PREFIX}PRICE_INPUT and {PREFIX}PRICE_OUTPUT ($ per million tokens)"
        )
    if not known:
        warnings.append(
            f"{provider}/{name} is not in the built-in list: using cautious image limits"
            f" ({image['max_edge']} px); set {PREFIX}IMAGE_MAX_EDGE if it reads larger images"
        )

    max_cost = read.number("MAX_COST_PER_RUN_USD", float, 0.0, 1000.0, DEFAULT_MAX_COST_PER_RUN_USD)
    settings = AISettings(
        provider=provider,
        adapter=info.adapter,
        model=name,
        base_url=base_url,
        api_key=api_key,
        key_source=key_source,
        needs_key=info.needs_key,
        local=info.local,
        known=bool(known),
        json_mode=json_mode,
        temperature=temperature,
        effort=effort,
        fallbacks=bool(spec.get("fallbacks")) and info.adapter == ANTHROPIC,
        max_output_tokens=read.number(
            "MAX_TOKENS",
            int,
            256,
            128_000,
            spec.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS),
        ),
        timeout_s=read.number("TIMEOUT_SECONDS", float, 5.0, 600.0, DEFAULT_TIMEOUT_SECONDS),
        image=ImageLimits(
            max_edge=image["max_edge"],
            max_visual_tokens=image.get("max_visual_tokens"),
            patch_px=image.get("patch_px"),
            max_pixels=image.get("max_pixels"),
            max_bytes=image.get("max_bytes"),
        ),
        price_input=price_input,
        price_output=price_output,
        price_source=price_source,
        max_calls_per_run=read.number(
            "MAX_CALLS_PER_RUN", int, 0, 10_000, DEFAULT_MAX_CALLS_PER_RUN
        ),
        max_cost_per_run=max_cost,
        warnings=tuple(warnings),
    )
    if read.problems:
        raise AISettingsError(read.problems)
    return settings
