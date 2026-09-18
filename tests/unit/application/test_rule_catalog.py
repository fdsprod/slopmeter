"""The catalog exposes every rule and its effective selection state."""

import pytest
from pydantic import ValidationError

from slop_measure.application.catalog import rule_catalog
from slop_measure.config import AnalysisConfig
from slop_measure.languages.python.rules import RULES


def test_catalog_is_complete_sorted_immutable_and_preserves_rule_metadata() -> None:
    result = rule_catalog(AnalysisConfig())
    assert result.language == "python"
    assert result.version == "py-patterns-1"
    assert isinstance(result.rules, tuple)
    assert len(result.rules) == 20
    assert tuple(entry.metadata for entry in result.rules) == tuple(rule.metadata for rule in RULES)
    assert all(entry.enabled for entry in result.rules)
    with pytest.raises(ValidationError):
        result.version = "changed"
    with pytest.raises(ValidationError):
        result.rules[0].enabled = False


def test_explicit_enable_list_retains_disabled_entries_in_complete_catalog() -> None:
    enabled = {"py.literal-fstring", "py.boolean-conditional"}
    catalog = rule_catalog(AnalysisConfig(enabled_rules=frozenset(enabled)))
    assert len(catalog.rules) == 20
    assert {entry.metadata.rule_id for entry in catalog.rules if entry.enabled} == enabled


def test_disable_list_removes_only_named_rules_from_effective_selection() -> None:
    catalog = rule_catalog(AnalysisConfig(disabled_rules=frozenset({"py.literal-fstring"})))
    assert sum(entry.enabled for entry in catalog.rules) == 19
    assert {entry.metadata.rule_id for entry in catalog.rules if not entry.enabled} == {
        "py.literal-fstring"
    }


@pytest.mark.parametrize("field", ["enabled_rules", "disabled_rules"])
def test_unknown_rule_selection_is_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        rule_catalog(AnalysisConfig.model_validate({field: ["py.unknown"]}))
