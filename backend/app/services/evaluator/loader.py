"""Dynamic rule loader — auto-discovers evaluation rules from the rules/ directory."""

import importlib
import logging
from pathlib import Path

from app.services.evaluator.rules.rule_spec import RuleSpec

logger = logging.getLogger(__name__)

def load_rules_from_directory(rules_dir: Path | None = None) -> list[RuleSpec]:
    """Scan the rules directory and load all modules that export RULE_SPEC."""
    if rules_dir is None:
        rules_dir = Path(__file__).parent / "rules"

    specs: list[RuleSpec] = []

    for py_file in sorted(rules_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue  # skip __init__.py, __pycache__, etc.

        module_name = f"app.services.evaluator.rules.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "RULE_SPEC"):
                spec = module.RULE_SPEC
                if isinstance(spec, RuleSpec):
                    specs.append(spec)
                    logger.info("Loaded rule: %s from %s", spec.name, py_file.name)
                else:
                    logger.warning(
                        "RULE_SPEC in %s is not a RuleSpec instance, skipping", py_file.name
                    )
            else:
                logger.debug("No RULE_SPEC in %s, skipping", py_file.name)
        except Exception:
            logger.exception("Failed to load rule from %s", py_file.name)

    logger.info("Loaded %d evaluation rules total", len(specs))
    return specs
