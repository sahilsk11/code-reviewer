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
CASE_DIR = REPO_ROOT / "evals" / "real_pr_cases"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Braintrust eval for frozen real PR review cases.")
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--teacher-model", default="gpt-5.5")
    parser.add_argument("--refresh-teacher", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    cases = load_cases()
    if args.refresh_teacher:
        for case in cases:
            teacher = review_case(case["input"], model=args.teacher_model, timeout=args.timeout)
            case["expected"] = {"teacher": teacher["payload"], "teacher_model": args.teacher_model}
            save_teacher(case, teacher_model=args.teacher_model)

    result = Eval(
        PROJECT_NAME,
        experiment_name=f"real-pr-review-v0-{slug(args.model)}",
        data=cases,
        task=lambda input: review_case(input, model=args.model, timeout=args.timeout),
        scores=[
            json_payload_present,
            conclusion_matches_teacher,
            finding_count_close_to_teacher,
            teacher_file_overlap,
            avoids_extra_findings,
        ],
        metadata={
            "runner": "evals/real_pr_review_v0.py",
            "model": args.model,
            "teacher_model": args.teacher_model,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def load_cases() -> list[dict[str, Any]]:
    cases = []
    for path in sorted(CASE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        teacher_path = path.with_suffix(".teacher.json")
        expected = data.get("expected") or {}
        if teacher_path.exists():
            expected = json.loads(teacher_path.read_text(encoding="utf-8"))
        cases.append(
            {
                "input": data["input"] | {"case_path": str(path)},
                "expected": expected,
                "metadata": {
                    "case": path.stem,
                    "repo": data["source"]["repo"],
                    "pr": data["source"]["pr_number"],
                    "head_sha": data["input"]["head_sha"],
                },
            }
        )
    if not cases:
        raise SystemExit(f"No cases found in {CASE_DIR}")
    return cases


def save_teacher(case: dict[str, Any], *, teacher_model: str) -> None:
    path = Path(case["input"]["case_path"])
    teacher_path = path.with_suffix(".teacher.json")
    teacher_path.write_text(
        json.dumps(case["expected"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {teacher_path} ({teacher_model})")


def review_case(input: dict[str, Any], *, model: str, timeout: int) -> dict[str, Any]:
    prompt = f"""Review this frozen pull request diff.
Return only high-confidence correctness findings.
Ignore style-only feedback and generic test requests.
End with exactly one fenced json block using this shape:
{{
  "summary": "short summary",
  "findings": [
    {{
      "file": "path",
      "line": 1,
      "severity": "low|medium|high",
      "blocking": true,
      "comment": "short actionable comment"
    }}
  ],
  "check_conclusion": "success|failure"
}}

PR title: {input["title"]}
Repo: {input["repo"]}
Base SHA: {input["base_sha"]}
Head SHA: {input["head_sha"]}

PR body:
{input["body"]}

Diff stat:
{input["diff_stat"]}

Diff:
```diff
{input["diff"]}
```
"""
    with tempfile.NamedTemporaryFile(prefix="real-pr-review-v0-", suffix=".md") as output_file:
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
            "--model",
            model,
            "-",
        ]
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
    return {
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
        "markdown": markdown,
        "payload": extract_json_payload(markdown),
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
        metadata={"returncode": output.get("returncode"), "stderr_tail": output.get("stderr_tail")},
    )


def conclusion_matches_teacher(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    student = output.get("payload") or {}
    teacher = expected.get("teacher") or {}
    if not teacher:
        return Score(name="conclusion_matches_teacher", score=None, metadata={"reason": "missing teacher"})
    return Score(
        name="conclusion_matches_teacher",
        score=1.0 if student.get("check_conclusion") == teacher.get("check_conclusion") else 0.0,
        metadata={"student": student.get("check_conclusion"), "teacher": teacher.get("check_conclusion")},
    )


def finding_count_close_to_teacher(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    student_count = len((output.get("payload") or {}).get("findings") or [])
    teacher_count = len((expected.get("teacher") or {}).get("findings") or [])
    return Score(
        name="finding_count_close_to_teacher",
        score=1.0 if abs(student_count - teacher_count) <= 1 else 0.0,
        metadata={"student_count": student_count, "teacher_count": teacher_count},
    )


def teacher_file_overlap(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    teacher_files = finding_files(expected.get("teacher") or {})
    student_files = finding_files(output.get("payload") or {})
    if not teacher_files:
        return Score(name="teacher_file_overlap", score=1.0 if not student_files else 0.0)
    overlap = sorted(teacher_files & student_files)
    return Score(
        name="teacher_file_overlap",
        score=len(overlap) / len(teacher_files),
        metadata={"teacher_files": sorted(teacher_files), "student_files": sorted(student_files)},
    )


def avoids_extra_findings(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    teacher_count = len((expected.get("teacher") or {}).get("findings") or [])
    student_count = len((output.get("payload") or {}).get("findings") or [])
    allowed = teacher_count + 1
    return Score(
        name="avoids_extra_findings",
        score=1.0 if student_count <= allowed else 0.0,
        metadata={"student_count": student_count, "allowed": allowed},
    )


def finding_files(payload: dict[str, Any]) -> set[str]:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return set()
    return {str(item.get("file")) for item in findings if isinstance(item, dict) and item.get("file")}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
