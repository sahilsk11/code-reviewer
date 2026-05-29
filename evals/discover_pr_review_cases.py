from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evals._review_comments import (
        compact_review_comment,
        flatten_pages,
        review_comment_priority,
        review_comment_title,
        run,
    )
except ModuleNotFoundError:
    from _review_comments import (  # type: ignore[no-redef]
        compact_review_comment,
        flatten_pages,
        review_comment_priority,
        review_comment_title,
        run,
    )


DEFAULT_PROJECTS_DIR = Path.home() / "projects"
DEFAULT_BOT_AUTHOR = "chatgpt-codex-connector[bot]"
FOLLOWUP_WORDS = ("addressed", "fixed", "resolved", "superseded")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find real PR review comments worth turning into eval cases.")
    parser.add_argument(
        "repos",
        nargs="*",
        help="GitHub repos, GitHub PR URLs, or local repo paths. Default: all GitHub remotes under ~/projects.",
    )
    parser.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR)
    parser.add_argument("--limit-prs", type=int, default=20)
    parser.add_argument("--bot-author", default=DEFAULT_BOT_AUTHOR)
    parser.add_argument("--min-bot-comments", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    parser.add_argument("--output", type=Path, help="Write the report to this path instead of stdout.")
    args = parser.parse_args(argv)

    repos = resolve_repos(args.repos, projects_dir=args.projects_dir)
    candidates = []
    for repo in repos:
        candidates.extend(
            discover_repo_candidates(
                repo=repo,
                limit_prs=args.limit_prs,
                bot_author=args.bot_author,
                min_bot_comments=args.min_bot_comments,
            )
        )

    candidates.sort(key=lambda item: item["candidate_score"], reverse=True)
    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "repos": repos,
        "bot_author": args.bot_author,
        "candidates": candidates,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text, end="")
    return 0


def resolve_repos(values: list[str], *, projects_dir: Path) -> list[str]:
    if values:
        repos = [repo_from_value(value) for value in values]
    else:
        repos = discover_local_github_repos(projects_dir)
    return sorted(set(repos))


def repo_from_value(value: str) -> str:
    if match := re.search(r"github\.com[:/]([^/\s]+/[^/\s.]+)(?:\.git)?", value):
        return match.group(1)
    path = Path(value).expanduser()
    if path.exists():
        remote = run(["git", "remote", "get-url", "origin"], cwd=path).stdout.strip()
        return repo_from_remote(remote)
    if re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        return value
    raise SystemExit(f"Could not resolve repo from {value!r}")


def discover_local_github_repos(projects_dir: Path) -> list[str]:
    repos = []
    for git_dir in sorted(projects_dir.glob("*/.git")):
        repo_dir = git_dir.parent
        try:
            remote = run(["git", "remote", "get-url", "origin"], cwd=repo_dir).stdout.strip()
            repos.append(repo_from_remote(remote))
        except (subprocess.CalledProcessError, SystemExit):
            continue
    return repos


def repo_from_remote(remote: str) -> str:
    patterns = [
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
        r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        if match := re.match(pattern, remote):
            return match.group(1)
    raise SystemExit(f"Unsupported GitHub remote: {remote}")


def discover_repo_candidates(
    *,
    repo: str,
    limit_prs: int,
    bot_author: str,
    min_bot_comments: int,
) -> list[dict[str, Any]]:
    candidates = []
    for pr in list_prs(repo, limit=limit_prs):
        comments = list_review_comments(repo, pr_number=pr["number"])
        bot_comments = [comment for comment in comments if comment["author"] == bot_author]
        bot_findings = [comment for comment in bot_comments if review_comment_severity(comment["body"]) != "unknown"]
        if len(bot_findings) < min_bot_comments:
            continue
        followups = [
            comment
            for comment in comments
            if comment["author"] != bot_author and has_followup_signal(comment["body"])
        ]
        commits = unique([comment["commit_id"] for comment in bot_findings if comment.get("commit_id")])
        findings = [summarize_finding(comment) for comment in bot_findings]
        candidates.append(
            {
                "repo": repo,
                "pr_number": pr["number"],
                "pr_url": pr["url"],
                "title": pr["title"],
                "state": pr["state"],
                "merged_at": pr.get("mergedAt"),
                "bot_comment_count": len(bot_findings),
                "ignored_bot_comment_count": len(bot_comments) - len(bot_findings),
                "followup_count": len(followups),
                "reviewed_commits": commits,
                "paths": sorted({comment["path"] for comment in bot_findings if comment.get("path")}),
                "severities": severity_counts(bot_findings),
                "candidate_score": candidate_score(bot_comments=bot_findings, followups=followups, commits=commits),
                "findings": findings,
                "capture_commands": capture_commands(pr_url=pr["url"], commits=commits, bot_author=bot_author),
            }
        )
    return candidates


def list_prs(repo: str, *, limit: int) -> list[dict[str, Any]]:
    completed = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            str(limit),
            "--json",
            "number,title,state,mergedAt,url",
        ]
    )
    return json.loads(completed.stdout)


def list_review_comments(repo: str, *, pr_number: int) -> list[dict[str, Any]]:
    raw_comments = flatten_pages(
        json.loads(run(["gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate", "--slurp"]).stdout)
    )
    return [compact_review_comment(comment) for comment in raw_comments]


def summarize_finding(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "severity": review_comment_severity(comment["body"]),
        "title": review_comment_title(comment["body"]),
        "path": comment.get("path"),
        "line": comment.get("line") or comment.get("original_line"),
        "commit_id": comment.get("commit_id"),
        "url": comment.get("html_url"),
    }


def review_comment_severity(body: str) -> str:
    return review_comment_priority(body) or "unknown"


def severity_counts(comments: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for comment in comments:
        severity = review_comment_severity(comment["body"])
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def has_followup_signal(body: str) -> bool:
    lowered = body.lower()
    return any(word in lowered for word in FOLLOWUP_WORDS)


def candidate_score(
    *,
    bot_comments: list[dict[str, Any]],
    followups: list[dict[str, Any]],
    commits: list[str],
) -> int:
    p1_count = sum(1 for comment in bot_comments if review_comment_severity(comment["body"]) == "P1")
    return len(bot_comments) * 2 + len(followups) * 4 + p1_count * 2 + max(0, len(commits) - 1)


def capture_commands(*, pr_url: str, commits: list[str], bot_author: str) -> list[str]:
    return [
        (
            "python3 evals/capture_pr_case.py "
            f"{pr_url} --commit-sha {commit} --include-review-comments --review-author {bot_author!r}"
        )
        for commit in commits
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PR Review Case Candidates",
        "",
        f"Generated: {report['generated_at']}",
        f"Bot author: `{report['bot_author']}`",
        "",
    ]
    if not report["candidates"]:
        lines.append("No candidates found.")
        return "\n".join(lines) + "\n"

    for candidate in report["candidates"]:
        lines.extend(
            [
                f"## {candidate['repo']}#{candidate['pr_number']}: {candidate['title']}",
                "",
                (
                    f"Score {candidate['candidate_score']} | "
                    f"{candidate['bot_comment_count']} bot comments | "
                    f"{candidate['followup_count']} followups | "
                    f"severities {candidate['severities']}"
                ),
                f"PR: {candidate['pr_url']}",
                f"Paths: {', '.join(candidate['paths'])}",
                "",
                "Findings:",
            ]
        )
        for finding in candidate["findings"]:
            location = f"{finding['path']}:{finding['line']}" if finding.get("line") else finding["path"]
            lines.append(f"- {finding['severity']} {finding['title']} ({location})")
        lines.extend(["", "Capture:", ""])
        lines.extend(f"```bash\n{command}\n```" for command in candidate["capture_commands"])
        lines.append("")
    return "\n".join(lines)

if __name__ == "__main__":
    sys.exit(main())
