from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

from code_reviewer.cli import build_review_payload, main


def test_install_workflow(tmp_path: Path) -> None:
    result = main(["install-workflow", "--repo", str(tmp_path)])

    assert result == 0
    assert (tmp_path / ".archon" / "workflows" / "ai-code-review.yaml").exists()


def test_build_review_payload_from_event(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "action": "synchronize",
                "repository": {"full_name": "owner/repo"},
                "pull_request": {
                    "number": 42,
                    "html_url": "https://github.com/owner/repo/pull/42",
                    "head": {"sha": "event-sha"},
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_review_payload(
        repo=tmp_path,
        event_path=event_path,
        pr_url=None,
        head_sha=None,
        mode="incremental",
    )

    assert payload["event_name"] == "synchronize"
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
            event_path=None,
            pr_url="https://github.com/owner/repo/pull/42",
            head_sha=None,
            mode="full",
            dry_run=True,
        )

    assert payload["head_sha"] == "resolved-sha"
    assert payload["dry_run"] is True


def test_review_runs_archon_with_payload(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "owner/repo"},
                "pull_request": {
                    "number": 7,
                    "html_url": "https://github.com/owner/repo/pull/7",
                },
            }
        ),
        encoding="utf-8",
    )

    completed = Mock(returncode=0)
    with patch("code_reviewer.cli.subprocess.run", return_value=completed) as run:
        result = main(
            [
                "review",
                "--repo",
                str(tmp_path),
                "--event-path",
                str(event_path),
                "--head-sha",
                "abc123",
                "--archon-bin",
                "archon-test",
            ]
        )

    assert result == 0
    command = run.call_args.args[0]
    assert command[:5] == [
        "archon-test",
        "workflow",
        "run",
        "ai-code-review",
        "--cwd",
    ]
    assert command[5] == str(tmp_path.resolve())
    payload = json.loads(command[6])
    assert payload["head_sha"] == "abc123"
    assert payload["pull_request_number"] == 7
    assert run.call_args.kwargs["env"]["CODE_REVIEW_PYTHON"]


def test_control_outputs_stable_token(capsys) -> None:
    result = main(["control", "ignore", "--finding-id", "finding-1"])

    assert result == 0
    output = capsys.readouterr().out
    assert "code-review:control" in output
    assert '"command": "ignore"' in output
    assert '"finding_id": "finding-1"' in output
