"""Adapter order and path spelling cannot change owned report values."""

from pathlib import Path

import pytest
from test_language_adapter import InventedAdapter, settings, synthetic_profile, write_sources

from slop_measure.application.service import AnalysisService
from slop_measure.domain.requests import SnapshotRequest
from slop_measure.domain.source import DirectorySourceReference
from slop_measure.languages.registry import LanguageRegistry
from slop_measure.reporting.json import serialize_report


def test_reversed_adapter_and_file_emission_and_windows_paths_produce_identical_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(
        "slop_measure.application.service.load_profile", lambda _name: synthetic_profile()
    )
    write_sources(tmp_path, changed=True)
    write_sources(tmp_path, changed=True, suffix=".second")
    request = SnapshotRequest(target=DirectorySourceReference(root=tmp_path), config=settings())
    forward = AnalysisService(
        LanguageRegistry(
            (InventedAdapter(), InventedAdapter(language_id="second", suffix=".second"))
        )
    )
    reverse = AnalysisService(
        LanguageRegistry(
            (
                InventedAdapter(
                    language_id="second", suffix=".second", reverse=True, windows_paths=True
                ),
                InventedAdapter(reverse=True, windows_paths=True),
            )
        )
    )
    first = forward.scan(request)
    second = reverse.scan(request)
    assert first.diagnostics == second.diagnostics == ()
    assert serialize_report(first) == serialize_report(second)
    assert all(
        "\\" not in file.evidence.path.root
        for cohort in second.cohorts
        for file in cohort.current.files
    )
    assert first.provenance == second.provenance
