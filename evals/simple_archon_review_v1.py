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

CASES: list[dict[str, Any]] = [
    {
        "input": {
            "name": "undefined_variable",
            "filename": "greeting.py",
            "content": 'def greet() -> str:\n    message = "hello world"\n    return mesage\n',
        },
        "expected": {
            "should_fail": True,
            "must_include": ["mesage", "message"],
            "must_not_include": ["test"],
            "max_findings": 1,
        },
    },
    {
        "input": {
            "name": "clean_readme",
            "filename": "README.md",
            "content": "# Demo\n\nThis package prints a greeting.\n",
        },
        "expected": {
            "should_fail": False,
            "must_include": ["no", "issue"],
            "must_not_include": ["test", "bug"],
            "max_findings": 0,
        },
    },
    {
        "input": {
            "name": "test_bait_comment",
            "filename": "math_utils.py",
            "content": (
                "def add(left: int, right: int) -> int:\n"
                "    # TODO: add more tests later.\n"
                "    return left + right\n"
            ),
        },
        "expected": {
            "should_fail": False,
            "must_include": ["no", "issue"],
            "must_not_include": ["test", "todo"],
            "max_findings": 0,
        },
    },
    {
        "input": {
            "name": "mutable_default",
            "filename": "collector.py",
            "content": (
                "def collect(value: str, items: list[str] = []) -> list[str]:\n"
                "    items.append(value)\n"
                "    return items\n"
            ),
        },
        "expected": {
            "should_fail": True,
            "must_include": ["mutable", "default"],
            "must_not_include": [],
            "max_findings": 1,
        },
    },
    {
        "input": {
            "name": "identity_string_compare",
            "filename": "auth.py",
            "content": (
                "class User:\n"
                "    def __init__(self, role: str) -> None:\n"
                "        self.role = role\n\n"
                "def is_admin(user: User) -> bool:\n"
                "    return user.role is \"admin\"\n"
            ),
        },
        "expected": {
            "should_fail": True,
            "must_include": ["is", "=="],
            "must_not_include": [],
            "max_findings": 1,
        },
    },
    {
        "input": {
            "name": "harmless_refactor",
            "filename": "formatter.py",
            "content": (
                "def format_name(first: str, last: str) -> str:\n"
                "    full_name = f\"{first} {last}\"\n"
                "    return full_name.strip()\n"
            ),
        },
        "expected": {
            "should_fail": False,
            "must_include": ["no", "issue"],
            "must_not_include": ["style", "test"],
            "max_findings": 0,
        },
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model comparison eval for simple Archon reviews.")
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    workflow_name = ensure_workflow(args.model)
    experiment_name = f"simple-archon-review-v1-{slug(args.model)}"
    result = Eval(
        PROJECT_NAME,
        experiment_name=experiment_name,
        data=CASES,
        task=lambda input: run_case(input, workflow_name=workflow_name, timeout=args.timeout),
        scores=[
            json_payload_present,
            conclusion_matches,
            must_include_terms,
            avoids_forbidden_terms,
            finding_count_reasonable,
        ],
        metadata={
            "runner": "evals/simple_archon_review_v1.py",
            "workflow": workflow_name,
            "model": args.model,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def ensure_workflow(model: str) -> str:
    workflow_name = f"simple-code-review-eval-{slug(model)}"
    workflow_path = REPO_ROOT / ".archon" / "workflows" / "tmp" / f"{workflow_name}.yaml"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(render_workflow(workflow_name, model), encoding="utf-8")
    return workflow_name


def render_workflow(name: str, model: str) -> str:
    return f"""name: {name}
description: |
  Use when: A synthetic eval file needs a fast code review pass.
  Input: JSON with `path` pointing at a local file to review.
  Output: Short review summary plus a final structured JSON payload.
  NOT for: Publishing GitHub comments or full PR context gathering.

provider: codex
model: {model}
worktree:
  enabled: false

nodes:
  - id: prepare_context
    bash: |
      set -euo pipefail
      python3 - <<'PY'
      import json
      import os
      from pathlib import Path

      payload = json.loads(os.environ.get("ARGUMENTS") or "{{}}")
      path = Path(payload["path"]).expanduser().resolve()
      code = path.read_text(encoding="utf-8")
      print(json.dumps({{
          "path": str(path),
          "filename": path.name,
          "code": code,
      }}, indent=2))
      PY

  - id: review_file
    context: fresh
    model: {model}
    prompt: |
      Review this tiny code change quickly.

      Prepared context:
      $prepare_context.output

      Requirements:
      - Keep the review short.
      - Report only concrete correctness issues.
      - Do not comment on style, tests, TODOs, or docs unless they cause a real bug.
      - If there are no concrete issues, say so.
      - End with one fenced `json` block containing:
        {{
          "summary": "short summary",
          "findings": [
            {{
              "file": "filename",
              "line": 1,
              "severity": "low|medium|high",
              "blocking": true,
              "comment": "short actionable comment"
            }}
          ],
          "check_conclusion": "success|failure"
        }}
    depends_on: [prepare_context]
"""


def run_case(input: dict[str, Any], *, workflow_name: str, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"simple-review-{input['name']}-") as temp_dir:
        path = Path(temp_dir) / input["filename"]
        path.write_text(input["content"], encoding="utf-8")
        completed = run_archon(workflow_name, path, timeout=timeout)
    output = completed.stdout
    return {
        "returncode": completed.returncode,
        "stdout_tail": output[-4000:],
        "payload": extract_json_payload(output),
    }


def run_archon(workflow_name: str, path: Path, *, timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CODEX_BIN_PATH", "/usr/bin/codex")
    return subprocess.run(
        ["archon", "workflow", "run", workflow_name, json.dumps({"path": str(path)})],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


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


def must_include_terms(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    text = searchable_output(output)
    terms = [term.lower() for term in expected["must_include"]]
    found = [term for term in terms if term in text]
    return Score(
        name="must_include_terms",
        score=1.0 if len(found) == len(terms) else len(found) / len(terms),
        metadata={"found": found, "missing": [term for term in terms if term not in found]},
    )


def avoids_forbidden_terms(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    text = searchable_output(output)
    terms = [term.lower() for term in expected["must_not_include"]]
    found = [term for term in terms if term in text]
    return Score(
        name="avoids_forbidden_terms",
        score=1.0 if not found else 0.0,
        metadata={"forbidden_found": found},
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


def searchable_output(output: dict[str, Any]) -> str:
    return (json.dumps(output.get("payload") or {}) + "\n" + output.get("stdout_tail", "")).lower()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
