"""Explicit ownership annotations add review context without changing measurements."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from slop_measure.api import (
    AnalysisConfig,
    ComparisonRequest,
    DirectorySourceReference,
    SnapshotRequest,
    compare,
    scan,
)
from slop_measure.cli import app
from slop_measure.domain.boundaries import (
    BoundaryAssignment,
    BoundaryDeclaration,
    CloneBoundaryContext,
)
from slop_measure.domain.reports import AnalysisReport


@pytest.mark.parametrize(
    "labels,relation",
    [
        (("one", "one"), "within-boundary"),
        (("one", "two"), "cross-boundary"),
        (("one", None), "unknown"),
        ((None, None), "unknown"),
    ],
)
def test_boundary_relation_is_derived_and_checked(labels, relation: str) -> None:
    context = CloneBoundaryContext.model_validate(
        {
            "members": [
                {"path": path, "boundary": label}
                for path, label in zip(("a.py", "b.py"), labels, strict=True)
            ],
            "policy_fingerprint": "a" * 64,
        }
    )
    assert context.model_dump(mode="json")["relation"] == relation
    assert CloneBoundaryContext.model_validate_json(context.model_dump_json()) == context
    payload = context.model_dump(mode="json")
    payload["relation"] = "cross-boundary" if relation != "cross-boundary" else "within-boundary"
    with pytest.raises(ValidationError):
        CloneBoundaryContext.model_validate(payload)
    with pytest.raises(ValidationError):
        context.policy_fingerprint = "b" * 64


@pytest.mark.parametrize(
    "prefix", [".", "../pkg", "/pkg", "C:/pkg", "pkg/**", "pkg/*", "pkg/?.py", "pkg/[ab]"]
)
def test_boundary_prefix_rejects_ambiguous_or_unsafe_paths(prefix: str) -> None:
    with pytest.raises(ValidationError):
        BoundaryDeclaration.model_validate({"name": "component", "prefix": prefix})


def test_boundary_config_is_immutable_unique_and_omitted_by_default() -> None:
    assert "boundaries" not in AnalysisConfig().model_dump(mode="json")
    assert "boundaries" not in AnalysisConfig().model_dump()
    config = AnalysisConfig.model_validate({"boundaries": [{"name": "one", "prefix": "pkg\\core"}]})
    assert config.model_dump(mode="json")["boundaries"] == [{"name": "one", "prefix": "pkg/core"}]
    assert AnalysisConfig.model_validate_json(config.model_dump_json()) == config
    for declarations in (
        [{"name": "one", "prefix": "pkg/core"}, {"name": "two", "prefix": "pkg\\core"}],
        [{"name": "same", "prefix": "pkg"}, {"name": "same", "prefix": "other"}],
        [{"name": " ", "prefix": "pkg"}],
    ):
        with pytest.raises(ValidationError):
            AnalysisConfig.model_validate({"boundaries": declarations})
    with pytest.raises(ValidationError):
        BoundaryAssignment.model_validate({"path": "a.py", "boundary": ""})
    for members in ([], [{"path": "a.py", "boundary": None}] * 2):
        with pytest.raises(ValidationError):
            CloneBoundaryContext.model_validate(
                {"members": members, "policy_fingerprint": "a" * 64}
            )
    for fingerprint in ("a" * 63, "A" * 64, "z" * 64, 1):
        with pytest.raises(ValidationError):
            CloneBoundaryContext.model_validate(
                {"members": [{"path": "a.py", "boundary": None}], "policy_fingerprint": fingerprint}
            )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    source = (
        "def work(value):\n    result = value + 1\n    result += 2\n    result += 3\n"
        "    result += 4\n    result += 5\n    return result\n"
    )
    for name in ("pkg/a.py", "pkg/core/b.py", "pkg_extra/c.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def config(*, reverse: bool = False, rename: bool = False) -> AnalysisConfig:
    boundaries = [
        {"name": "package", "prefix": "pkg"},
        {"name": "core-renamed" if rename else "core", "prefix": "pkg/core"},
    ]
    return AnalysisConfig.model_validate(
        {"boundaries": boundaries[::-1] if reverse else boundaries}
    )


def snapshot(project: Path, settings: AnalysisConfig) -> AnalysisReport:
    return scan(SnapshotRequest(target=DirectorySourceReference(root=project), config=settings))


def test_annotations_use_longest_component_prefix_and_never_change_scores_or_clone_ids(
    project: Path,
) -> None:
    plain, annotated = snapshot(project, AnalysisConfig()), snapshot(project, config())
    assert plain.clone_groups and len(annotated.clone_groups) == len(plain.clone_groups)
    assert plain.cohorts == annotated.cohorts
    assert plain.findings == annotated.findings
    for old, new in zip(plain.clone_groups, annotated.clone_groups, strict=True):
        assert old.id == new.id and old.detail == new.detail and old.source == new.source
        assert "boundary_context" not in old.model_dump(mode="json")
        context = new.model_dump(mode="json")["boundary_context"]
        assert context["relation"] == "unknown"
        assert context["members"] == [
            {"path": "pkg/a.py", "boundary": "package"},
            {"path": "pkg/core/b.py", "boundary": "core"},
            {"path": "pkg_extra/c.py", "boundary": None},
        ]
    assert AnalysisReport.model_validate_json(annotated.model_dump_json()) == annotated
    reversed_report = snapshot(project, config(reverse=True))
    renamed = snapshot(project, config(rename=True))
    first = annotated.clone_groups[0].model_dump(mode="json")["boundary_context"]
    assert reversed_report.clone_groups[0].model_dump(mode="json")["boundary_context"] == first
    assert (
        renamed.clone_groups[0].model_dump(mode="json")["boundary_context"]["policy_fingerprint"]
        != first["policy_fingerprint"]
    )
    assert renamed.cohorts == plain.cohorts


@pytest.mark.parametrize("tamper", ["label", "path", "fingerprint"])
def test_report_rejects_context_that_disagrees_with_its_owned_policy(
    project: Path, tamper: str
) -> None:
    payload = snapshot(project, config()).model_dump(mode="json")
    context = payload["clone_groups"][0]["boundary_context"]
    if tamper == "label":
        context["members"][0]["boundary"] = "invented"
    elif tamper == "path":
        context["members"].pop()
    else:
        context["policy_fingerprint"] = "0" * 64
    context.pop("relation", None)
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_comparison_preserves_both_owned_contexts(project: Path) -> None:
    reference = DirectorySourceReference(root=project)
    owned = snapshot(project, config())
    compared = compare(ComparisonRequest(baseline=reference, current=reference, config=config()))
    assert {group.source.value for group in compared.clone_groups} == {"baseline", "current"}
    for group in compared.clone_groups:
        assert group.detail == owned.clone_groups[0].detail
        assert (
            group.model_dump(mode="json")["boundary_context"]
            == owned.clone_groups[0].model_dump(mode="json")["boundary_context"]
        )


def test_cli_toml_annotations_reach_json_and_both_clone_views(project: Path) -> None:
    (project / "slop.toml").write_text(
        '[[boundaries]]\nname="package"\nprefix="pkg"\n[[boundaries]]\nname="core"\nprefix="pkg/core"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["findings", "--root", str(project), "--metric", "m3", "--json"])
    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.stdout)["selection"]["clone_groups"][0]["boundary_context"]["relation"]
        == "unknown"
    )
    for args in (
        ["findings", "--root", str(project), "--metric", "m3"],
        ["explain", "pkg/a.py", "--root", str(project)],
    ):
        rendered = runner.invoke(app, [*args, "--ascii", "--no-color"])
        assert rendered.exit_code == 0, rendered.output
        text = rendered.stdout.split("How to read this report", 1)[0].lower()
        assert "unknown" in text and "unassigned" in text and "package" in text and "core" in text
    (project / "slop.toml").write_text(
        '[[boundaries]]\nname="bad"\nprefix="../escape"\n', encoding="utf-8"
    )
    invalid = runner.invoke(app, ["score", str(project)])
    assert invalid.exit_code == 2
    assert "Invalid analysis input:" in invalid.stderr
