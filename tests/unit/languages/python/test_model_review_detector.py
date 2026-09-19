"""Paired examples define a narrow, source-only coupled-state experiment."""

import hashlib

import pytest
from pydantic import ValidationError

from slop_measure.domain.source import Cohort, ProjectPath, SourceDocument
from slop_measure.languages.python.model_review import analyze_models

SOURCE = """from dataclasses import dataclass

@dataclass
class State:
    active: bool
    value: str | None
    def __post_init__(self):
        if self.active and self.value is None:
            raise ValueError("value required")

def first(item: State):
    if item.active and item.value is None:
        return None
    return item.value

def second(record: State):
    if record.active and record.value is None:
        return None
    return record.value
"""


def document(source: str) -> SourceDocument:
    return SourceDocument(
        path=ProjectPath("models.py"),
        language="python",
        cohort=Cohort.PRODUCTION,
        content=source.encode("utf-8"),
    )


def wire(source: str) -> dict:
    return analyze_models(document(source)).model_dump(mode="json")


def findings(payload: dict) -> list[dict]:
    return [finding for model in payload.get("models", []) for finding in model.get("findings", [])]


@pytest.mark.parametrize("alias,quoted", [(False, False), (True, True)])
def test_repeated_boolean_nullable_rejection_has_precise_owned_locations(
    alias: bool, quoted: bool
) -> None:
    source = SOURCE
    if alias:
        source = source.replace("import dataclass", "import dataclass as record_model").replace(
            "@dataclass", "@record_model(frozen=True)"
        )
    if quoted:
        source = source.replace(": State)", ': "State")')
    outcome = analyze_models(document(source))
    payload = outcome.model_dump(mode="json")
    assert payload["state"] == "analyzed" and payload["path"] == "models.py"
    assert payload["cohort"] == "production"
    assert payload["source_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert len(payload["models"]) == 1
    model = payload["models"][0]
    assert model["state"] == "analyzed" and model["name"] == "State"
    assert model["span"]["start_line"] <= 4 <= model["span"]["end_line"]
    (finding,) = model["findings"]
    assert finding["kind"] == "coupled-state"
    assert finding["predicate"] == "model.active and model.value is None"
    assert finding["fields"] == [
        {"name": "active", "kind": "boolean", "span": {"start_line": 5, "end_line": 5}},
        {"name": "value", "kind": "nullable", "span": {"start_line": 6, "end_line": 6}},
    ]
    assert finding["validator"] == {
        "symbol": "State.__post_init__",
        "span": {"start_line": 8, "end_line": 8},
    }
    assert finding["consumers"] == [
        {"symbol": "first", "span": {"start_line": 12, "end_line": 12}},
        {"symbol": "second", "span": {"start_line": 17, "end_line": 17}},
    ]
    with pytest.raises(ValidationError):
        outcome.path = ProjectPath("changed.py")
    assert type(outcome).model_validate_json(outcome.model_dump_json()) == outcome


@pytest.mark.parametrize(
    "case",
    [
        "model-only",
        "one-consumer",
        "one-symbol-twice",
        "different-predicate",
        "independent-flags",
        "nonraising-validator",
    ],
)
def test_nearby_nonexamples_do_not_claim_repeated_coupling(case: str) -> None:
    source = SOURCE
    if case == "model-only":
        source = source.split("def first", 1)[0]
    elif case == "one-consumer":
        source = source.split("def second", 1)[0]
    elif case == "one-symbol-twice":
        source = source.split("def second", 1)[0].replace(
            "    return item.value",
            "    if item.active and item.value is None:\n"
            "        return None\n    return item.value",
        )
    elif case == "different-predicate":
        source = source.replace(
            "if record.active and record.value is None:",
            "if record.value is None and record.active:",
        )
    elif case == "independent-flags":
        source = source.replace("value: str | None", "value: bool").replace(
            ".value is None", ".value"
        )
    else:
        source = source.replace('raise ValueError("value required")', "return None")
    payload = wire(source)
    assert payload["state"] == "analyzed"
    assert findings(payload) == []


@pytest.mark.parametrize("mutation", ["reassign", "field-write", "nested-consumer"])
def test_uncertain_or_mutated_consumer_is_not_independent_evidence(mutation: str) -> None:
    if mutation == "reassign":
        source = SOURCE.replace(
            "def second(record: State):\n", "def second(record: State):\n    record = replacement\n"
        )
    elif mutation == "field-write":
        source = SOURCE.replace(
            "def second(record: State):\n",
            "def second(record: State):\n    record.active = False\n",
        )
    else:
        head, tail = SOURCE.split("def second", 1)
        source = (
            head
            + "def wrapper():\n"
            + "\n".join("    " + line for line in ("def second" + tail).splitlines())
            + "\n"
        )
    assert findings(wire(source)) == []


@pytest.mark.parametrize(
    "mutation",
    ["inherited", "shadowed-import", "shadowed-model", "optional-alias", "ordinary-class"],
)
def test_unsupported_or_ambiguous_model_is_unresolved_not_clean(mutation: str) -> None:
    source = SOURCE
    if mutation == "inherited":
        source = source.replace("class State:", "class State(Base):")
    elif mutation == "shadowed-import":
        source = source.replace("@dataclass", "dataclass = replacement\n@dataclass")
    elif mutation == "shadowed-model":
        source = source.replace("def first", "State = replacement\n\ndef first")
    elif mutation == "optional-alias":
        source = source.replace("str | None", "Optional[str]")
    else:
        source = source.replace("@dataclass\n", "")
    payload = wire(source)
    assert findings(payload) == []
    model = next(model for model in payload["models"] if model["name"] == "State")
    assert model["state"] == "unresolved" and model["reason"].strip()


def test_parse_failure_is_failed_with_owned_diagnostic_and_no_successful_models() -> None:
    payload = wire("class Broken(:\n")
    assert payload["state"] == "failed"
    assert payload["diagnostic"]["path"] == "models.py"
    assert payload["diagnostic"]["severity"] == "error"
    assert payload["diagnostic"]["message"]
    assert "models" not in payload


def test_target_module_and_validator_are_never_executed() -> None:
    payload = wire(SOURCE + '\nraise RuntimeError("target must not execute")\n')
    assert payload["state"] == "analyzed" and len(findings(payload)) == 1
