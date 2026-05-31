from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from code_reviewer.commands import (
    cleanup_worktree,
    collect_github_context,
    discover_transcripts,
    prepare_worktree,
    publish_review,
    summarize_intent,
)


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


def test_discover_transcripts_selects_exact_match_without_ai(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data_dir = tmp_path / ".kanna" / "data"
    transcripts = data_dir / "transcripts"
    transcripts.mkdir(parents=True)
    (data_dir / "snapshot.json").write_text(
        json.dumps({"chats": [{"id": "exact", "title": "Exact", "projectId": "p1"}]}),
        encoding="utf-8",
    )
    (transcripts / "exact.jsonl").write_text(
        json.dumps(
            {
                "_id": "u1",
                "kind": "user_prompt",
                "createdAt": 1,
                "content": "implement https://github.com/owner/repo/pull/7",
            }
        ),
        encoding="utf-8",
    )

    result = discover_transcripts.main(
        [
            "--payload-json",
            json.dumps(
                {
                    "pull_request_url": "https://github.com/owner/repo/pull/7",
                    "head_sha": "abc123",
                }
            ),
            "--kanna-root",
            str(tmp_path / ".kanna"),
            "--optional",
            "--select",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "- Selected transcript: `" in output
    assert "exact.json" in output
    assert "- Confidence: high" in output


def test_discover_transcripts_does_not_select_fallback_only_match(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data_dir = tmp_path / ".kanna" / "data"
    transcripts = data_dir / "transcripts"
    transcripts.mkdir(parents=True)
    (data_dir / "snapshot.json").write_text("{}", encoding="utf-8")
    (transcripts / "fallback.jsonl").write_text(
        json.dumps(
            {
                "_id": "u1",
                "kind": "user_prompt",
                "createdAt": 1,
                "content": "owner/repo only",
            }
        ),
        encoding="utf-8",
    )

    result = discover_transcripts.main(
        [
            "--payload-json",
            json.dumps({"pull_request_url": "https://github.com/owner/repo/pull/7"}),
            "--kanna-root",
            str(tmp_path / ".kanna"),
            "--optional",
            "--select",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "- Selected transcript: `none`" in output
    assert "Only repository-level fallback transcript candidates were found." in output


def test_discover_transcripts_does_not_select_ambiguous_exact_matches(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data_dir = tmp_path / ".kanna" / "data"
    transcripts = data_dir / "transcripts"
    transcripts.mkdir(parents=True)
    (data_dir / "snapshot.json").write_text("{}", encoding="utf-8")
    for name in ("first", "second"):
        (transcripts / f"{name}.jsonl").write_text(
            json.dumps(
                {
                    "_id": name,
                    "kind": "user_prompt",
                    "createdAt": 1,
                    "content": "https://github.com/owner/repo/pull/7",
                }
            ),
            encoding="utf-8",
        )

    result = discover_transcripts.main(
        [
            "--payload-json",
            json.dumps({"pull_request_url": "https://github.com/owner/repo/pull/7"}),
            "--kanna-root",
            str(tmp_path / ".kanna"),
            "--optional",
            "--select",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "- Selected transcript: `none`" in output
    assert "Multiple PR-specific transcript candidates were found." in output


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


def test_collect_github_context_writes_context_file(tmp_path: Path) -> None:
    payload = {
        "repository": "owner/repo",
        "pull_request_number": 7,
        "head_sha": "abc123",
    }
    context = {"pr": {"headRefOid": "abc123"}, "issue_comments": []}

    with patch.object(collect_github_context, "collect_context", return_value=context):
        result = collect_github_context.main(
            [
                "--payload-json",
                json.dumps(payload),
                "--output-root",
                str(tmp_path),
            ]
        )

    assert result == 0
    output = tmp_path / "owner-repo-pr-7-abc123.json"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["repository"] == "owner/repo"
    assert written["pr_number"] == 7
    assert written["payload"] == payload


def test_collect_github_context_flattens_paginated_api_results() -> None:
    with patch.object(collect_github_context, "gh_json_value", return_value=[[{"id": 1}], [{"id": 2}]]):
        assert collect_github_context.gh_api_list(["api", "endpoint"]) == [{"id": 1}, {"id": 2}]


def test_summarize_intent_writes_deterministic_review_brief(tmp_path: Path, capsys) -> None:
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "repository": "owner/repo",
                "pr_number": 7,
                "pr": {
                    "url": "https://github.com/owner/repo/pull/7",
                    "title": "Improve deploy review",
                    "body": "Make the review pipeline less flaky.",
                    "headRefOid": "abc123",
                    "baseRefOid": "def456",
                    "headRefName": "feature",
                    "baseRefName": "main",
                    "state": "OPEN",
                    "isDraft": False,
                    "commits": [{"oid": "abc123456789", "messageHeadline": "Fix flake"}],
                },
                "files": [{"filename": "src/app.py", "status": "modified", "additions": 2, "deletions": 1}],
                "issue_comments": [{}],
                "review_comments": [{}, {}],
                "reviews": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"repository": "owner/repo", "pr_number": 7, "head_sha": "abc123"}),
        encoding="utf-8",
    )
    transcript = tmp_path / "transcript.md"
    transcript.write_text("- Selected transcript: `none`\n", encoding="utf-8")

    result = summarize_intent.main(
        [
            "--payload-json",
            json.dumps({"repository": "owner/repo", "pull_request_number": 7, "mode": "incremental"}),
            "--github-context",
            f"'{context}'",
            "--worktree-manifest",
            f"'{manifest}'",
            "--transcript-selection-file",
            f"'{transcript}'",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "# Review Brief" in output
    assert "Improve deploy review" in output
    assert "`src/app.py`" in output
    assert "Issue comments: `1`" in output
    assert "- Selected transcript: `none`" in output


def test_publish_review_dry_run_reports_blocking_comment_without_failing(
    tmp_path: Path,
    capsys,
) -> None:
    aggregate_output = tmp_path / "aggregate.md"
    aggregate_output.write_text(
        """
Review result.

```json
{
  "comments": [
    {
      "type": "inline",
      "path": "app.py",
      "line": 12,
      "body": "This breaks the fork path.",
      "blocking": true
    }
  ]
}
```
""",
        encoding="utf-8",
    )
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"repository": "owner/repo", "pr_number": 7}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository": "owner/repo",
                "pr_number": 7,
                "head_sha": "abc123",
                "worktree_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "repository": "owner/repo",
        "pull_request_number": 7,
        "head_sha": "abc123",
        "dry_run": True,
    }

    with patch.object(publish_review, "run") as run:
        result = publish_review.main(
            [
                "--payload-json",
                json.dumps(payload),
                "--github-context",
                str(context),
                "--aggregate-output-file",
                str(aggregate_output),
                "--worktree-manifest",
                str(manifest),
            ]
        )

    assert result == 0
    run.assert_not_called()
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["blocking_count"] == 1
    assert output["check_conclusion"] == "failure"


def test_publish_review_does_not_let_top_level_count_mask_blocking_comment(
    tmp_path: Path,
    capsys,
) -> None:
    aggregate_output = tmp_path / "aggregate.md"
    aggregate_output.write_text(
        json.dumps(
            {
                "blocking_count": 0,
                "comments": [
                    {
                        "type": "top_level",
                        "body": "Blocking summary.",
                        "blocking": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"repository": "owner/repo", "pr_number": 7}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository": "owner/repo",
                "pr_number": 7,
                "head_sha": "abc123",
                "worktree_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "repository": "owner/repo",
        "pull_request_number": 7,
        "head_sha": "abc123",
        "dry_run": True,
    }

    result = publish_review.main(
        [
            "--payload-json",
            json.dumps(payload),
            "--github-context",
            str(context),
            "--aggregate-output-file",
            str(aggregate_output),
            "--worktree-manifest",
            str(manifest),
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["blocking_count"] == 1


def test_publish_review_rejects_malformed_aggregate_before_github_writes(
    tmp_path: Path,
) -> None:
    aggregate_output = tmp_path / "aggregate.md"
    aggregate_output.write_text("No structured comments here.", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"repository": "owner/repo", "pr_number": 7}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository": "owner/repo",
                "pr_number": 7,
                "head_sha": "abc123",
                "worktree_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "repository": "owner/repo",
        "pull_request_number": 7,
        "head_sha": "abc123",
    }

    with patch.object(publish_review, "run") as run:
        try:
            publish_review.main(
                [
                    "--payload-json",
                    json.dumps(payload),
                    "--github-context",
                    str(context),
                    "--aggregate-output-file",
                    str(aggregate_output),
                    "--worktree-manifest",
                    str(manifest),
                ]
            )
        except SystemExit as exc:
            assert "comments JSON" in str(exc)
        else:
            raise AssertionError("expected malformed aggregate to fail")

    run.assert_not_called()


def test_publish_review_posts_top_level_and_inline_comments(tmp_path: Path) -> None:
    aggregate_output = tmp_path / "aggregate.md"
    aggregate_output.write_text(
        json.dumps(
            {
                "comments": [
                    {
                        "type": "top_level",
                        "body": "Review summary.",
                        "blocking": False,
                    },
                    {
                        "type": "inline",
                        "path": "app.py",
                        "line": 12,
                        "body": "Inline note.",
                        "blocking": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"repository": "owner/repo", "pr_number": 7}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository": "owner/repo",
                "pr_number": 7,
                "head_sha": "abc123",
                "worktree_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "repository": "owner/repo",
        "pull_request_number": 7,
        "head_sha": "abc123",
    }

    with patch.object(publish_review, "run") as run:
        run.return_value.stdout = "ok\n"
        result = publish_review.main(
            [
                "--payload-json",
                json.dumps(payload),
                "--github-context",
                str(context),
                "--aggregate-output-file",
                str(aggregate_output),
                "--worktree-manifest",
                str(manifest),
            ]
        )

    assert result == 0
    assert run.call_count == 2
    assert run.call_args_list[0].args[0][:4] == ["gh", "pr", "comment", "7"]
    assert run.call_args_list[1].args[0][:3] == ["gh", "api", "repos/owner/repo/pulls/7/comments"]
