"""Explicit directory roots take precedence over ambient Git repository state."""

from pathlib import Path

import pytest
from test_filesystem import git, provider, write


@pytest.mark.parametrize(
    "variables",
    [
        ("GIT_DIR",),
        ("GIT_WORK_TREE",),
        ("GIT_INDEX_FILE",),
        ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"),
    ],
)
def test_directory_inventory_uses_own_git_policy_and_preserves_both_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variables: tuple[str, ...],
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    requested, foreign = tmp_path / "requested", tmp_path / "foreign"
    for root in (requested, foreign):
        root.mkdir()
        git(root, "init", "--quiet")
    write(requested, ".gitignore", b"*.generated.py\n")
    write(requested, "tracked.generated.py")
    git(requested, "add", "--force", "tracked.generated.py")
    write(requested, "untracked.py")
    write(requested, "ignored.generated.py")
    write(foreign, ".gitignore", b"untracked.py\n")
    write(foreign, "foreign.py")
    git(foreign, "add", "foreign.py")
    indexes = {root: (root / ".git" / "index").read_bytes() for root in (requested, foreign)}
    values = {
        "GIT_DIR": str(foreign / ".git"),
        "GIT_WORK_TREE": str(foreign),
        "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
    }
    for variable in variables:
        monkeypatch.setenv(variable, values[variable])
    inventory = provider(requested).inventory()
    assert [document.path.root for document in inventory.documents] == [
        "tracked.generated.py",
        "untracked.py",
    ]
    assert any(item.reason == "git ignored" and item.file_count == 1 for item in inventory.coverage)
    assert not inventory.failed_files and not inventory.diagnostics
    assert {root: (root / ".git" / "index").read_bytes() for root in indexes} == indexes
