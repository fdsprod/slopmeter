"""The stable first Python source-pattern catalog."""

from slop_measure.languages.python.rules import abstraction, control_flow, defensive, redundancy

RULE_SET_VERSION = "py-patterns-1"
RULES = tuple(
    sorted(
        (*redundancy.RULES, *control_flow.RULES, *defensive.RULES, *abstraction.RULES),
        key=lambda rule: rule.metadata.rule_id,
    )
)

__all__ = ["RULES", "RULE_SET_VERSION"]
