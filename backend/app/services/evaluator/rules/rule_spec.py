from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RuleSpec:
    """Declaration of a single evaluation rule."""
    name: str
    description: str
    fn: Callable[[str, list[dict]], dict | None]
    applicable_control_patterns: list[str]
    applicable_source_types: list[str] = field(default_factory=lambda: ["*"])
    # If source_types is ["*"], rule runs against all evidence types.
    # Otherwise, only runs when evidence of that type is linked.
