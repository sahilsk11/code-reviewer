from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import load_json_arg, read_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create deterministic PR intent context for reviewer nodes."
    )
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--github-context", type=Path, required=True)
    parser.add_argument("--worktree-manifest", type=Path, required=True)
    parser.add_argument("--transcript-selection-file", type=Path, required=True)
    args = parser.parse_args(argv)

    payload = load_json_arg(args.payload_json)
    context = read_json(strip_wrapping_quotes(args.github_context))
    manifest = read_json(strip_wrapping_quotes(args.worktree_manifest))
    transcript_selection = strip_wrapping_quotes(args.transcript_selection_file).read_text(
        encoding="utf-8"
    )

    print(render_summary(payload, context, manifest, transcript_selection))
    return 0


def render_summary(
    payload: dict[str, Any],
    context: dict[str, Any],
    manifest: dict[str, Any],
    transcript_selection: str,
) -> str:
    pr_raw = context.get("pr")
    pr: dict[str, Any] = pr_raw if isinstance(pr_raw, dict) else {}
    files_raw = context.get("files")
    files: list[Any] = files_raw if isinstance(files_raw, list) else []
    commits_raw = pr.get("commits")
    commits: list[Any] = commits_raw if isinstance(commits_raw, list) else []
    issue_comments = context.get("issue_comments")
    review_comments = context.get("review_comments")
    reviews = context.get("reviews")

    lines = [
        "# Review Brief",
        "",
        "## PR",
        "",
        f"- Repository: `{context.get('repository') or payload.get('repository') or manifest.get('repository') or 'unknown'}`",
        f"- Pull request: `{context.get('pr_number') or payload.get('pull_request_number') or manifest.get('pr_number') or 'unknown'}`",
        f"- URL: `{pr.get('url') or payload.get('pull_request_url') or manifest.get('pr_url') or 'unknown'}`",
        f"- Title: {pr.get('title') or 'unknown'}",
        f"- State: `{pr.get('state') or 'unknown'}`",
        f"- Draft: `{str(pr.get('isDraft')).lower() if 'isDraft' in pr else 'unknown'}`",
        f"- Mode: `{payload.get('mode') or 'unknown'}`",
        f"- Head SHA: `{payload.get('head_sha') or manifest.get('head_sha') or pr.get('headRefOid') or 'unknown'}`",
        f"- Base SHA: `{manifest.get('base_sha') or pr.get('baseRefOid') or 'unknown'}`",
        f"- Head ref: `{manifest.get('head_ref') or pr.get('headRefName') or 'unknown'}`",
        f"- Base ref: `{manifest.get('base_ref') or pr.get('baseRefName') or 'unknown'}`",
        "",
        "## Intent",
        "",
        safe_body(pr.get("body")),
        "",
        "## Changed Files",
        "",
    ]
    if files:
        for file_info in files[:50]:
            if not isinstance(file_info, dict):
                continue
            path = file_info.get("filename") or file_info.get("path") or "unknown"
            status = file_info.get("status") or "modified"
            additions = file_info.get("additions")
            deletions = file_info.get("deletions")
            lines.append(f"- `{path}` ({status}, +{additions or 0}/-{deletions or 0})")
        if len(files) > 50:
            lines.append(f"- ...and {len(files) - 50} more files")
    else:
        lines.append("- No changed files found in collected GitHub context.")
    lines.extend(
        [
            "",
            "## Commits",
            "",
        ]
    )
    if commits:
        for commit in commits[:20]:
            if isinstance(commit, dict):
                oid = str(commit.get("oid") or commit.get("abbreviatedOid") or "")[:12]
                message = first_line(commit.get("messageHeadline") or commit.get("message") or "")
                lines.append(f"- `{oid or 'unknown'}` {message or '(no message)'}")
        if len(commits) > 20:
            lines.append(f"- ...and {len(commits) - 20} more commits")
    else:
        lines.append("- No commit list found in collected GitHub context.")

    lines.extend(
        [
            "",
            "## Prior Review State",
            "",
            f"- Issue comments: `{count_items(issue_comments)}`",
            f"- Review comments: `{count_items(review_comments)}`",
            f"- Reviews: `{count_items(reviews)}`",
            "- Reviewer control tokens, human replies, and outdated comment handling are available in the collected GitHub context JSON.",
            "",
            "## Implementation Transcript",
            "",
            transcript_selection.strip() or "- Selected transcript: `none`",
            "",
            "## Reviewer Guidance",
            "",
            "- Review exactly the supplied head SHA, not a moving branch.",
            "- Use collected GitHub context instead of calling GitHub from reviewer nodes.",
            "- Trace affected code paths beyond the diff when needed.",
            "- Prefer high-confidence actionable findings over broad commentary.",
            "",
        ]
    )
    return "\n".join(lines)


def safe_body(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "_No PR body provided._"
    return value.strip()


def first_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().splitlines()[0] if value.strip() else ""


def count_items(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def strip_wrapping_quotes(path: Path) -> Path:
    text = str(path).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return Path(text)


if __name__ == "__main__":
    sys.exit(main())
