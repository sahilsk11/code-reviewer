from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import (
    gh_json,
    load_json_arg,
    manifest_path_for,
    parse_pr_url,
    run,
    sanitize_path_part,
    write_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an exact-SHA PR review worktree.")
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--worktree-root", default="~/wt")
    args = parser.parse_args(argv)

    payload = load_json_arg(args.payload_json)
    repo_path = Path(str(payload.get("repo") or ".")).expanduser().resolve()
    if not repo_path.exists():
        raise SystemExit(f"Repository path does not exist: {repo_path}")

    pr_url = payload.get("pull_request_url")
    repository = payload.get("repository")
    pr_number = payload.get("pull_request_number")
    parsed_repository, parsed_number = parse_pr_url(pr_url if isinstance(pr_url, str) else None)
    repository = repository or parsed_repository
    pr_number = pr_number or parsed_number

    pr = resolve_pr(pr_url, repository, pr_number)
    repository = repository or pr["headRepository"]["nameWithOwner"]
    pr_number = pr_number or pr["number"]
    head_sha = str(payload.get("head_sha") or pr["headRefOid"])
    if head_sha != pr["headRefOid"]:
        raise SystemExit(
            f"Payload head_sha {head_sha} does not match PR headRefOid {pr['headRefOid']}"
        )

    worktree_root = Path(args.worktree_root).expanduser().resolve()
    repo_slug = sanitize_path_part(str(repository).replace("/", "-"))
    worktree_path = worktree_root / f"code-review-{repo_slug}-pr-{pr_number}-{head_sha[:12]}"
    prepare_clean_path(repo_path, worktree_path)

    fetch_pr(repo_path, int(pr_number), head_sha, pr.get("baseRefOid"))
    run(["git", "worktree", "add", "--detach", str(worktree_path), head_sha], cwd=repo_path)

    manifest = {
        "payload": payload,
        "repository": repository,
        "pr_number": int(pr_number),
        "pr_url": pr.get("url") or pr_url,
        "head_sha": head_sha,
        "base_sha": pr.get("baseRefOid"),
        "head_ref": pr.get("headRefName"),
        "base_ref": pr.get("baseRefName"),
        "source_repo": str(repo_path),
        "worktree_path": str(worktree_path),
        "managed_by": "code-reviewer",
    }
    manifest_path = write_json(manifest_path_for(worktree_path), manifest)
    print(manifest_path)
    return 0


def resolve_pr(pr_url: object, repository: object, pr_number: object) -> dict[str, Any]:
    fields = (
        "url,number,title,headRefOid,baseRefOid,headRepository,"
        "headRefName,baseRefName,state,isDraft"
    )
    if isinstance(pr_url, str) and pr_url:
        return gh_json(["pr", "view", pr_url, "--json", fields])
    if repository and pr_number:
        return gh_json(["pr", "view", str(pr_number), "--repo", str(repository), "--json", fields])
    raise SystemExit("Need pull_request_url or repository + pull_request_number to resolve PR")


def prepare_clean_path(repo_path: Path, worktree_path: Path) -> None:
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if not worktree_path.exists():
        return

    if not is_managed_worktree_path(worktree_path):
        raise SystemExit(f"Refusing to remove unmanaged existing path: {worktree_path}")

    run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_path, check=False)
    if worktree_path.exists():
        shutil.rmtree(worktree_path)


def fetch_pr(repo_path: Path, pr_number: int, head_sha: str, base_sha: object) -> None:
    run(["git", "fetch", "origin", f"pull/{pr_number}/head"], cwd=repo_path)
    if base_sha:
        run(["git", "fetch", "origin", str(base_sha)], cwd=repo_path, check=False)
    run(["git", "cat-file", "-e", f"{head_sha}^{{commit}}"], cwd=repo_path)


def is_managed_worktree_path(path: Path) -> bool:
    try:
        path.relative_to((Path.home() / "wt").resolve())
    except ValueError:
        return False
    return path.name.startswith("code-review-")


if __name__ == "__main__":
    sys.exit(main())
