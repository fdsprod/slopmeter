"""Closed vocabulary for finding continuity across two source snapshots."""

from enum import StrEnum


class FindingChangeState(StrEnum):
    INTRODUCED = "introduced"
    REMOVED = "removed"
    PERSISTED = "persisted"
    CHANGED = "changed"
    UNRESOLVED = "unresolved"
