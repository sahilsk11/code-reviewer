from __future__ import annotations

import sqlite3
from pathlib import Path

from code_reviewer.run_store import RunStore


def test_run_store_tracks_active_and_finished_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    run = store.create_run(
        repository="owner/repo",
        pr_number=12,
        head_sha="abc123",
        mode="incremental",
        harness="opencode",
        model="model-a",
        repo_path=tmp_path,
        workflow_name="ai-code-review-test",
        workflow_path=tmp_path / ".archon" / "workflows" / "ai-code-review-test.yaml",
        workflow_yaml="name: ai-code-review-test\n",
    )

    assert store.active_runs_for_pr(repository="owner/repo", pr_number=12) == [run]

    store.set_archon_run_id(run.id, "archon-run-1")
    store.mark_failed(run.id, exit_code=247)

    assert store.active_runs_for_pr(repository="owner/repo", pr_number=12) == []
    finished = store.get_run(run.id)
    assert finished.status == "failed"
    assert finished.archon_run_id == "archon-run-1"
    assert finished.exit_code == 247


def test_run_store_marks_superseded_run_canceled(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    run = store.create_run(
        repository="owner/repo",
        pr_number=12,
        head_sha="abc123",
        mode="incremental",
        harness="opencode",
        model="model-a",
        repo_path=tmp_path,
        workflow_name="ai-code-review-old",
        workflow_path=tmp_path / ".archon" / "workflows" / "ai-code-review-old.yaml",
        workflow_yaml="name: ai-code-review-old\n",
    )

    store.mark_canceling(run.id)
    store.mark_canceled(run.id, superseded_by="replacement")

    assert store.active_runs_for_pr(repository="owner/repo", pr_number=12) == []
    with sqlite3.connect(tmp_path / "runs.db") as connection:
        row = connection.execute(
            "select status, superseded_by from code_review_runs where id = ?",
            (run.id,),
        ).fetchone()
    assert row == ("canceled", "replacement")
