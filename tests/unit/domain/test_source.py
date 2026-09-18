"""Behavioral tests for source-domain value objects and tagged variants."""

from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.source import (
    Cohort,
    DirectorySourceIdentity,
    DirectorySourceReference,
    GitSourceIdentity,
    GitSourceReference,
    ProjectPath,
    SourceDocument,
    SourceIdentity,
    SourceReference,
)


@pytest.mark.parametrize("value", ["production", "test"])
def test_cohort_accepts_the_two_scoring_populations(value: str) -> None:
    assert Cohort(value).value == value


def test_cohort_rejects_an_unknown_population() -> None:
    with pytest.raises(ValueError):
        Cohort("generated")


def test_project_path_normalizes_windows_separators() -> None:
    path = ProjectPath(r"src\slop_measure\domain\source.py")

    assert path.root == "src/slop_measure/domain/source.py"
    assert path.model_dump(mode="json") == "src/slop_measure/domain/source.py"


@pytest.mark.parametrize(
    "value",
    [
        "/src/app.py",
        "C:/repo/src/app.py",
        r"C:\repo\src\app.py",
        r"\\server\share\src\app.py",
        "../src/app.py",
        "src/../app.py",
        "",
        ".",
        "./src/app.py",
        "src/./app.py",
        "src/app.py\0ignored",
    ],
)
def test_project_path_rejects_non_project_relative_paths(value: str) -> None:
    with pytest.raises(ValidationError):
        ProjectPath(value)


def test_source_references_are_explicit_tagged_variants() -> None:
    adapter = TypeAdapter(SourceReference)

    directory = adapter.validate_python({"kind": "directory", "root": "checkout"})
    git = adapter.validate_python({"kind": "git", "root": "checkout", "revision": "HEAD"})

    assert isinstance(directory, DirectorySourceReference)
    assert directory.model_dump(mode="json") == {
        "kind": "directory",
        "root": "checkout",
    }
    assert isinstance(git, GitSourceReference)
    assert git.model_dump(mode="json") == {
        "kind": "git",
        "root": "checkout",
        "revision": "HEAD",
    }


@pytest.mark.parametrize("revision", ["", " ", "\t\n"])
def test_git_source_reference_requires_a_nonempty_revision(revision: str) -> None:
    with pytest.raises(ValidationError):
        GitSourceReference(root=Path("checkout"), revision=revision)


def test_resolved_source_identities_are_distinct_tagged_variants() -> None:
    adapter = TypeAdapter(SourceIdentity)

    directory = adapter.validate_python({"kind": "directory", "root": "checkout"})
    git = adapter.validate_python(
        {
            "kind": "git",
            "root": "checkout",
            "revision": "b6f8bf73129a3f251113bfc258b056e107a5f613",
        }
    )

    assert isinstance(directory, DirectorySourceIdentity)
    assert isinstance(git, GitSourceIdentity)
    assert git.revision == "b6f8bf73129a3f251113bfc258b056e107a5f613"
    assert git.model_dump(mode="json")["kind"] == "git"


@pytest.mark.parametrize("revision", ["", " ", "\r\n"])
def test_git_source_identity_requires_a_nonempty_resolved_revision(
    revision: str,
) -> None:
    with pytest.raises(ValidationError):
        GitSourceIdentity(root=Path("checkout"), revision=revision)


def test_a_mutable_git_reference_can_resolve_to_a_stable_distinct_identity() -> None:
    reference = GitSourceReference(root=Path("checkout"), revision="HEAD")
    identity = GitSourceIdentity(
        root=reference.root,
        revision="b6f8bf73129a3f251113bfc258b056e107a5f613",
    )

    assert not isinstance(reference, GitSourceIdentity)
    assert reference.revision == "HEAD"
    assert identity.revision != reference.revision


@pytest.mark.parametrize(
    "source",
    [
        DirectorySourceReference(root=Path("checkout")),
        GitSourceReference(root=Path("checkout"), revision="HEAD"),
        DirectorySourceIdentity(root=Path("checkout")),
        GitSourceIdentity(
            root=Path("checkout"),
            revision="b6f8bf73129a3f251113bfc258b056e107a5f613",
        ),
    ],
)
def test_source_references_and_identities_are_immutable(source: object) -> None:
    with pytest.raises(ValidationError):
        source.root = Path("other")  # type: ignore[attr-defined]


def test_source_document_keeps_exact_bytes_and_derives_its_content_hash() -> None:
    content = b"print('raw bytes')\r\n# \xff\n"
    document = SourceDocument(
        path=ProjectPath(r"src\app.py"),
        content=content,
        language="python",
        cohort=Cohort.PRODUCTION,
    )

    assert document.path == ProjectPath("src/app.py")
    assert document.content is content
    assert document.language == "python"
    assert document.cohort is Cohort.PRODUCTION
    assert document.content_hash == sha256(content).hexdigest()


def test_source_document_does_not_accept_an_independent_content_hash() -> None:
    with pytest.raises(ValidationError):
        SourceDocument(
            path=ProjectPath("src/app.py"),
            content=b"content",
            content_hash="caller-controlled",  # pyright: ignore[reportCallIssue]
            language="python",
            cohort=Cohort.PRODUCTION,
        )


def test_source_document_is_immutable() -> None:
    document = SourceDocument(
        path=ProjectPath("src/app.py"),
        content=b"before",
        language="python",
        cohort=Cohort.TEST,
    )

    with pytest.raises(ValidationError):
        document.content = b"after"
