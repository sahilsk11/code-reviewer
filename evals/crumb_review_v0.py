from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from braintrust import Eval, Score

from code_reviewer.env import braintrust_project, load_local_env
from code_reviewer.workflow_builder import AGENT_NODES, read_prompt


DEFAULT_CASE_DIR = REPO_ROOT / "evals" / "crumb_cases"


@dataclass(frozen=True)
class MaterializedCase:
    repo_path: Path
    manifest_path: Path
    payload: dict[str, Any]
    summarize_intent_output: str
    diff: str
    diff_stat: str
    base_sha: str
    head_sha: str


class EvalInfrastructureError(RuntimeError):
    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def main(argv: list[str] | None = None) -> int:
    load_local_env(REPO_ROOT)
    parser = argparse.ArgumentParser(
        description="Braintrust eval for individual Archon prompt crumbs against local git fixtures."
    )
    parser.add_argument("--project", default=braintrust_project())
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--crumb-id", default="reviewer_correctness_regressions")
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Materialize cases and render prompts without Braintrust or model calls.",
    )
    parser.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Keep temporary materialized repos for debugging.",
    )
    args = parser.parse_args(argv)

    if args.render_only:
        cases = load_cases(args.case_dir, crumb_id=args.crumb_id)
        render_only(cases, keep_worktrees=args.keep_worktrees)
        return 0

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    cases = load_cases(args.case_dir, crumb_id=args.crumb_id)
    result = Eval(
        args.project,
        experiment_name=f"crumb-review-v0-{args.crumb_id}-{slug(args.model)}",
        data=cases,
        task=lambda input: run_crumb_case(
            input,
            model=args.model,
            timeout=args.timeout,
            keep_worktrees=args.keep_worktrees,
        ),
        scores=[
            output_present,
            expected_terms_present,
            expected_files_present,
            forbidden_terms_absent,
            no_findings_when_expected,
        ],
        metadata={
            "runner": "evals/crumb_review_v0.py",
            "crumb_id": args.crumb_id,
            "model": args.model,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def render_only(cases: list[dict[str, Any]], *, keep_worktrees: bool = False) -> None:
    for case in cases:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"crumb-review-{slug(case['input']['name'])}-"))
        try:
            materialized = materialize_case(case["input"], temp_dir)
            prompt = render_crumb_prompt(case["input"]["crumb_id"], materialized)
            print(
                json.dumps(
                    {
                        "case": case["metadata"]["case"],
                        "crumb_id": case["metadata"]["crumb_id"],
                        "base_sha": materialized.base_sha,
                        "head_sha": materialized.head_sha,
                        "diff_bytes": len(materialized.diff.encode("utf-8")),
                        "prompt_bytes": len(prompt.encode("utf-8")),
                        "worktree_path": str(materialized.repo_path) if keep_worktrees else None,
                    },
                    sort_keys=True,
                )
            )
        finally:
            if not keep_worktrees:
                shutil.rmtree(temp_dir, ignore_errors=True)


def load_cases(case_dir: Path, *, crumb_id: str) -> list[dict[str, Any]]:
    cases = []
    for path in sorted(case_dir.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("crumb_id") != crumb_id:
            continue
        cases.append(
            {
                "input": data | {"case_path": str(path)},
                "expected": data.get("expected", {}),
                "metadata": {
                    "case": data.get("name") or path.stem,
                    "crumb_id": data.get("crumb_id"),
                    "case_path": display_path(path),
                },
            }
        )
    if not cases:
        raise SystemExit(f"No {crumb_id!r} cases found in {case_dir}")
    return cases


def run_crumb_case(
    input: dict[str, Any],
    *,
    model: str,
    timeout: int,
    keep_worktrees: bool = False,
) -> dict[str, Any]:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"crumb-review-{slug(input['name'])}-"))
    try:
        try:
            materialized = materialize_case(input, temp_dir)
            prompt = render_crumb_prompt(input["crumb_id"], materialized)
            markdown, completed = run_codex_prompt(
                prompt,
                cwd=materialized.repo_path,
                model=model,
                timeout=timeout,
            )
        except EvalInfrastructureError as exc:
            return infrastructure_failure_result(
                exc,
                keep_worktrees=keep_worktrees,
                temp_dir=temp_dir,
            )
        result = {
            "returncode": completed.returncode,
            "stderr_tail": completed.stderr[-2000:],
            "markdown": markdown,
            "worktree_path": str(materialized.repo_path) if keep_worktrees else None,
            "diff": materialized.diff,
            "diff_stat": materialized.diff_stat,
            "base_sha": materialized.base_sha,
            "head_sha": materialized.head_sha,
        }
        return result
    finally:
        if not keep_worktrees:
            shutil.rmtree(temp_dir, ignore_errors=True)


def materialize_case(case: dict[str, Any], root: Path) -> MaterializedCase:
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    git(repo_path, "init", "-q")
    git(repo_path, "config", "user.email", "code-reviewer-eval@example.com")
    git(repo_path, "config", "user.name", "Code Reviewer Eval")

    repo = case["repo"]
    write_files(repo_path, repo.get("base_files", {}))
    git(repo_path, "add", ".")
    git(repo_path, "commit", "-q", "-m", "base")
    base_sha = git(repo_path, "rev-parse", "HEAD").stdout.strip()

    write_files(repo_path, repo.get("changed_files", {}))
    git(repo_path, "add", "-A")
    git(repo_path, "commit", "-q", "-m", "head")
    head_sha = git(repo_path, "rev-parse", "HEAD").stdout.strip()
    diff = git(repo_path, "diff", "--binary", "--find-renames", f"{base_sha}..{head_sha}").stdout
    diff_stat = git(repo_path, "diff", "--stat", f"{base_sha}..{head_sha}").stdout

    payload = review_payload(case, repo_path=repo_path, base_sha=base_sha, head_sha=head_sha)
    manifest = {
        "payload": payload,
        "repository": payload["repository"],
        "pr_number": payload["pull_request_number"],
        "pr_url": payload["pull_request_url"],
        "head_sha": head_sha,
        "base_sha": base_sha,
        "head_ref": "eval-head",
        "base_ref": "eval-base",
        "source_repo": str(repo_path),
        "worktree_path": str(repo_path),
        "managed_by": "code-reviewer-eval",
    }
    manifest_path = root / "prepare_worktree_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summarize_intent_output = render_review_brief(case, payload=payload, diff=diff, diff_stat=diff_stat)
    return MaterializedCase(
        repo_path=repo_path,
        manifest_path=manifest_path,
        payload=payload,
        summarize_intent_output=summarize_intent_output,
        diff=diff,
        diff_stat=diff_stat,
        base_sha=base_sha,
        head_sha=head_sha,
    )


def write_files(repo_path: Path, files: dict[str, str | None]) -> None:
    for relative_path, content in files.items():
        path = repo_path / relative_path
        if content is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def review_payload(case: dict[str, Any], *, repo_path: Path, base_sha: str, head_sha: str) -> dict[str, Any]:
    metadata = case.get("input", {})
    repository = metadata.get("repository", f"eval/{slug(case['name'])}")
    pr_number = int(metadata.get("pull_request_number", 1))
    return {
        "repo": str(repo_path),
        "repository": repository,
        "pull_request_number": pr_number,
        "pull_request_url": metadata.get(
            "pull_request_url",
            f"https://github.com/{repository}/pull/{pr_number}",
        ),
        "head_sha": head_sha,
        "base_sha": base_sha,
        "mode": metadata.get("mode", "full"),
        "dry_run": True,
    }


def render_review_brief(
    case: dict[str, Any],
    *,
    payload: dict[str, Any],
    diff: str,
    diff_stat: str,
) -> str:
    upstream = case.get("upstream", {})
    if upstream.get("summarize_intent_output"):
        return str(upstream["summarize_intent_output"])

    title = case.get("input", {}).get("title", case["name"])
    body = case.get("input", {}).get("body", "")
    return f"""# Review Brief

- PR: {title}
- Body: {body or "No PR body."}
- Repository: {payload["repository"]}
- Base SHA: {payload["base_sha"]}
- Head SHA: {payload["head_sha"]}

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


def render_crumb_prompt(crumb_id: str, materialized: MaterializedCase) -> str:
    node = next((candidate for candidate in AGENT_NODES if candidate.id == crumb_id), None)
    if node is None:
        raise ValueError(f"Unknown prompt crumb: {crumb_id}")
    prompt = read_prompt(node.prompt_file)
    replacements = {
        "$ARGUMENTS": json.dumps(materialized.payload, indent=2, sort_keys=True),
        "$prepare_worktree.output": str(materialized.manifest_path),
        "$summarize_intent.output": materialized.summarize_intent_output,
    }
    pattern = re.compile(
        "|".join(re.escape(token) for token in sorted(replacements, key=len, reverse=True))
    )
    return pattern.sub(lambda match: replacements[match.group(0)], prompt)


def run_codex_prompt(
    prompt: str,
    *,
    cwd: Path,
    model: str,
    timeout: int,
) -> tuple[str, subprocess.CompletedProcess[str]]:
    with tempfile.NamedTemporaryFile(prefix="crumb-review-v0-", suffix=".md") as output_file:
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
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            markdown = Path(output_file.name).read_text(encoding="utf-8").strip()
            stderr = timeout_output(exc.stderr) or str(exc)
            return markdown, subprocess.CompletedProcess(
                command,
                returncode=124,
                stdout=timeout_output(exc.output),
                stderr=stderr,
            )
        markdown = Path(output_file.name).read_text(encoding="utf-8").strip()
    return markdown, completed


def output_present(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return Score(
        name="output_present",
        score=1.0 if output.get("markdown") else 0.0,
        metadata={"returncode": output.get("returncode"), "stderr_tail": output.get("stderr_tail")},
    )


def expected_terms_present(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    terms = expected.get("must_include") or []
    if not terms:
        return Score(name="expected_terms_present", score=None, metadata={"reason": "no terms"})
    text = searchable_output(output)
    found = [term for term in terms if term.lower() in text]
    return Score(
        name="expected_terms_present",
        score=len(found) / len(terms),
        metadata={"found": found, "missing": [term for term in terms if term not in found]},
    )


def expected_files_present(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    files = expected.get("expected_files") or []
    if not files:
        return Score(name="expected_files_present", score=None, metadata={"reason": "no files"})
    text = searchable_output(output)
    found = [path for path in files if path.lower() in text]
    return Score(
        name="expected_files_present",
        score=len(found) / len(files),
        metadata={"found": found, "missing": [path for path in files if path not in found]},
    )


def forbidden_terms_absent(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    terms = expected.get("should_not_include") or []
    if not terms:
        return Score(name="forbidden_terms_absent", score=None, metadata={"reason": "no terms"})
    text = searchable_output(output)
    present = [term for term in terms if term.lower() in text]
    return Score(
        name="forbidden_terms_absent",
        score=1.0 if not present else 0.0,
        metadata={"present": present},
    )


def no_findings_when_expected(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> Score:
    if not expected.get("no_findings"):
        return Score(name="no_findings_when_expected", score=None, metadata={"reason": "not a clean case"})
    text = searchable_output(output)
    negative_signals = (
        "no findings",
        "no correctness findings",
        "no blocking findings",
        "no high-confidence findings",
        "no issues found",
        "no regressions detected",
    )
    has_negative_signal = any(signal in text for signal in negative_signals)
    has_finding_signal = has_finding_block_signal(output.get("markdown", ""))
    return Score(
        name="no_findings_when_expected",
        score=1.0 if not has_finding_signal else 0.0,
        metadata={
            "has_negative_signal": has_negative_signal,
            "has_finding_signal": has_finding_signal,
        },
    )


def searchable_output(output: dict[str, Any]) -> str:
    return str(output.get("markdown", "")).lower()


def has_finding_block_signal(markdown: object) -> bool:
    text = str(markdown)
    patterns = (
        r"(?im)^\s*(?:[-*]\s*)?source\s*:\s*(?:`)?new_finding(?:`)?\s*$",
        r"(?im)^\s*(?:[-*]\s*)?blocking\s*:\s*(?:`)?true(?:`)?\s*$",
        r"(?im)^\s*(?:[-*]\s*)?severity\s*:\s*(?:`)?(?:low|medium|high)(?:`)?\s*$",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def infrastructure_failure_result(
    exc: EvalInfrastructureError,
    *,
    keep_worktrees: bool,
    temp_dir: Path,
) -> dict[str, Any]:
    return {
        "returncode": 1,
        "stderr_tail": exc.stderr[-2000:],
        "markdown": "",
        "worktree_path": str(temp_dir) if keep_worktrees else None,
        "diff": "",
        "diff_stat": "",
        "base_sha": None,
        "head_sha": None,
        "error": str(exc),
    }


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        command = " ".join(["git", *args])
        raise EvalInfrastructureError(
            f"{command} failed with exit code {completed.returncode}",
            stderr=completed.stderr,
        )
    return completed


def timeout_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
