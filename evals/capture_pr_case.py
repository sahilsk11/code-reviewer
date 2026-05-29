from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--name", help="Output case name without .json.")
    args = parser.parse_args(argv)

    pr = gh_pr_view(args.pr_url)
    commits = pr["commits"]
    if args.commit_index < 0 or args.commit_index >= len(commits):
        raise SystemExit(f"--commit-index must be between 0 and {len(commits) - 1}")

    repo = pr["headRepository"]["nameWithOwner"]
    base_sha = pr["baseRefOid"]
    target_commit = commits[args.commit_index]
    target_sha = target_commit["oid"]
    patch, diff_stat = capture_diff(repo=repo, pr_number=pr["number"], base_sha=base_sha, target_sha=target_sha)

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
            "captured_commit_index": args.commit_index,
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
        "expected": {
            "notes": "Unlabeled captured case. Add teacher output or human labels before scoring quality.",
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or default_case_name(repo=repo, pr_number=pr["number"], commit_index=args.commit_index)
    output_path = args.output_dir / f"{name}.json"
    output_path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
