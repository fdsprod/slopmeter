"""Retained Pydantic 2.13.5 observations for string enums in union discriminators."""

from enum import StrEnum
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class ObservedState(StrEnum):
    INTRODUCED = "introduced"
    UNRESOLVED = "unresolved"


class Introduced(BaseModel):
    state: Literal[ObservedState.INTRODUCED] = ObservedState.INTRODUCED
    value: int


class Unresolved(BaseModel):
    state: Literal[ObservedState.UNRESOLVED] = ObservedState.UNRESOLVED
    reason: str


Observation = Annotated[Introduced | Unresolved, Field(discriminator="state")]


@pytest.mark.parametrize(
    "wire,expected",
    [
        ({"state": "introduced", "value": 1}, ObservedState.INTRODUCED),
        ({"state": "unresolved", "reason": "Missing source"}, ObservedState.UNRESOLVED),
    ],
)
def test_wire_string_selects_literal_enum_member_and_roundtrips(wire, expected):
    adapter = TypeAdapter(Observation)
    parsed = adapter.validate_python(wire)
    # Literal validation converts the accepted wire string into the enum singleton.
    assert parsed.state is expected
    # JSON retains the original string tag; enum identity does not change the wire shape.
    assert parsed.model_dump(mode="json") == wire
    restored = adapter.validate_json(adapter.dump_json(parsed))
    assert restored == parsed and restored.state is expected


def test_schema_uses_string_discriminator_tags_and_unknown_tag_fails():
    adapter = TypeAdapter(Observation)
    discriminator = adapter.json_schema()["discriminator"]
    assert discriminator["propertyName"] == "state"
    assert set(discriminator["mapping"]) == {"introduced", "unresolved"}
    with pytest.raises(ValidationError):
        adapter.validate_python({"state": "other", "value": 1})
