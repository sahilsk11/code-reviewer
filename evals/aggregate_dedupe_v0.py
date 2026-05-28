from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from braintrust import Eval, Score

PROJECT_NAME = "My Project"
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / "src/code_reviewer/workflows/ai-code-review.yaml"


CASES: list[dict[str, Any]] = [
    {
        "input": {
            "name": "dedupe_same_root_cause",
            "arguments": {
                "pull_request_url": "https://github.com/acme/app/pull/7",
                "head_sha": "abc123",
                "mode": "full",
                "dry_run": True,
            },
            "prepare_worktree": "/tmp/acme-app-pr-7",
            "brief": "The PR renames a variable in greeting.py and should keep runtime behavior.",
            "correctness": """
Finding correctness-1
- file: greeting.py
- line: 3
- severity: high
- blocking: true
- confidence: high
- evidence: greet() returns `mesage`, but only `message` is defined.
- proposed comment: This will raise NameError at runtime; return `message`.
""",
            "design": """
Finding design-1
- file: greeting.py
- line: 3
- severity: high
- blocking: true
- confidence: high
- evidence: The function returns `mesage`, duplicating the same undefined-name issue.
- proposed comment: Return the existing `message` variable instead of `mesage`.
""",
            "simplicity": "No additional actionable findings.",
        },
        "expected": {
            "should_fail": True,
            "must_include": ["NameError", "mesage", "message"],
            "max_findings": 1,
        },
    },
    {
        "input": {
            "name": "drop_unit_test_only_complaint",
            "arguments": {
                "pull_request_url": "https://github.com/acme/app/pull/8",
                "head_sha": "def456",
                "mode": "incremental",
                "dry_run": True,
            },
            "prepare_worktree": "/tmp/acme-app-pr-8",
            "brief": "The PR changes only README wording. No runtime behavior changed.",
            "correctness": """
Finding correctness-1
- file: README.md
- line: 4
- severity: low
- blocking: false
- confidence: medium
- evidence: There are no unit tests for the README wording change.
- proposed comment: Please add unit tests for this README update.
""",
            "design": "No findings.",
            "simplicity": "No findings.",
        },
        "expected": {
            "should_fail": False,
            "must_include": ["skipped", "unit"],
            "max_findings": 0,
        },
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Braintrust eval for the aggregate_dedupe prompt.")
    parser.add_argument("--model", default=os.environ.get("CODEX_EVAL_MODEL"))
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    result = Eval(
        PROJECT_NAME,
        experiment_name="aggregate-dedupe-v0",
        data=CASES,
        task=lambda input: run_aggregate_prompt(input, model=args.model, timeout=args.timeout),
        scores=[json_payload_present, conclusion_matches, dedupes_findings, expected_signal],
        metadata={"runner": "evals/aggregate_dedupe_v0.py", "node": "aggregate_dedupe"},
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def run_aggregate_prompt(input: dict[str, Any], *, model: str | None, timeout: int) -> dict[str, Any]:
    prompt = render_prompt(load_node_prompt("aggregate_dedupe"), input)
    prompt += """

For this eval, keep the answer short. The final fenced json block is required.
Use this JSON shape:
{
  "summary": "short summary",
  "findings": [{"id": "...", "file": "...", "line": 1, "blocking": true, "comment": "..."}],
  "skipped_findings": [{"id": "...", "reason": "..."}],
  "check_conclusion": "success or failure"
}
"""
    with tempfile.NamedTemporaryFile(prefix="aggregate-dedupe-v0-", suffix=".md") as output_file:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            output_file.name,
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")

        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        markdown = Path(output_file.name).read_text(encoding="utf-8").strip()
        payload = extract_json_payload(markdown)
        return {
            "returncode": completed.returncode,
            "markdown": markdown,
            "payload": payload,
        }


def load_node_prompt(node_id: str) -> str:
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    in_node = False
    in_prompt = False
    prompt_lines: list[str] = []
    for line in lines:
        if line.startswith("  - id: "):
            if in_node:
                break
            in_node = line.strip() == f"- id: {node_id}"
            continue
        if not in_node:
            continue
        if line.strip() == "prompt: |":
            in_prompt = True
            continue
        if in_prompt:
            if line.startswith("    depends_on:"):
                break
            prompt_lines.append(line[6:] if line.startswith("      ") else line)
    if not prompt_lines:
        raise RuntimeError(f"Could not find prompt for node: {node_id}")
    return "\n".join(prompt_lines).rstrip()


def render_prompt(template: str, input: dict[str, Any]) -> str:
    replacements = {
        "$ARGUMENTS": json.dumps(input["arguments"], sort_keys=True),
        "$prepare_worktree.output": input["prepare_worktree"],
        "$summarize_intent.output": input["brief"],
        "$reviewer_correctness_regressions.output": input["correctness"],
        "$reviewer_design_layering_reuse.output": input["design"],
        "$reviewer_simplicity_alternatives.output": input["simplicity"],
    }
    for old, new in replacements.items():
        template = template.replace(old, str(new))
    return template


def extract_json_payload(markdown: str) -> dict[str, Any] | None:
    matches = re.findall(r"```(?:json)?\s*(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE)
    for candidate in reversed(matches):
        candidate = candidate.strip()
        if "publish_payload" in candidate:
            candidate = candidate.split("=", 1)[-1].strip()
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None


def json_payload_present(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return Score(name="json_payload_present", score=1.0 if output.get("payload") else 0.0)


def conclusion_matches(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    payload = output.get("payload") or {}
    conclusion = str(payload.get("check_conclusion", "")).lower()
    should_fail = bool(expected["should_fail"])
    passed = conclusion == ("failure" if should_fail else "success")
    return Score(name="conclusion_matches", score=1.0 if passed else 0.0, metadata={"conclusion": conclusion})


def dedupes_findings(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    payload = output.get("payload") or {}
    findings = payload.get("findings")
    count = len(findings) if isinstance(findings, list) else 0
    return Score(
        name="dedupes_findings",
        score=1.0 if count <= int(expected["max_findings"]) else 0.0,
        metadata={"finding_count": count, "max_findings": expected["max_findings"]},
    )


def expected_signal(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    text = json.dumps(output.get("payload") or {}) + "\n" + output.get("markdown", "")
    normalized = text.lower()
    terms = [term.lower() for term in expected["must_include"]]
    found = [term for term in terms if term in normalized]
    return Score(
        name="expected_signal",
        score=1.0 if len(found) == len(terms) else len(found) / len(terms),
        metadata={"found": found, "missing": [term for term in terms if term not in found]},
    )


if __name__ == "__main__":
    sys.exit(main())
