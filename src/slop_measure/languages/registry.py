"""Explicit adapter registration with stable routing metadata."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from slop_measure.domain.source import ProjectPath
from slop_measure.errors import InputError
from slop_measure.languages.base import LanguageAdapter


@dataclass(frozen=True)
class _Registration:
    """Snapshot routing suffixes so adapter edits cannot change registration."""

    adapter: LanguageAdapter
    extensions: frozenset[str]


def _normalized_extensions(extensions: frozenset[str]) -> frozenset[str]:
    if not extensions:
        raise ValueError("an adapter must declare at least one extension")
    normalized: set[str] = set()
    for extension in extensions:
        if (
            not isinstance(extension, str)
            or not extension.startswith(".")
            or extension == "."
            or "/" in extension
            or "\\" in extension
            or "." in extension[1:]
            or "\0" in extension
            or any(character.isspace() for character in extension)
        ):
            raise ValueError(
                "an extension must be one dot-prefixed suffix without whitespace, NUL, "
                "or path separators"
            )
        key = extension.casefold()
        if key in normalized:
            raise ValueError(f"duplicate extension: {extension}")
        normalized.add(key)
    return frozenset(normalized)


class LanguageRegistry:
    """Route file suffixes to adapters registered by exact language identifier."""

    def __init__(self, adapters: Iterable[LanguageAdapter] = ()) -> None:
        self._registrations: dict[str, _Registration] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: LanguageAdapter) -> None:
        """Validate all routing metadata before adding an adapter."""
        language_id = adapter.language_id
        if (
            not isinstance(language_id, str)
            or not language_id
            or language_id != language_id.strip()
        ):
            raise ValueError("language ID must be nonempty with no surrounding whitespace")
        if language_id in self._registrations:
            raise ValueError(f"duplicate language ID: {language_id}")
        extensions = _normalized_extensions(adapter.extensions)
        for registration in self._registrations.values():
            conflicts = extensions & registration.extensions
            if conflicts:
                raise ValueError(f"extensions already registered: {', '.join(sorted(conflicts))}")
        self._registrations[language_id] = _Registration(adapter, extensions)

    def get(self, language_id: str) -> LanguageAdapter:
        """Return the adapter for an exact ID, or raise KeyError."""
        return self._registrations[language_id].adapter

    def for_path(self, path: ProjectPath) -> LanguageAdapter | None:
        """Return the adapter for a final suffix, ignoring suffix case."""
        extension = PurePosixPath(path.root).suffix.casefold()
        for registration in self._registrations.values():
            if extension in registration.extensions:
                return registration.adapter
        return None

    def resolve_languages(self, selectors: frozenset[str]) -> frozenset[str]:
        """Resolve installed language IDs or extension aliases without guessing support."""
        resolved: set[str] = set()
        for selector in sorted(selectors):
            key = selector.casefold()
            exact = [name for name in self._registrations if name == selector]
            names = exact or [name for name in self._registrations if name.casefold() == key]
            if not names:
                extension = "." + key.removeprefix(".")
                names = [
                    name
                    for name, registration in self._registrations.items()
                    if extension in registration.extensions
                ]
            if len(names) != 1:
                installed = ", ".join(sorted(self._registrations)) or "none"
                raise InputError(
                    f"Unknown or ambiguous language: {selector}. Installed: {installed}."
                )
            resolved.add(names[0])
        return frozenset(resolved)

    @property
    def adapters(self) -> tuple[LanguageAdapter, ...]:
        """Return adapters ordered by their registered language IDs."""
        return tuple(self._registrations[key].adapter for key in sorted(self._registrations))
