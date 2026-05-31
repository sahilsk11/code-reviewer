from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import (
    gh_json,
    load_json_arg,
    resolve_repository_and_pr,
    run,
    sanitize_path_part,
    write_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect deterministic GitHub context for an AI code review."
    )
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--output-root", default="~/.code-reviews/github-context")
    args = parser.parse_args(argv)

    payload = load_json_arg(args.payload_json)
    repository, pr_number = resolve_repository_and_pr(payload)

    context = collect_context(repository=repository, pr_number=pr_number)
    context["payload"] = payload
    context["repository"] = repository
    context["pr_number"] = pr_number

    output_root = Path(args.output_root).expanduser()
    head_sha = context.get("pr", {}).get("headRefOid") if isinstance(context.get("pr"), dict) else None
    suffix = str(head_sha or "unknown")[:12]
    path = output_root / f"{sanitize_path_part(repository.replace('/', '-'))}-pr-{pr_number}-{suffix}.json"
    write_json(path, context)
    print(path)
    return 0


def collect_context(*, repository: str, pr_number: int) -> dict[str, Any]:
    pr_fields = (
        "url,number,title,body,headRefOid,baseRefOid,headRefName,baseRefName,"
        "headRepository,state,isDraft,commits,files"
    )
    return {
        "pr": gh_json(["pr", "view", str(pr_number), "--repo", repository, "--json", pr_fields]),
        "issue_comments": gh_api_list(
            ["api", f"repos/{repository}/issues/{pr_number}/comments", "--paginate", "--slurp"]
        ),
        "review_comments": gh_api_list(
            ["api", f"repos/{repository}/pulls/{pr_number}/comments", "--paginate", "--slurp"]
        ),
        "reviews": gh_api_list(
            ["api", f"repos/{repository}/pulls/{pr_number}/reviews", "--paginate", "--slurp"]
        ),
        "files": gh_api_list(
            ["api", f"repos/{repository}/pulls/{pr_number}/files", "--paginate", "--slurp"]
        ),
    }


def gh_api_list(args: Sequence[str]) -> list[Any]:
    data = gh_json_value(args)
    if isinstance(data, list):
        if all(isinstance(item, list) for item in data):
            return [nested for page in data for nested in page]
        return data
    if isinstance(data, dict):
        return [data]
    raise SystemExit(f"gh returned non-list JSON for: gh {' '.join(args)}")


def gh_json_value(args: Sequence[str]) -> Any:
    completed = run(["gh", *args])
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"gh returned invalid JSON for: gh {' '.join(args)}") from exc


if __name__ == "__main__":
    sys.exit(main())
