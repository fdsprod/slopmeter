"""Resolve the installed Python rule catalog without analyzing source files."""

from slop_measure.config import AnalysisConfig
from slop_measure.domain.rules import RuleCatalog, RuleEntry
from slop_measure.languages.python.patterns import select_rules
from slop_measure.languages.python.rules import RULE_SET_VERSION, RULES


def rule_catalog(config: AnalysisConfig) -> RuleCatalog:
    """Include every rule with its version and effective enabled state."""
    enabled = {rule.metadata.rule_id for rule in select_rules(RULES, config)}
    return RuleCatalog(
        language="python",
        version=RULE_SET_VERSION,
        rules=tuple(
            RuleEntry(metadata=rule.metadata, enabled=rule.metadata.rule_id in enabled)
            for rule in RULES
        ),
    )
