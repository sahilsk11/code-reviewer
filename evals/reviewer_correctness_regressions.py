from __future__ import annotations

# ruff: noqa: E402,I001

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
        "must_notice_terms": [
            ["recover_missing_final", "missing final"],
            ["events", "poll"],
            ["recovery"],
        ],
    },
    {
        "name": "code-reviewer-publish-blocking-count-override",
        "repo": "https://github.com/sahilsk11/code-reviewer.git",
        "base_sha": "69c41ee0a1350dfa09818bce929eec5fdc06d758",
        "head_sha": "b19ebf5093a7c82f04b980c2f332247a978232c8",
        "source_pr": "https://github.com/sahilsk11/code-reviewer/pull/8",
        "title": "Move review publication into deterministic commands",
        "body": (
            "Adds deterministic GitHub context collection, replaces the publish "
            "agent with a Python publisher, and rewires cleanup around the "
            "managed review worktree."
        ),
        "validated_comments": [
            {
                "grade": "partial",
                "url": "https://github.com/sahilsk11/code-reviewer/pull/8#issuecomment-4584991993",
                "body": (
                    "`count_blocking` gives priority to a top-level "
                    "`blocking_count` over per-comment `blocking: true`, so a "
                    "payload with `blocking_count: 0` can silently ignore a "
                    "blocking comment."
                ),
            }
        ],
        "must_notice": [
            (
                "count_blocking can undercount blocking comments when the "
                "payload also includes a stale or contradictory blocking_count"
            ),
            (
                "the publisher can treat a review containing blocking comments "
                "as non-blocking if blocking_count is 0"
            ),
        ],
        "must_notice_terms": [
            ["count_blocking"],
            ["blocking_count"],
            ["blocking: true", "blocking true", "per-comment"],
            ["mask", "override", "undercount", "ignore", "non-blocking"],
        ],
        "avoid": [
            "treating the issue as only style or cleanup",
            "requiring the agent output to match the original review wording",
        ],
    },
    {
        "name": "sas-deploy-planner-missing-deployments-role",
        "repo": "https://github.com/sahilsk11/sas.git",
        "base_sha": "f5d18b11836e091e36df7dc87c5d2fb2ae4ba753",
        "head_sha": "88c8918d425fe464b39e975481790fd9787ea941",
        "source_pr": "https://github.com/sahilsk11/sas/pull/149",
        "title": "Move SAS deploys to self-hosted Prefect flow",
        "body": (
            "Moves SAS deploys onto a self-hosted runner and adds deploy "
            "planning/flow commands for Prefect-backed execution."
        ),
        "validated_comments": [
            {
                "grade": "valid",
                "url": "https://github.com/sahilsk11/sas/pull/149#issuecomment-4585396626",
                "body": (
                    "The deploy planner's structural tag list drift was real: "
                    "the new deployments role was missing from the planner wave "
                    "and needed a regression test against ansible/parallel.yml."
                ),
            }
        ],
        "must_notice": [
            (
                "the deployments role is missing from the deploy planner tag "
                "waves even though it was added to Ansible"
            ),
            (
                "planner tags can drift from ansible/parallel.yml and cause "
                "full deploys or deployments-only changes to skip the role"
            ),
        ],
        "must_notice_terms": [
            ["deployments"],
            ["APP_TAGS", "planner", "deploy planner", "tag list"],
            ["ansible/parallel.yml", "parallel.yml", "parallel"],
            ["skip", "missing", "drift", "not included"],
        ],
        "avoid": [
            "treating this as only deploy efficiency",
            "claiming the role is covered without comparing planner tags to Ansible waves",
        ],
    },
    {
        "name": "sas-prefect-control-plane-tags-drift",
        "repo": "https://github.com/sahilsk11/sas.git",
        "base_sha": "6b1c471a47f6d92168a7cb9bb0401f9bdc44bc27",
        "head_sha": "8cef5a8c666b4edd70413f33fa268c4728921acf",
        "source_pr": "https://github.com/sahilsk11/sas/pull/150",
        "title": "Implement two-phase Prefect deploy",
        "body": (
            "Splits deploys into GitHub-observed prepare and Prefect-observed "
            "worker phases, with control-plane tags handled outside Prefect."
        ),
        "validated_comments": [
            {
                "grade": "valid",
                "url": "https://github.com/sahilsk11/sas/pull/150#issuecomment-4585673822",
                "body": (
                    "CONTROL_PLANE_TAGS was duplicated independently in Bash "
                    "and Python, so prepare and worker filtering could drift."
                ),
            }
        ],
        "must_notice": [
            (
                "CONTROL_PLANE_TAGS is defined independently in Python and Bash "
                "with no sync enforcement"
            ),
            (
                "if the sets diverge, prepare and worker phases handle different "
                "control-plane tags and can defeat self-observation avoidance"
            ),
        ],
        "must_notice_terms": [
            ["CONTROL_PLANE_TAGS", "control-plane tags", "control plane tags"],
            ["bash", "sas-actions-deploy"],
            ["python", "flow.py", "sas.deploy.flow"],
            ["drift", "diverge", "sync", "source of truth"],
        ],
        "avoid": [
            "treating duplicated constants as a style-only issue",
            "missing the cross-language behavior split between prepare and worker",
        ],
    },
    {
        "name": "sas-prefect-work-pool-create-failure",
        "repo": "https://github.com/sahilsk11/sas.git",
        "base_sha": "6b1c471a47f6d92168a7cb9bb0401f9bdc44bc27",
        "head_sha": "8cef5a8c666b4edd70413f33fa268c4728921acf",
        "source_pr": "https://github.com/sahilsk11/sas/pull/150",
        "title": "Implement two-phase Prefect deploy",
        "body": (
            "Adds Prefect worker service and deployment registration for the "
            "two-phase SAS deploy architecture."
        ),
        "validated_comments": [
            {
                "grade": "partial",
                "url": "https://github.com/sahilsk11/sas/pull/150#issuecomment-4585674189",
                "body": (
                    "register_deployment had a real work-pool creation issue: "
                    "registration could continue to prefect deploy after work "
                    "pool creation failed."
                ),
            }
        ],
        "must_notice": [
            (
                "deployment registration should stop if Prefect work-pool "
                "creation fails"
            ),
            (
                "continuing to prefect deploy after a failed work-pool creation "
                "hides setup failure and can produce misleading deploy output"
            ),
        ],
        "must_notice_terms": [
            ["work pool", "work-pool"],
            ["prefect deploy", "register_deployment", "deployment registration"],
            ["create", "creation"],
            ["fail", "failure", "return code", "exit"],
        ],
        "avoid": [
            "requiring the broader deploy subprocess claim to be true",
            "missing the narrowed work-pool creation failure path",
        ],
    },
    {
        "name": "code-reviewer-braintrust-configure-crash",
        "repo": "https://github.com/sahilsk11/code-reviewer.git",
        "base_sha": "6ff95b46612648d172b6a1f6a846622e785bacc7",
        "head_sha": "abca301c6b4927be21456fe6ee2cb3a50485dafd",
        "source_pr": "https://github.com/sahilsk11/code-reviewer/pull/2",
        "title": "Install Braintrust SDK tracing",
        "body": (
            "Adds Braintrust tracing and eval tooling while keeping the CLI "
            "usable when Braintrust is absent or disabled."
        ),
        "validated_comments": [
            {
                "grade": "valid",
                "url": "https://github.com/sahilsk11/code-reviewer/pull/2#issuecomment-4570159981",
                "body": (
                    "configure_braintrust() ran before argument parsing with no "
                    "try/except, so Braintrust SDK failures could crash even "
                    "code-review --help."
                ),
            }
        ],
        "must_notice": [
            (
                "configure_braintrust runs before CLI parsing and can crash the "
                "entire CLI if Braintrust import/instrumentation/logger setup fails"
            ),
            (
                "optional tracing must degrade gracefully so commands like --help "
                "or install-workflow still work"
            ),
        ],
        "must_notice_terms": [
            ["configure_braintrust"],
            ["braintrust"],
            ["try", "except", "catch", "gracefully", "degrade"],
            ["--help", "help", "CLI", "parser", "parse_args"],
        ],
        "avoid": [
            "only checking for missing API keys",
            "assuming optional instrumentation failures are harmless",
        ],
    },
    {
        "name": "kanna-opencode-concurrent-server-startup",
        "repo": "https://github.com/sahilsk11/kanna.git",
        "base_sha": "206a835a252f2f5a12c9378431d08e57b2b1081e",
        "head_sha": "df59d72931d07e4e7288d986fed0571088f921fa",
        "source_pr": "https://github.com/sahilsk11/kanna/pull/17",
        "title": "Replace OpenCode ACP with server integration",
        "body": (
            "Routes OpenCode through a dedicated opencode serve HTTP/SSE "
            "manager and adds server event mapping tests."
        ),
        "validated_comments": [
            {
                "grade": "valid",
                "url": "https://github.com/sahilsk11/kanna/pull/17#issuecomment-4584466439",
                "body": (
                    "Concurrent same-cwd OpenCode server startup needed dedupe, "
                    "and server diagnostics/crash text handling needed to be "
                    "scoped to the right ServerState."
                ),
            }
        ],
        "must_notice": [
            (
                "concurrent ensureServer calls for the same cwd can spawn or "
                "race multiple OpenCode server starts without a starting-server guard"
            ),
            (
                "server diagnostics and buffered crash text need to stay scoped "
                "to the correct ServerState"
            ),
        ],
        "must_notice_terms": [
            ["ensureServer", "ensure server", "server startup", "startingServers"],
            ["concurrent", "race", "double-spawn", "same cwd", "same-cwd"],
            ["OpenCode", "opencode"],
            ["ServerState", "stderrLines", "diagnostics", "buffered"],
        ],
        "avoid": [
            "focusing only on style or provider abstraction",
            "treating all server lifecycle findings as already fixed at the pre-fix commit",
        ],
    },
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
                "metadata": case_metadata(case, model=args.model),
            }
            for case in CASES
        ],
        task=lambda input: run_case(input, model=args.model, timeout=args.timeout),
        scores=[completed, output_present, known_issue_present],
        metadata={
            "runner": "evals/reviewer_correctness_regressions.py",
            "prompt_file": f"src/code_reviewer/prompts/{PROMPT_FILE}",
            "model": args.model,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def case_metadata(case: dict[str, Any], *, model: str) -> dict[str, Any]:
    return {
        "eval_case": case["name"],
        "case": case["name"],
        "case_kind": "validated_pr" if case.get("source_pr") else "curated_pr",
        "repo": case["repo"],
        "source_pr": case.get("source_pr"),
        "base_sha": case["base_sha"],
        "head_sha": case["head_sha"],
        "model": model,
        "prompt_node": PROMPT_NODE,
        "prompt_file": f"src/code_reviewer/prompts/{PROMPT_FILE}",
    }


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
            capture_output=True,
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


def known_issue_present(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    term_groups = input.get("must_notice_terms") or []
    if not term_groups:
        return Score(name="known_issue_present", score=None)

    markdown = normalize_text(str(output.get("markdown") or ""))
    matched = []
    missing = []
    for terms in term_groups:
        normalized_terms = [normalize_text(str(term)) for term in terms]
        if any(term in markdown for term in normalized_terms):
            matched.append(terms)
        else:
            missing.append(terms)

    return Score(
        name="known_issue_present",
        score=len(matched) / len(term_groups),
        metadata={"matched": matched, "missing": missing},
    )


def normalize_text(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text.casefold()).strip()


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd)


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def repo_slug(repo: str) -> str:
    value = repo.removesuffix(".git").rstrip("/")
    return "/".join(value.split("/")[-2:])


def slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
