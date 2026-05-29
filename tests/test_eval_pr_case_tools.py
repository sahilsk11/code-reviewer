from __future__ import annotations

from evals import capture_pr_case, discover_pr_review_cases
from evals._review_comments import review_comment_priority, review_comment_title


def test_discover_resolves_github_remotes() -> None:
    assert discover_pr_review_cases.repo_from_remote("git@github.com:sahilsk11/friday.git") == "sahilsk11/friday"
    assert discover_pr_review_cases.repo_from_remote("https://github.com/sahilsk11/overwatch.git") == "sahilsk11/overwatch"
    assert discover_pr_review_cases.repo_from_value("https://github.com/sahilsk11/friday/pull/35") == "sahilsk11/friday"


def test_discover_summarizes_codex_review_comment() -> None:
    body = """**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Keep CI errors from being treated as "no checks"**

Details.
"""

    assert review_comment_title(body) == 'Keep CI errors from being treated as "no checks"'
    assert review_comment_priority(body) == "P1"
    assert discover_pr_review_cases.has_followup_signal("Fixed in 123abc with a regression test.")


def test_capture_imports_review_comment_as_weak_label() -> None:
    comment = {
        "body": "**<sub><sub>![P2 Badge](badge)</sub></sub>  Prefer resolution attempts when selecting latest diagnostics**\n\nUse `resolution_attempts`.",
        "path": "src/overwatch/store.py",
        "line": 385,
        "html_url": "https://example.com/comment",
    }

    label = capture_pr_case.review_comment_to_label(comment)

    assert label["severity"] == "medium"
    assert label["file"] == "src/overwatch/store.py"
    assert label["line"] == 385
    assert "resolution_attempts" in label["must_include"]


def test_capture_default_case_name_uses_resolved_commit_index() -> None:
    commits = [
        {"oid": "111111"},
        {"oid": "222222"},
    ]

    commit_index = capture_pr_case.resolve_commit_index(commits, commit_sha="222", commit_index=0)
    name = capture_pr_case.default_case_name(repo="owner/repo", pr_number=7, commit_index=commit_index)

    assert name == "owner-repo-pr-7-commit-2"
