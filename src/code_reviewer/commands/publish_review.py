from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import (
    first_json_value,
    load_json_arg,
    read_json,
    resolve_repository_and_pr,
    run,
)

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)\s*```", re.IGNORECASE | re.DOTALL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish deterministic AI code review comments to GitHub."
    )
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--github-context", type=Path, required=True)
    parser.add_argument("--aggregate-output-file", type=Path, required=True)
    parser.add_argument("--worktree-manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    payload = load_json_arg(args.payload_json)
    context = read_json(args.github_context)
    manifest = read_json(args.worktree_manifest)
    aggregate_output = args.aggregate_output_file.read_text(encoding="utf-8")

    repository, pr_number = resolve_repository_and_pr(
        payload,
        context=context,
        manifest=manifest,
    )
    head_sha = str(
        payload.get("head_sha")
        or manifest.get("head_sha")
        or context.get("pr", {}).get("headRefOid")
        or ""
    )
    if not head_sha:
        raise SystemExit("Need head_sha from payload, manifest, or GitHub context")

    publish_payload = extract_publish_payload(aggregate_output)
    comments = normalize_comments(publish_payload)
    blocking_count = count_blocking(comments, publish_payload)

    if payload.get("dry_run") is True:
        print_result(
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            dry_run=True,
            comments=comments,
            blocking_count=blocking_count,
            published=[],
        )
        return 1 if blocking_count else 0

    published = publish_comments(
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        comments=comments,
        cwd=Path(str(manifest["worktree_path"])).expanduser(),
    )
    print_result(
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        dry_run=False,
        comments=comments,
        blocking_count=blocking_count,
        published=published,
    )
    return 1 if blocking_count else 0


def extract_publish_payload(text: str) -> dict[str, Any]:
    candidates = [match.group("body") for match in JSON_FENCE_RE.finditer(text)]
    candidates.append(text)
    for candidate in reversed(candidates):
        data = first_json_value(candidate)
        if isinstance(data, dict) and ("comments" in data or "findings" in data):
            return data
    raise SystemExit("aggregate_dedupe output did not contain comments JSON")


def normalize_comments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_comments = payload.get("comments")
    if raw_comments is None:
        raw_comments = payload.get("findings")
    if not isinstance(raw_comments, list):
        raise SystemExit("publish payload comments must be a list")

    comments = []
    for index, raw in enumerate(raw_comments, start=1):
        if not isinstance(raw, dict):
            raise SystemExit(f"comment {index} must be an object")
        comment_type = raw.get("type") or ("inline" if raw.get("path") else "top_level")
        if comment_type not in {"inline", "top_level"}:
            raise SystemExit(f"comment {index} has unsupported type: {comment_type}")
        body = raw.get("body") or raw.get("comment") or raw.get("proposed_comment")
        if not isinstance(body, str) or not body.strip():
            raise SystemExit(f"comment {index} missing body")

        normalized = dict(raw)
        normalized["type"] = comment_type
        normalized["body"] = body.strip()
        normalized["blocking"] = raw.get("blocking") is True
        if comment_type == "inline":
            if not isinstance(raw.get("path"), str) or not raw.get("path"):
                raise SystemExit(f"inline comment {index} missing path")
            line = raw.get("line")
            if not isinstance(line, int):
                raise SystemExit(f"inline comment {index} missing integer line")
            normalized["side"] = raw.get("side") if raw.get("side") in {"LEFT", "RIGHT"} else "RIGHT"
        comments.append(normalized)
    return comments


def count_blocking(comments: list[dict[str, Any]], payload: dict[str, Any]) -> int:
    from_comments = sum(1 for comment in comments if comment.get("blocking") is True)
    explicit = payload.get("blocking_count")
    if isinstance(explicit, int):
        return max(explicit, from_comments)
    if isinstance(explicit, str) and explicit.isdigit():
        return max(int(explicit), from_comments)
    return from_comments


def publish_comments(
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    comments: list[dict[str, Any]],
    cwd: Path,
) -> list[dict[str, Any]]:
    published = []
    for comment in comments:
        if comment["type"] == "top_level":
            completed = run(
                [
                    "gh",
                    "pr",
                    "comment",
                    str(pr_number),
                    "--repo",
                    repository,
                    "--body",
                    comment["body"],
                ],
                cwd=cwd,
            )
            published.append({"type": "top_level", "stdout": completed.stdout.strip()})
            continue

        completed = run(
            [
                "gh",
                "api",
                f"repos/{repository}/pulls/{pr_number}/comments",
                "-f",
                f"body={comment['body']}",
                "-f",
                f"commit_id={head_sha}",
                "-f",
                f"path={comment['path']}",
                "-F",
                f"line={comment['line']}",
                "-f",
                f"side={comment['side']}",
            ],
            cwd=cwd,
        )
        published.append(
            {
                "type": "inline",
                "path": comment["path"],
                "line": comment["line"],
                "stdout": completed.stdout.strip(),
            }
        )
    return published


def print_result(
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    dry_run: bool,
    comments: list[dict[str, Any]],
    blocking_count: int,
    published: list[dict[str, Any]],
) -> None:
    print(
        json.dumps(
            {
                "repository": repository,
                "pr_number": pr_number,
                "head_sha": head_sha,
                "dry_run": dry_run,
                "comment_count": len(comments),
                "blocking_count": blocking_count,
                "check_conclusion": "failure" if blocking_count else "success",
                "published": published,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
