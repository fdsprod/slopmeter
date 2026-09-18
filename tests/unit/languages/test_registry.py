"""Contracts for explicit language registration and immutable routing metadata."""

from dataclasses import dataclass

import pytest

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import EvidenceCapability, LanguageEvidence
from slop_measure.domain.source import ProjectPath, SourceDocument
from slop_measure.languages.base import LanguageAdapter
from slop_measure.languages.registry import LanguageRegistry


@dataclass(frozen=True)
class FakeAdapter:
    """A frozen third-party adapter that satisfies the public protocol."""

    language_id: str = "python"
    extensions: frozenset[str] = frozenset({".py"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        return LanguageEvidence(language=self.language_id, capabilities=self.capabilities, files=())


@dataclass
class MutableAdapter:
    """Expose mutable metadata to verify the registry takes routing snapshots."""

    language_id: str = "python"
    extensions: frozenset[str] = frozenset({".py"})
    capabilities: frozenset[EvidenceCapability] = frozenset({EvidenceCapability.FILES})

    def analyze(
        self, documents: tuple[SourceDocument, ...], config: AnalysisConfig
    ) -> LanguageEvidence:
        return LanguageEvidence(language=self.language_id, capabilities=self.capabilities, files=())


def test_frozen_adapter_satisfies_protocol_and_returns_owned_evidence() -> None:
    adapter: LanguageAdapter = FakeAdapter()

    evidence = adapter.analyze((), AnalysisConfig())

    assert evidence.language == "python"
    assert evidence.capabilities == frozenset({EvidenceCapability.FILES})
    assert evidence.files == ()


def test_empty_registry_has_no_implicit_adapters() -> None:
    registry = LanguageRegistry()

    assert registry.adapters == ()
    assert registry.for_path(ProjectPath("app.py")) is None
    with pytest.raises(KeyError):
        registry.get("python")


def test_registry_accepts_an_iterable_and_sorts_adapters_by_language_id() -> None:
    typescript = FakeAdapter("typescript", frozenset({".ts"}))
    python = FakeAdapter()
    registry = LanguageRegistry(adapter for adapter in (typescript, python))

    assert registry.adapters == (python, typescript)
    assert registry.get("python") is python
    assert registry.get("typescript") is typescript
    with pytest.raises(KeyError):
        registry.get("unknown")


@pytest.mark.parametrize("path", ["src/app.py", "src/APP.PY", "src/app.Py"])
def test_registry_routes_case_insensitive_suffixes(path: str) -> None:
    adapter = FakeAdapter(extensions=frozenset({".PY"}))
    registry = LanguageRegistry((adapter,))

    assert registry.for_path(ProjectPath(path)) is adapter


@pytest.mark.parametrize("path", ["README", "app.py.txt", "folder.py/app", "app.js"])
def test_registry_does_not_route_unknown_or_nonfinal_suffixes(path: str) -> None:
    assert LanguageRegistry((FakeAdapter(),)).for_path(ProjectPath(path)) is None


def test_register_adds_multiple_extensions_for_one_adapter() -> None:
    adapter = FakeAdapter("typescript", frozenset({".ts", ".tsx"}))
    registry = LanguageRegistry()

    assert registry.register(adapter) is None
    assert registry.for_path(ProjectPath("index.ts")) is adapter
    assert registry.for_path(ProjectPath("view.tsx")) is adapter


def test_duplicate_language_id_rejects_all_new_routes() -> None:
    original = FakeAdapter()
    registry = LanguageRegistry((original,))

    with pytest.raises(ValueError):
        registry.register(FakeAdapter("python", frozenset({".pyi"})))

    assert registry.adapters == (original,)
    assert registry.get("python") is original
    assert registry.for_path(ProjectPath("stub.pyi")) is None


def test_extension_collision_rejects_registration_atomically() -> None:
    original = FakeAdapter()
    registry = LanguageRegistry((original,))

    with pytest.raises(ValueError):
        registry.register(FakeAdapter("other", frozenset({".PY", ".new"})))

    assert registry.adapters == (original,)
    assert registry.for_path(ProjectPath("app.py")) is original
    assert registry.for_path(ProjectPath("app.new")) is None
    with pytest.raises(KeyError):
        registry.get("other")


@pytest.mark.parametrize("language_id", ["", " ", "\t\n"])
def test_registry_rejects_blank_language_ids(language_id: str) -> None:
    registry = LanguageRegistry()

    with pytest.raises(ValueError):
        registry.register(FakeAdapter(language_id))

    assert registry.adapters == ()
    assert registry.for_path(ProjectPath("app.py")) is None


@pytest.mark.parametrize("extension", ["", ".", "py", ".p/y", ".p\\y"])
def test_registry_rejects_invalid_extensions_without_adding_routes(extension: str) -> None:
    registry = LanguageRegistry()

    with pytest.raises(ValueError):
        registry.register(FakeAdapter(extensions=frozenset({".valid", extension})))

    assert registry.adapters == ()
    assert registry.for_path(ProjectPath("app.valid")) is None


def test_registry_requires_at_least_one_extension() -> None:
    with pytest.raises(ValueError):
        LanguageRegistry((FakeAdapter(extensions=frozenset()),))


def test_registry_rejects_duplicate_extensions_after_case_normalization() -> None:
    with pytest.raises(ValueError):
        LanguageRegistry((FakeAdapter(extensions=frozenset({".py", ".PY"})),))


def test_registry_keeps_routing_metadata_after_adapter_mutation() -> None:
    mutable = MutableAdapter()
    typescript = FakeAdapter("typescript", frozenset({".ts"}))
    registry = LanguageRegistry((typescript, mutable))
    mutable.language_id = "zzz"
    mutable.extensions = frozenset({".changed"})

    assert registry.get("python") is mutable
    assert registry.for_path(ProjectPath("app.PY")) is mutable
    assert registry.for_path(ProjectPath("app.changed")) is None
    assert registry.adapters == (mutable, typescript)
    with pytest.raises(KeyError):
        registry.get("zzz")
    with pytest.raises(ValueError):
        registry.register(FakeAdapter("python", frozenset({".other"})))
    with pytest.raises(ValueError):
        registry.register(FakeAdapter("other", frozenset({".py"})))
