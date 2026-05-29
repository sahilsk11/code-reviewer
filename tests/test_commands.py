from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from code_reviewer.commands import cleanup_worktree, discover_transcripts, finalize_review, prepare_worktree


def test_prepare_worktree_writes_manifest_without_dirtying_worktree(tmp_path: Path) -> None:
    source_repo = tmp_path / "repo"
    source_repo.mkdir()
    manifest_path = tmp_path / "manifest.json"
    payload = {
        "repo": str(source_repo),
        "pull_request_url": "https://github.com/owner/repo/pull/3",
        "head_sha": "abc1234567890",
        "mode": "full",
    }
    pr = {
        "url": "https://github.com/owner/repo/pull/3",
        "number": 3,
        "headRefOid": "abc1234567890",
        "baseRefOid": "def456",
        "headRepository": {"nameWithOwner": "owner/repo"},
        "headRefName": "feature",
        "baseRefName": "main",
    }

    with (
        patch.object(prepare_worktree, "resolve_pr", return_value=pr),
        patch.object(prepare_worktree, "fetch_pr"),
        patch.object(prepare_worktree, "manifest_path_for", return_value=manifest_path),
        patch.object(prepare_worktree, "run") as run,
    ):
        result = prepare_worktree.main(
            [
                "--payload-json",
                json.dumps(payload),
                "--worktree-root",
                str(tmp_path / "wt"),
            ]
        )

    assert result == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["head_sha"] == "abc1234567890"
    assert manifest["repository"] == "owner/repo"
    assert manifest["worktree_path"].endswith("code-review-owner-repo-pr-3-abc123456789")
    assert not Path(manifest["worktree_path"], ".code-review-manifest.json").exists()
    assert run.call_args.args[0][:4] == ["git", "worktree", "add", "--detach"]


def test_discover_transcripts_prefers_exact_pr_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data_dir = tmp_path / ".kanna" / "data"
    transcripts = data_dir / "transcripts"
    transcripts.mkdir(parents=True)
    (data_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "chats": [
                    {"id": "exact", "title": "Exact", "projectId": "p1"},
                    {"id": "fallback", "title": "Fallback", "projectId": "p1"},
                ],
                "projects": [{"id": "p1", "localPath": "/repo"}],
            }
        ),
        encoding="utf-8",
    )
    (transcripts / "exact.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "_id": "u1",
                        "kind": "user_prompt",
                        "createdAt": 1,
                        "content": "see https://github.com/owner/repo/pull/7",
                    }
                ),
                json.dumps({"_id": "a1", "kind": "assistant_text", "createdAt": 2, "text": "ok"}),
                json.dumps({"_id": "tool", "kind": "tool_call", "createdAt": 3, "name": "bash"}),
            ]
        ),
        encoding="utf-8",
    )
    (transcripts / "fallback.jsonl").write_text(
        json.dumps(
            {
                "_id": "u2",
                "kind": "user_prompt",
                "createdAt": 4,
                "content": "owner/repo but not the PR",
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "pull_request_url": "https://github.com/owner/repo/pull/7",
        "head_sha": "abc123",
    }

    result = discover_transcripts.main(
        [
            "--payload-json",
            json.dumps(payload),
            "--kanna-root",
            str(tmp_path / ".kanna"),
            "--optional",
        ]
    )

    assert result == 0
    report_path = tmp_path / ".code-reviews" / "transcripts" / "owner-repo-pr-7-candidates.md"
    report = report_path.read_text(encoding="utf-8")
    assert "Used fallback repo-only matches: `false`" in report
    assert "Session: `exact`" in report
    assert "Session: `fallback`" not in report
    normalized_path = tmp_path / ".code-reviews" / "transcripts" / "exact.json"
    normalized = json.loads(normalized_path.read_text())
    assert [message["role"] for message in normalized["messages"]] == ["user", "assistant"]


def test_cleanup_worktree_strips_archon_wrapping_quotes(tmp_path: Path) -> None:
    source_repo = tmp_path / "repo"
    source_repo.mkdir()
    worktree = Path.home() / "wt" / "code-review-test-quote-cleanup"
    worktree.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "managed_by": "code-reviewer",
                "source_repo": str(source_repo),
                "worktree_path": str(worktree),
            }
        ),
        encoding="utf-8",
    )

    with patch.object(cleanup_worktree, "run") as run:
        result = cleanup_worktree.main(["--worktree-manifest", f"'{manifest}'"])

    assert result == 0
    assert not worktree.exists()
    assert run.call_args_list[0].args[0][:3] == ["git", "worktree", "remove"]


def test_finalize_review_fails_for_blocking_publish_payload(tmp_path: Path) -> None:
    aggregate_output = """
Summary

```json publish_payload
{"blocking_count": 1, "non_blocking_count": 0, "check_conclusion": "failure", "findings": []}
```
"""

    with patch.object(cleanup_worktree, "main", return_value=0) as cleanup:
        result = finalize_review.main(
            [
                "--aggregate-output",
                aggregate_output,
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 1
    cleanup.assert_called_once()


def test_finalize_review_rejects_nested_publish_payload(tmp_path: Path) -> None:
    aggregate_output = """
```json
{
  "publish_payload": {
    "blocking_count": 1,
    "check_conclusion": "failure",
    "findings": []
  }
}
```
"""

    with patch.object(cleanup_worktree, "main", return_value=0):
        result = finalize_review.main(
            [
                "--aggregate-output",
                aggregate_output,
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 1


def test_finalize_review_uses_blocking_count_for_check_result(tmp_path: Path) -> None:
    aggregate_output = """
```json publish_payload
{"blocking_count": 0, "non_blocking_count": 0, "check_conclusion": "failure", "findings": []}
```
"""

    with patch.object(cleanup_worktree, "main", return_value=0):
        result = finalize_review.main(
            [
                "--aggregate-output",
                aggregate_output,
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 0


def test_finalize_review_succeeds_without_blocking_findings(tmp_path: Path) -> None:
    aggregate_output = """
```json publish_payload
{"blocking_count": 0, "non_blocking_count": 0, "check_conclusion": "success", "findings": []}
```
"""

    with patch.object(cleanup_worktree, "main", return_value=0):
        result = finalize_review.main(
            [
                "--aggregate-output",
                aggregate_output,
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 0


def test_finalize_review_reads_publish_payload_from_file(tmp_path: Path) -> None:
    aggregate_output = tmp_path / "aggregate.md"
    aggregate_output.write_text(
        """
```json publish_payload
{"blocking_count": 1, "non_blocking_count": 0, "check_conclusion": "failure", "findings": []}
```
"""
    )

    with patch.object(cleanup_worktree, "main", return_value=0):
        result = finalize_review.main(
            [
                "--aggregate-output-file",
                str(aggregate_output),
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 1


def test_finalize_review_accepts_unfenced_publish_payload(tmp_path: Path) -> None:
    aggregate_output = """
Summary text with earlier braces like {not json}.

{
  "blocking_count": 0,
  "non_blocking_count": 1,
  "check_conclusion": "success",
  "findings": [
    {"id": "n1", "blocking": false}
  ]
}
"""

    with patch.object(cleanup_worktree, "main", return_value=0):
        result = finalize_review.main(
            [
                "--aggregate-output",
                aggregate_output,
                "--worktree-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )

    assert result == 0
