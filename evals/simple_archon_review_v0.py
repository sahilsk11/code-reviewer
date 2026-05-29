from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from braintrust import Eval, Score

PROJECT_NAME = "My Project"
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = "simple-code-review"

CASES = [
    {
        "input": {
            "path": str(REPO_ROOT / "evals/examples/hello_world_bug.py"),
            "name": "hello_world_bug",
        },
        "expected": {
            "should_fail": True,
            "must_include": ["NameError", "mesage", "message"],
            "max_findings": 1,
        },
    },
    {
        "input": {
            "path": str(REPO_ROOT / "evals/examples/hello_world.py"),
            "name": "hello_world_clean",
        },
        "expected": {
            "should_fail": False,
            "must_include": ["no", "issue"],
            "max_findings": 0,
        },
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Braintrust eval for simple Archon review workflow.")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    result = Eval(
        PROJECT_NAME,
        experiment_name="simple-archon-review-v0",
        data=CASES,
        task=lambda input: run_simple_workflow(input, timeout=args.timeout),
        scores=[json_payload_present, conclusion_matches, expected_signal, finding_count_reasonable],
        metadata={"runner": "evals/simple_archon_review_v0.py", "workflow": WORKFLOW_NAME},
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def run_simple_workflow(input: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    payload = json.dumps({"path": input["path"]})
    env = os.environ.copy()
    env.setdefault("CODEX_BIN_PATH", "/usr/bin/codex")
    completed = subprocess.run(
        ["archon", "workflow", "run", WORKFLOW_NAME, payload],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout
    return {
        "returncode": completed.returncode,
        "stdout_tail": output[-4000:],
        "payload": extract_json_payload(output),
    }


def extract_json_payload(text: str) -> dict[str, Any] | None:
    matches = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate.strip())
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None


def json_payload_present(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return Score(
        name="json_payload_present",
        score=1.0 if output.get("payload") else 0.0,
        metadata={"returncode": output.get("returncode")},
    )


def conclusion_matches(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    payload = output.get("payload") or {}
    actual = str(payload.get("check_conclusion", "")).lower()
    wanted = "failure" if expected["should_fail"] else "success"
    return Score(name="conclusion_matches", score=1.0 if actual == wanted else 0.0, metadata={"actual": actual})


def expected_signal(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    text = json.dumps(output.get("payload") or {}) + "\n" + output.get("stdout_tail", "")
    normalized = text.lower()
    terms = [term.lower() for term in expected["must_include"]]
    found = [term for term in terms if term in normalized]
    return Score(
        name="expected_signal",
        score=1.0 if len(found) == len(terms) else len(found) / len(terms),
        metadata={"found": found, "missing": [term for term in terms if term not in found]},
    )


def finding_count_reasonable(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    payload = output.get("payload") or {}
    findings = payload.get("findings")
    count = len(findings) if isinstance(findings, list) else 0
    return Score(
        name="finding_count_reasonable",
        score=1.0 if count <= expected["max_findings"] else 0.0,
        metadata={"finding_count": count, "max_findings": expected["max_findings"]},
    )


if __name__ == "__main__":
    sys.exit(main())
