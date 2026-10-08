"""Smoke test: the package imports, has a version, and carries its data files."""

import compliancelens
from compliancelens.evaluator import prompt, settings


def test_version_is_set():
    assert isinstance(compliancelens.__version__, str)
    assert compliancelens.__version__


def test_ai_files_are_part_of_the_package():
    # Read through importlib.resources, as an installed copy would. CI also installs the
    # built wheel in a clean environment and loads them there.
    assert prompt.system_prompt().startswith("You check one compliance rule")
    assert prompt.answer_schema()["type"] == "object"
    assert "anthropic/claude-opus-5-5" in settings.catalog()["models"]
