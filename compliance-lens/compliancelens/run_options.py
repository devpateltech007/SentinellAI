"""What an audit is asked to do (V5), checked the same way for every front end.

`audit.py run` and the dashboard both turn their choices into RunOptions here, so a
choice the command line refuses is refused in the dashboard too, and neither can
forget the AI by accident (runner.run_audit() without AI options runs with it off).

Without an explicit list of rules, a run takes every rule that is turned on in
config/settings.yaml (config.py). An explicit list wins: a rule turned off can still
be run by name.

Problems raise OptionsError with a code, so each front end names its own controls
(--cross-check on the command line, a checkbox in the dashboard).
"""

from dataclasses import dataclass, field
from pathlib import Path

from compliancelens import config, runner
from compliancelens.evaluator import settings as ai_settings

NO_AI_CONFLICT = "no_ai_conflict"  # AI off, yet a cross-check, a refresh or a model asked for
CROSS_CHECK_NEEDS_SCREENSHOTS = "cross_check_needs_screenshots"
AI_SETTINGS = "ai_settings"  # the AI settings in .env can't be used
SETTINGS_FILE = "settings_file"  # config/settings.yaml can't be used


class OptionsError(ValueError):
    """The run can't start as asked. `code` says which problem, `problems` the details."""

    def __init__(self, code: str, problems: list[str]):
        super().__init__("; ".join(problems))
        self.code, self.problems = code, problems


@dataclass
class RunOptions:
    rule_ids: list[str] | None = None  # None: every rule that is turned on
    disabled: list[str] = field(default_factory=list)  # turned off (only when rule_ids is None)
    screenshots: bool = True
    ai: runner.AIOptions = field(default_factory=lambda: runner.AIOptions(enabled=False))


def prepare(
    rule_ids: list[str] | None = None,
    *,
    screenshots: bool = True,
    use_ai: bool = True,
    cross_check: bool = False,
    refresh_ai: bool = False,
    ai_model: str | None = None,
) -> RunOptions:
    """Check the choices and resolve the AI settings and the rules turned off.

    Raises OptionsError.
    """
    if not use_ai and (cross_check or refresh_ai or ai_model):
        raise OptionsError(
            NO_AI_CONFLICT,
            ["with the AI off there is nothing to cross-check, ask again or choose a model for"],
        )
    if cross_check and not screenshots:
        raise OptionsError(
            CROSS_CHECK_NEEDS_SCREENSHOTS, ["a cross-check reads screenshots: turn them on"]
        )
    disabled = []
    if rule_ids is None:
        try:
            disabled = config.disabled_rules()
        except config.SettingsError as e:
            raise OptionsError(SETTINGS_FILE, [str(e)])
    if not use_ai:
        return RunOptions(rule_ids, disabled, screenshots, runner.AIOptions(enabled=False))
    try:
        settings = ai_settings.resolve(model=ai_model)
    except ai_settings.AISettingsError as e:
        raise OptionsError(AI_SETTINGS, e.problems)
    ai = runner.AIOptions(settings=settings, refresh=refresh_ai, cross_check=cross_check)
    return RunOptions(rule_ids, disabled, screenshots, ai)


def run(rules_file: Path, options: RunOptions, on_result=None, on_event=None):
    """Run an audit with checked options. Raises what runner.run_audit() raises."""
    return runner.run_audit(
        rules_file,
        options.rule_ids,
        on_result=on_result,
        screenshots=options.screenshots,
        ai_options=options.ai,
        disabled=options.disabled,
        on_event=on_event,
    )
