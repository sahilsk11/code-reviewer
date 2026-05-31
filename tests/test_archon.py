from __future__ import annotations

from pathlib import Path

from code_reviewer.archon import (
    extract_archon_run_id,
    first_json_object,
    repair_workspace_source_symlink,
)


def test_first_json_object_handles_archon_log_prefix() -> None:
    output = """{"level":30,"msg":"db.connection_sqlite_selected"}
{
  "runs": [
    {"id": "run-1", "workflowName": "ai-code-review"}
  ]
}
"""

    data = first_json_object(output)

    assert data["runs"][0]["id"] == "run-1"


def test_extract_archon_run_id_reads_json_log_lines() -> None:
    output = """Running workflow: ai-code-review
{"level":30,"workflowRunId":"7bac03432fab6b262675fd36a2eea2f3","msg":"workflow_starting"}
"""

    assert extract_archon_run_id(output) == "7bac03432fab6b262675fd36a2eea2f3"


def test_repair_workspace_source_symlink_updates_stale_archon_link(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    workspace = tmp_path / ".archon" / "workspaces" / "owner" / "repo"
    workspace.mkdir(parents=True)
    stale = tmp_path / "old"
    expected = tmp_path / "new"
    stale.mkdir()
    expected.mkdir()
    source = workspace / "source"
    source.symlink_to(stale)

    note = repair_workspace_source_symlink(repository="owner/repo", cwd=expected)

    assert note is not None
    assert source.resolve() == expected.resolve()
    assert "Repaired stale Archon source symlink" in note


def test_repair_workspace_source_symlink_leaves_non_symlink_alone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    workspace = tmp_path / ".archon" / "workspaces" / "owner" / "repo"
    source = workspace / "source"
    source.mkdir(parents=True)

    note = repair_workspace_source_symlink(repository="owner/repo", cwd=tmp_path)

    assert note is None
    assert source.is_dir()
