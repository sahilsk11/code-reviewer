from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from braintrust import Eval, Score

from code_reviewer.env import braintrust_project, load_local_env
from code_reviewer.workflow_builder import read_prompt


PROMPT_FILE = "reviewer_correctness_regressions.md"
PROMPT_NODE = "reviewer_correctness_regressions"

CASES: list[dict[str, Any]] = [
    {
        "name": "friday-narrator-final-recovery",
        "repo": "https://github.com/sahilsk11/friday.git",
        "base_sha": "4625de4df421d9f87aed48bbec6e77f4c2783760",
        "head_sha": "bb004ed88f2391bd63781fa3d5ed71a37b538753",
        "title": "Stop narrator final recovery from event polling",
        "body": (
            "Removes legacy final recovery paths and moves provider-final "
            "handling toward explicit turn ownership."
        ),
    }
]


def main(argv: list[str] | None = None) -> int:
    load_local_env(REPO_ROOT)
    parser = argparse.ArgumentParser(
        description="Braintrust eval for the correctness/regressions reviewer prompt."
    )
    parser.add_argument("--project", default=braintrust_project())
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    result = Eval(
        args.project,
        experiment_name=f"reviewer-correctness-regressions-{slug(args.model)}",
        data=[
            {
                "input": case,
                "metadata": {
                    "case": case["name"],
                    "repo": case["repo"],
                    "base_sha": case["base_sha"],
                    "head_sha": case["head_sha"],
                    "prompt_node": PROMPT_NODE,
                },
            }
            for case in CASES
        ],
        task=lambda input: run_case(input, model=args.model, timeout=args.timeout),
        scores=[completed, output_present, finding_shape_present],
        metadata={
            "runner": "evals/reviewer_correctness_regressions.py",
            "prompt_file": f"src/code_reviewer/prompts/{PROMPT_FILE}",
            "model": args.model,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def run_case(case: dict[str, Any], *, model: str, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=f"reviewer-correctness-{slug(case['name'])}-"
    ) as temp_dir:
        root = Path(temp_dir)
        repo_path = clone_case_repo(case, root)
        diff = git(
            repo_path,
            "diff",
            "--binary",
            "--find-renames",
            f"{case['base_sha']}..{case['head_sha']}",
        ).stdout
        diff_stat = git(
            repo_path,
            "diff",
            "--stat",
            f"{case['base_sha']}..{case['head_sha']}",
        ).stdout
        manifest_path = write_worktree_manifest(case, repo_path=root, checkout_path=repo_path)
        prompt = render_prompt(
            case,
            manifest_path=manifest_path,
            diff=diff,
            diff_stat=diff_stat,
        )
        markdown, completed_process = run_codex_prompt(
            prompt,
            cwd=repo_path,
            model=model,
            timeout=timeout,
        )
        return {
            "returncode": completed_process.returncode,
            "markdown": markdown,
            "stderr_tail": completed_process.stderr[-2000:],
            "diff_stat": diff_stat,
            "prompt_node": PROMPT_NODE,
            "repo": case["repo"],
            "base_sha": case["base_sha"],
            "head_sha": case["head_sha"],
        }


def clone_case_repo(case: dict[str, Any], root: Path) -> Path:
    repo_path = root / "repo"
    run(["git", "clone", "--no-checkout", "--quiet", case["repo"], str(repo_path)])
    ensure_commit(repo_path, case["base_sha"])
    ensure_commit(repo_path, case["head_sha"])
    git(repo_path, "checkout", "--quiet", case["head_sha"])
    return repo_path


def ensure_commit(repo_path: Path, sha: str) -> None:
    if subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0:
        return
    git(repo_path, "fetch", "--quiet", "origin", sha)
    git(repo_path, "cat-file", "-e", f"{sha}^{{commit}}")


def write_worktree_manifest(case: dict[str, Any], *, repo_path: Path, checkout_path: Path) -> Path:
    manifest = {
        "payload": review_payload(case, repo_path=checkout_path),
        "repository": repo_slug(case["repo"]),
        "pr_number": None,
        "pr_url": None,
        "head_sha": case["head_sha"],
        "base_sha": case["base_sha"],
        "source_repo": str(checkout_path),
        "worktree_path": str(checkout_path),
        "managed_by": "braintrust-eval",
    }
    path = repo_path / "prepare_worktree_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def review_payload(case: dict[str, Any], *, repo_path: Path) -> dict[str, Any]:
    return {
        "repo": str(repo_path),
        "repository": repo_slug(case["repo"]),
        "pull_request_number": None,
        "pull_request_url": None,
        "head_sha": case["head_sha"],
        "base_sha": case["base_sha"],
        "mode": "full",
        "dry_run": True,
    }


def render_prompt(
    case: dict[str, Any],
    *,
    manifest_path: Path,
    diff: str,
    diff_stat: str,
) -> str:
    replacements = {
        "$ARGUMENTS": json.dumps(
            review_payload(case, repo_path=manifest_path.parent / "repo"),
            indent=2,
            sort_keys=True,
        ),
        "$prepare_worktree.output": str(manifest_path),
        "$summarize_intent.output": review_brief(case, diff=diff, diff_stat=diff_stat),
    }
    prompt = read_prompt(PROMPT_FILE)
    for token, value in replacements.items():
        prompt = prompt.replace(token, value)
    return prompt


def review_brief(case: dict[str, Any], *, diff: str, diff_stat: str) -> str:
    return f"""# Review Brief

- PR: {case.get("title", case["name"])}
- Body: {case.get("body", "No PR body.")}
- Repository: {repo_slug(case["repo"])}
- Base SHA: {case["base_sha"]}
- Head SHA: {case["head_sha"]}

## Prior Review State

- Active unresolved blocking comments: none
- Active unresolved non-blocking comments: none
- Responded-to comments: none
- Outdated comments: none
- Explicit controls: none

## Diff Stat

```text
{diff_stat.strip() or "No stat."}
```

## Diff

```diff
{diff}
```
"""


def run_codex_prompt(
    prompt: str,
    *,
    cwd: Path,
    model: str,
    timeout: int,
) -> tuple[str, subprocess.CompletedProcess[str]]:
    with tempfile.NamedTemporaryFile(prefix="reviewer-correctness-", suffix=".md") as output_file:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            output_file.name,
            "--model",
            model,
            "-",
        ]
        completed_process = subprocess.run(
            command,
            input=prompt,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        markdown = Path(output_file.name).read_text(encoding="utf-8").strip()
    return markdown, completed_process


def completed(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return Score(
        name="completed",
        score=1.0 if output.get("returncode") == 0 else 0.0,
        metadata={"returncode": output.get("returncode"), "stderr_tail": output.get("stderr_tail")},
    )


def output_present(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    return Score(
        name="output_present",
        score=1.0 if str(output.get("markdown") or "").strip() else 0.0,
    )


def finding_shape_present(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    markdown = str(output.get("markdown") or "")
    labels = ("file", "severity", "blocking", "confidence", "source")
    found = [label for label in labels if re_search_label(markdown, label)]
    return Score(
        name="finding_shape_present",
        score=len(found) / len(labels),
        metadata={"found": found, "missing": [label for label in labels if label not in found]},
    )


def re_search_label(markdown: str, label: str) -> bool:
    import re

    return re.search(rf"(?im)^\s*(?:[-*]\s*)?{label}\s*:", markdown) is not None


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd)


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def repo_slug(repo: str) -> str:
    value = repo.removesuffix(".git").rstrip("/")
    return "/".join(value.split("/")[-2:])


def slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
