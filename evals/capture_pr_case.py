from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evals._review_comments import (
        compact_review_comment,
        flatten_pages,
        review_comment_severity,
        review_comment_terms,
        review_comment_title,
        run,
    )
except ModuleNotFoundError:
    from _review_comments import (  # type: ignore[no-redef]
        compact_review_comment,
        flatten_pages,
        review_comment_severity,
        review_comment_terms,
        review_comment_title,
        run,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = REPO_ROOT / "evals" / "real_pr_cases"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze a GitHub PR commit as an eval case.")
    parser.add_argument("pr_url")
    parser.add_argument(
        "--commit-index",
        type=int,
        default=0,
        help="Zero-based PR commit index to capture. Default: first commit.",
    )
    parser.add_argument(
        "--commit-sha",
        help="PR commit SHA to capture. Overrides --commit-index.",
    )
    parser.add_argument(
        "--include-review-comments",
        action="store_true",
        help="Import inline PR review comments for the captured commit as expected labels.",
    )
    parser.add_argument(
        "--review-author",
        default="chatgpt-codex-connector[bot]",
        help="Review comment author to import when --include-review-comments is set.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--name", help="Output case name without .json.")
    args = parser.parse_args(argv)

    pr = gh_pr_view(args.pr_url)
    commits = pr["commits"]
    commit_index = resolve_commit_index(commits, commit_sha=args.commit_sha, commit_index=args.commit_index)

    repo = pr["headRepository"]["nameWithOwner"]
    base_sha = pr["baseRefOid"]
    target_commit = commits[commit_index]
    target_sha = target_commit["oid"]
    patch, diff_stat = capture_diff(
        repo=repo,
        pr_number=pr["number"],
        base_ref=pr["baseRefName"],
        base_sha=base_sha,
        target_sha=target_sha,
    )
    expected = {
        "notes": "Unlabeled captured case. Add teacher output or human labels before scoring quality.",
    }
    if args.include_review_comments:
        review_comments = gh_pr_review_comments(
            repo=repo,
            pr_number=pr["number"],
            author=args.review_author,
            commit_sha=target_sha,
        )
        review_comments = [
            comment for comment in review_comments if review_comment_severity(comment["body"]) != "unknown"
        ]
        findings = [review_comment_to_label(comment) for comment in review_comments]
        expected = {
            "notes": f"Labels imported from inline review comments by {args.review_author}. Treat as weak labels.",
            "check_conclusion": "failure" if findings else "success",
            "findings": findings,
            "review_comments": review_comments,
        }

    case = {
        "schema_version": 1,
        "captured_at": datetime.now(tz=UTC).isoformat(),
        "source": {
            "pr_url": pr["url"],
            "repo": repo,
            "pr_number": pr["number"],
            "title": pr["title"],
            "body": pr["body"],
            "author": pr["author"],
            "base_ref": pr["baseRefName"],
            "head_ref": pr["headRefName"],
            "base_sha": base_sha,
            "pr_head_sha": pr["headRefOid"],
            "captured_commit_index": commit_index,
            "captured_commit": target_commit,
            "commit_count": len(commits),
        },
        "input": {
            "title": pr["title"],
            "body": pr["body"],
            "repo": repo,
            "base_sha": base_sha,
            "head_sha": target_sha,
            "diff": patch,
            "diff_stat": diff_stat,
            "files": pr["files"],
        },
        "expected": expected,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or default_case_name(repo=repo, pr_number=pr["number"], commit_index=commit_index)
    output_path = args.output_dir / f"{name}.json"
    output_path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


def resolve_commit_index(commits: list[dict[str, Any]], *, commit_sha: str | None, commit_index: int) -> int:
    if commit_sha:
        matches = [index for index, commit in enumerate(commits) if str(commit["oid"]).startswith(commit_sha)]
        if not matches:
            raise SystemExit(f"--commit-sha {commit_sha} was not found in PR commits")
        if len(matches) > 1:
            raise SystemExit(f"--commit-sha {commit_sha} is ambiguous")
        return matches[0]
    if commit_index < 0 or commit_index >= len(commits):
        raise SystemExit(f"--commit-index must be between 0 and {len(commits) - 1}")
    return commit_index


def gh_pr_view(pr_url: str) -> dict[str, Any]:
    fields = ",".join(
        [
            "title",
            "body",
            "number",
            "url",
            "baseRefOid",
            "headRefOid",
            "baseRefName",
            "headRefName",
            "commits",
            "author",
            "headRepository",
            "headRepositoryOwner",
            "files",
        ]
    )
    completed = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", fields],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def gh_pr_review_comments(*, repo: str, pr_number: int, author: str, commit_sha: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate", "--slurp"],
        check=True,
        text=True,
        capture_output=True,
    )
    comments = flatten_pages(json.loads(completed.stdout))
    return [
        compact_review_comment(comment)
        for comment in comments
        if comment.get("commit_id") == commit_sha and (comment.get("user") or {}).get("login") == author
    ]


def review_comment_to_label(comment: dict[str, Any]) -> dict[str, Any]:
    title = review_comment_title(comment["body"])
    return {
        "id": slug(f"{comment.get('path', 'finding')}-{title}"),
        "file": comment.get("path"),
        "line": comment.get("line") or comment.get("original_line"),
        "severity": review_comment_severity(comment["body"]),
        "summary": title,
        "must_include": review_comment_terms(comment["body"], title),
        "source_comment_url": comment.get("html_url") or comment.get("url"),
    }


def capture_diff(*, repo: str, pr_number: int, base_ref: str, base_sha: str, target_sha: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="capture-pr-case-") as temp_dir:
        temp_path = Path(temp_dir)
        run(["git", "init", "-q"], cwd=temp_path)
        run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=temp_path)
        run(["git", "fetch", "--depth=50", "origin", f"pull/{pr_number}/head"], cwd=temp_path)
        run(["git", "fetch", "--depth=1", "origin", base_ref], cwd=temp_path)
        ensure_commit(temp_path, base_sha)
        ensure_commit(temp_path, target_sha)
        patch = run(
            ["git", "diff", "--binary", "--find-renames", base_sha, target_sha],
            cwd=temp_path,
        ).stdout
        diff_stat = run(["git", "diff", "--stat", base_sha, target_sha], cwd=temp_path).stdout
        return patch, diff_stat


def ensure_commit(repo_path: Path, sha: str) -> None:
    if subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0:
        return
    run(["git", "fetch", "--depth=1", "origin", sha], cwd=repo_path)
    run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_path)


def default_case_name(*, repo: str, pr_number: int, commit_index: int) -> str:
    repo_slug = repo.replace("/", "-").lower()
    return f"{repo_slug}-pr-{pr_number}-commit-{commit_index + 1}"


def slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
