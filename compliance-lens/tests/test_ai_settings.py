"""Choosing the AI model in .env: COMPLIANCELENS_AI_MODEL=<provider>/<model> + a key."""

import pytest

from compliancelens.evaluator import settings as ai

KEY = "test-key-123"


def resolve(model=None, **values):
    env = {f"COMPLIANCELENS_AI_{name}": value for name, value in values.items()}
    return ai.resolve(env, model=model)


def problems(**values) -> list[str]:
    with pytest.raises(ai.AISettingsError) as e:
        resolve(**values)
    return e.value.problems


# ------------------------------------------------------------ which model ----


def test_default_is_claude_opus():
    s = resolve(API_KEY=KEY)
    assert (s.provider, s.model, s.adapter) == ("anthropic", "claude-opus-5-5", ai.ANTHROPIC)
    assert s.base_url == "https://api.anthropic.com"
    assert s.name == "anthropic/claude-opus-5-5"


def test_a_bare_claude_name_means_anthropic():
    s = resolve(MODEL="claude-haiku-5-5", API_KEY=KEY)
    assert (s.provider, s.model) == ("anthropic", "claude-haiku-5-5")


@pytest.mark.parametrize(
    "value, provider, adapter, base_url",
    [
        ("openai/some-model", "openai", ai.OPENAI_COMPATIBLE, "https://api.openai.com/v1"),
        ("ollama/llava:13b", "ollama", ai.OPENAI_COMPATIBLE, "http://127.0.0.1:11434/v1"),
        ("lmstudio/qwen-vl", "lmstudio", ai.OPENAI_COMPATIBLE, "http://127.0.0.1:1234/v1"),
        ("OpenAI/some-model", "openai", ai.OPENAI_COMPATIBLE, "https://api.openai.com/v1"),
    ],
)
def test_the_prefix_picks_the_adapter_and_address(value, provider, adapter, base_url):
    s = resolve(MODEL=value, API_KEY=KEY)
    assert (s.provider, s.adapter, s.base_url) == (provider, adapter, base_url)


def test_model_names_may_contain_slashes():
    s = resolve(MODEL="compatible/meta/llama-vision", BASE_URL="https://api.example.com/v1")
    assert (s.provider, s.model) == ("compatible", "meta/llama-vision")


@pytest.mark.parametrize(
    "value, message",
    [
        ("gpt-like-model", "needs a provider"),
        ("acme/model", "unknown provider 'acme'"),
        ("openai/", "is not valid"),
        ("openai/two words", "is not valid"),
        ("sk-ant-api03-abcdef", "looks like an API key"),
    ],
)
def test_bad_model_names_are_refused(value, message):
    [problem] = problems(MODEL=value)
    assert message in problem


def test_the_command_line_model_wins_for_one_run():
    s = resolve(model="ollama/llava", MODEL="anthropic/claude-opus-5-5")
    assert s.name == "ollama/llava"


# -------------------------------------------------------------------- keys ----


def test_the_key_comes_from_compliancelens_ai_api_key_first():
    env = {"COMPLIANCELENS_AI_API_KEY": "first", "ANTHROPIC_API_KEY": "second"}
    s = ai.resolve(env)
    assert (s.api_key, s.key_source) == ("first", "COMPLIANCELENS_AI_API_KEY")


@pytest.mark.parametrize(
    "model, variable",
    [("anthropic/claude-opus-5-5", "ANTHROPIC_API_KEY"), ("openai/m", "OPENAI_API_KEY")],
)
def test_the_providers_usual_variable_is_the_fallback(model, variable):
    s = ai.resolve({"COMPLIANCELENS_AI_MODEL": model, variable: "usual"})
    assert (s.api_key, s.key_source, s.configured) == ("usual", variable, True)


def test_no_key_is_not_an_error_but_not_configured():
    s = resolve()
    assert s.api_key is None and not s.configured


def test_local_models_need_no_key_and_never_get_one():
    s = resolve(MODEL="ollama/llava", API_KEY="some-key")
    assert s.api_key is None and s.configured and s.local


def test_an_anthropic_key_is_never_sent_to_another_provider():
    [problem] = problems(MODEL="openai/m", API_KEY="sk-ant-api03-secret")
    assert "Anthropic key" in problem
    assert "secret" not in problem  # the key itself is never repeated


def test_the_key_is_never_shown():
    s = resolve(API_KEY="sk-ant-api03-verysecret")
    assert "verysecret" not in repr(s)
    assert "verysecret" not in str(s.identity())
    assert "verysecret" not in "\n".join(s.describe())
    assert "set (COMPLIANCELENS_AI_API_KEY)" in s.describe()[0]


# --------------------------------------------------------------- addresses ----


def test_compatible_needs_an_address():
    [problem] = problems(MODEL="compatible/m")
    assert "BASE_URL" in problem


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://api.example.com/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://localhost:8000/v1", True),
        ("http://api.example.com/v1", False),
        ("https://user:pass@api.example.com", False),
        ("ftp://api.example.com", False),
        ("https://[::1", False),
    ],
)
def test_addresses_must_be_https_unless_local(url, ok):
    if ok:
        assert resolve(MODEL="compatible/m", BASE_URL=url).base_url == url
    else:
        assert "BASE_URL" in problems(MODEL="compatible/m", BASE_URL=url)[0]


def test_the_address_can_be_overridden():
    s = resolve(MODEL="ollama/llava", BASE_URL="http://127.0.0.1:9999/v1")
    assert s.base_url == "http://127.0.0.1:9999/v1" and s.base_url_host == "127.0.0.1"


# ----------------------------------------------------- what the model can do ----


def test_known_claude_models_come_from_the_built_in_list():
    s = resolve(API_KEY=KEY)
    assert s.known and s.json_mode == ai.SCHEMA and s.effort == "medium" and s.fallbacks
    assert (s.price_input, s.price_output) == (4.0, 20.0)
    assert "built-in list" in s.price_source
    assert (s.image.max_edge, s.image.max_visual_tokens, s.image.patch_px) == (2576, 4784, 28)
    assert s.warnings == ()


def test_haiku_has_no_fallbacks_and_a_price_note():
    s = resolve(MODEL="anthropic/claude-haiku-5-5", API_KEY=KEY)
    assert not s.fallbacks
    assert "100K" in s.price_source


def test_unknown_models_get_cautious_defaults_and_warnings():
    s = resolve(MODEL="openai/some-model", API_KEY=KEY)
    assert not s.known and s.json_mode == ai.SCHEMA and s.effort is None and not s.fallbacks
    assert (s.image.max_edge, s.image.max_pixels) == (1568, 1_200_000)
    assert s.price_input is None and s.cost(100, 100) is None
    assert any("price" in w for w in s.warnings)
    assert any("cautious image limits" in w for w in s.warnings)
    assert s.describe()[-1].startswith("Price:     unknown (not in the built-in list")
    assert s.describe()[3] == "Images:    up to 1568 px long edge, 1.2 MP"


def test_local_models_are_free_and_use_prompt_json():
    s = resolve(MODEL="lmstudio/m")
    assert (s.price_input, s.price_output, s.json_mode) == (0.0, 0.0, ai.PROMPT)
    assert s.cost(1000, 1000) == 0.0
    assert "not needed" in s.describe()[0]


def test_everything_can_be_overridden():
    s = resolve(
        MODEL="openai/m",
        API_KEY=KEY,
        JSON="prompt",
        TEMPERATURE="0",
        PRICE_INPUT="1.5",
        PRICE_OUTPUT="6",
        IMAGE_MAX_EDGE="2048",
        IMAGE_MAX_PIXELS="3000000",
        MAX_TOKENS="4000",
        TIMEOUT_SECONDS="30",
        MAX_CALLS_PER_RUN="5",
        MAX_COST_PER_RUN_USD="0.5",
    )
    assert (s.json_mode, s.temperature, s.max_output_tokens, s.timeout_s) == (
        "prompt",
        0.0,
        4000,
        30.0,
    )
    assert (s.image.max_edge, s.image.max_pixels, s.image.max_visual_tokens) == (
        2048,
        3_000_000,
        None,
    )
    assert (s.max_calls_per_run, s.max_cost_per_run) == (5, 0.5)
    assert s.cost(1_000_000, 1_000_000) == 7.5
    assert s.price_source.startswith("COMPLIANCELENS_AI_PRICE")
    assert not any("price" in w for w in s.warnings)


def test_temperature_is_refused_for_models_that_reject_it():
    [problem] = problems(API_KEY=KEY, TEMPERATURE="0")
    assert "does not accept a temperature" in problem


def test_effort_only_for_anthropic_and_only_known_levels():
    assert resolve(API_KEY=KEY, EFFORT="low").effort == "low"
    assert "only works with anthropic" in problems(MODEL="openai/m", API_KEY=KEY, EFFORT="low")[0]
    assert "must be one of" in problems(API_KEY=KEY, EFFORT="extreme")[0]


@pytest.mark.parametrize(
    "values, message",
    [
        ({"JSON": "xml"}, "must be schema or prompt"),
        ({"PRICE_INPUT": "1"}, "set both"),
        ({"MAX_TOKENS": "lots"}, "must be a number"),
        ({"MAX_TOKENS": "10"}, "must be a number from 256"),
        ({"TIMEOUT_SECONDS": "-1"}, "must be a number"),
        ({"IMAGE_MAX_EDGE": "50"}, "must be a number"),
    ],
)
def test_bad_values_are_refused(values, message):
    assert any(message in p for p in problems(API_KEY=KEY, **values))


def test_every_problem_is_reported_at_once():
    found = problems(MODEL="openai/m", API_KEY=KEY, JSON="xml", EFFORT="low", MAX_TOKENS="1")
    assert len(found) == 3


def test_identity_records_what_can_change_an_answer():
    s = resolve(API_KEY=KEY)
    assert s.identity() == {
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "base_url_host": "api.anthropic.com",
        "json_mode": "schema",
        "temperature": None,
        "effort": "medium",
        "max_output_tokens": 8000,
        "image": {"max_edge": 2576, "max_visual_tokens": 4784, "patch_px": 28, "max_pixels": None},
    }


def test_cost_needs_token_counts():
    s = resolve(API_KEY=KEY)
    assert s.cost(1_000_000, 0) == 4.0
    assert s.cost(None, 10) is None


def test_the_environment_is_read_by_default(monkeypatch):
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "ollama/llava")
    assert ai.resolve().name == "ollama/llava"
