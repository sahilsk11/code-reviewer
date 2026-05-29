from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
    patch, diff_stat = capture_diff(repo=repo, pr_number=pr["number"], base_sha=base_sha, target_sha=target_sha)
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
    name = args.name or default_case_name(repo=repo, pr_number=pr["number"], commit_index=args.commit_index)
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def gh_pr_review_comments(*, repo: str, pr_number: int, author: str, commit_sha: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate", "--slurp"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    comments = flatten_pages(json.loads(completed.stdout))
    return [
        compact_review_comment(comment)
        for comment in comments
        if comment.get("commit_id") == commit_sha and (comment.get("user") or {}).get("login") == author
    ]


def compact_review_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "author": (comment.get("user") or {}).get("login"),
        "body": comment.get("body") or "",
        "commit_id": comment.get("commit_id"),
        "created_at": comment.get("created_at"),
        "html_url": comment.get("html_url"),
        "line": comment.get("line"),
        "original_line": comment.get("original_line"),
        "path": comment.get("path"),
        "url": comment.get("url"),
    }


def flatten_pages(pages: Any) -> list[dict[str, Any]]:
    if isinstance(pages, list) and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages if isinstance(pages, list) else []


def review_comment_to_label(comment: dict[str, Any]) -> dict[str, Any]:
    title = review_comment_title(comment["body"])
    severity = review_comment_severity(comment["body"])
    return {
        "id": slug(f"{comment.get('path', 'finding')}-{title}"),
        "file": comment.get("path"),
        "line": comment.get("line") or comment.get("original_line"),
        "severity": severity,
        "summary": title,
        "must_include": review_comment_terms(comment["body"], title),
        "source_comment_url": comment.get("html_url") or comment.get("url"),
    }


def review_comment_title(body: str) -> str:
    first_line = body.strip().splitlines()[0] if body.strip() else "Imported review finding"
    first_line = re.sub(r"<[^>]+>", "", first_line)
    first_line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", first_line)
    first_line = first_line.replace("**", "").strip()
    first_line = re.sub(r"\s+", " ", first_line)
    return first_line or "Imported review finding"


def review_comment_severity(body: str) -> str:
    match = re.search(r"\bP([0-3])\b", body)
    if not match:
        return "unknown"
    return {"0": "high", "1": "high", "2": "medium", "3": "low"}[match.group(1)]


def review_comment_terms(body: str, title: str) -> list[str]:
    code_terms = [term.strip() for term in re.findall(r"`([^`]+)`", body) if term.strip()]
    title_terms = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", title)
        if word.lower() not in {"badge", "should", "review", "finding"}
    ]
    terms: list[str] = []
    for term in code_terms + title_terms:
        if term not in terms:
            terms.append(term)
        if len(terms) >= 5:
            break
    return terms


def capture_diff(*, repo: str, pr_number: int, base_sha: str, target_sha: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="capture-pr-case-") as temp_dir:
        run(["git", "init", "-q"], cwd=Path(temp_dir))
        run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=Path(temp_dir))
        run(["git", "fetch", "--depth=50", "origin", f"pull/{pr_number}/head"], cwd=Path(temp_dir))
        run(["git", "cat-file", "-e", f"{base_sha}^{{commit}}"], cwd=Path(temp_dir))
        run(["git", "cat-file", "-e", f"{target_sha}^{{commit}}"], cwd=Path(temp_dir))
        patch = run(
            ["git", "diff", "--binary", "--find-renames", base_sha, target_sha],
            cwd=Path(temp_dir),
        ).stdout
        diff_stat = run(["git", "diff", "--stat", base_sha, target_sha], cwd=Path(temp_dir)).stdout
        return patch, diff_stat


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def default_case_name(*, repo: str, pr_number: int, commit_index: int) -> str:
    repo_slug = repo.replace("/", "-").lower()
    return f"{repo_slug}-pr-{pr_number}-commit-{commit_index + 1}"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
