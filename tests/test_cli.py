from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from code_reviewer.archon import ArchonResult, ArchonRun
from code_reviewer.cli import build_review_payload, main, sanitize_argv
from code_reviewer.run_store import RunStore


def test_install_workflow(tmp_path: Path) -> None:
    result = main(["install-workflow", "--repo", str(tmp_path)])

    assert result == 0
    assert (tmp_path / ".archon" / "workflows" / "ai-code-review.yaml").exists()


def test_build_review_payload_from_pr_url_and_head_sha(tmp_path: Path) -> None:
    payload = build_review_payload(
        repo=tmp_path,
        pr_url="https://github.com/owner/repo/pull/42",
        head_sha="event-sha",
        mode="incremental",
    )

    assert payload["head_sha"] == "event-sha"
    assert payload["pull_request_number"] == 42
    assert payload["pull_request_url"] == "https://github.com/owner/repo/pull/42"
    assert payload["repository"] == "owner/repo"
    assert payload["dry_run"] is False


def test_build_review_payload_resolves_head_sha_from_pr_url(tmp_path: Path) -> None:
    completed = Mock(stdout=json.dumps({"headRefOid": "resolved-sha"}))

    with patch("code_reviewer.cli.subprocess.run", return_value=completed):
        payload = build_review_payload(
            repo=tmp_path,
            pr_url="https://github.com/owner/repo/pull/42",
            head_sha=None,
            mode="full",
            dry_run=True,
        )

    assert payload["head_sha"] == "resolved-sha"
    assert payload["repository"] == "owner/repo"
    assert payload["pull_request_number"] == 42
    assert payload["dry_run"] is True


def test_review_generates_workflow_tracks_run_and_invokes_archon(tmp_path: Path) -> None:
    fake_archon = Mock()
    fake_archon.run_workflow.return_value = ArchonResult(
        returncode=0,
        output='{"workflowRunId":"archon-run-1"}\n',
        archon_run_id="archon-run-1",
    )
    fake_archon.active_runs.return_value = []
    db_path = tmp_path / "runs.db"
    with patch("code_reviewer.cli.ArchonClient", return_value=fake_archon):
        result = main(
            [
                "review",
                "--repo",
                str(tmp_path),
                "--pr-url",
                "https://github.com/owner/repo/pull/7",
                "--head-sha",
                "abc123",
                "--archon-bin",
                "archon-test",
                "--harness",
                "codex",
                "--model",
                "gpt-test",
                "--db-path",
                str(db_path),
            ]
        )

    assert result == 0
    call = fake_archon.run_workflow.call_args.kwargs
    assert call["workflow_name"].startswith("ai-code-review-")
    assert call["cwd"] == tmp_path.resolve()
    payload = call["payload"]
    assert payload["head_sha"] == "abc123"
    assert payload["pull_request_number"] == 7
    workflow_files = list((tmp_path / ".archon" / "workflows").glob("ai-code-review-*.yaml"))
    assert len(workflow_files) == 1
    workflow_text = workflow_files[0].read_text(encoding="utf-8")
    assert "provider: codex" in workflow_text
    assert "model: gpt-test" in workflow_text

    assert RunStore(db_path).active_runs_for_pr(repository="owner/repo", pr_number=7) == []
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select status, archon_run_id, harness, model from code_review_runs"
        ).fetchone()
    assert row == ("succeeded", "archon-run-1", "codex", "gpt-test")


def test_review_abandons_existing_active_archon_run_for_same_pr(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    store = RunStore(db_path)
    old = store.create_run(
        repository="owner/repo",
        pr_number=7,
        head_sha="oldsha",
        mode="incremental",
        harness="opencode",
        model="old-model",
        repo_path=tmp_path,
        workflow_name="ai-code-review-old",
        workflow_path=tmp_path / ".archon" / "workflows" / "ai-code-review-old.yaml",
        workflow_yaml="name: ai-code-review-old\n",
    )
    store.set_archon_run_id(old.id, "archon-old")

    fake_archon = Mock()
    fake_archon.active_runs.return_value = [
        ArchonRun(
            id="archon-old",
            workflow_name="ai-code-review-old",
            status="running",
            raw={},
        )
    ]
    fake_archon.run_workflow.return_value = ArchonResult(
        returncode=0,
        output="",
        archon_run_id="archon-new",
    )

    with patch("code_reviewer.cli.ArchonClient", return_value=fake_archon):
        result = main(
            [
                "review",
                "--repo",
                str(tmp_path),
                "--pr-url",
                "https://github.com/owner/repo/pull/7",
                "--head-sha",
                "newsha",
                "--db-path",
                str(db_path),
            ]
        )

    assert result == 0
    fake_archon.abandon_and_verify.assert_called_once_with("archon-old", cwd=tmp_path)
    with sqlite3.connect(db_path) as connection:
        old_row = connection.execute(
            "select status, superseded_by from code_review_runs where id = ?",
            (old.id,),
        ).fetchone()
        statuses = connection.execute("select status from code_review_runs").fetchall()
    assert old_row[0] == "canceled"
    assert old_row[1] is not None
    assert sorted(status for (status,) in statuses) == ["canceled", "succeeded"]


def test_control_outputs_stable_token(capsys) -> None:
    result = main(["control", "ignore", "--finding-id", "finding-1"])

    assert result == 0
    output = capsys.readouterr().out
    assert "code-review:control" in output
    assert '"command": "ignore"' in output
    assert '"finding_id": "finding-1"' in output


def test_sanitize_argv_redacts_secret_like_values() -> None:
    assert sanitize_argv(["control", "ignore", "--reason", "token-123"]) == [
        "control",
        "ignore",
        "--reason",
        "[redacted]",
    ]
    assert sanitize_argv(["review", "--api-key=token-123", "--pr-url", "https://example.test/pr/1"]) == [
        "review",
        "--api-key=[redacted]",
        "--pr-url",
        "https://example.test/pr/1",
    ]


def test_braintrust_setup_failure_does_not_crash_cli(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fail_braintrust_import(name, *args, **kwargs):
        if name == "braintrust":
            raise ImportError("missing braintrust")
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-key")
    monkeypatch.setattr(builtins, "__import__", fail_braintrust_import)

    assert main(["control", "pause"]) == 0
