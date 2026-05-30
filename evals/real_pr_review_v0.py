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
from code_reviewer.env import load_local_env

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "evals" / "real_pr_cases"


def main(argv: list[str] | None = None) -> int:
    load_local_env(REPO_ROOT)
    parser = argparse.ArgumentParser(description="Braintrust eval for frozen real PR review cases.")
    parser.add_argument("--project", default=os.environ.get("BRAINTRUST_PROJECT", "Code Reviewer"))
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--teacher-model", default="gpt-5.5")
    parser.add_argument("--judge-model", default="gpt-5.5")
    parser.add_argument("--refresh-teacher", action="store_true")
    parser.add_argument("--judge", action="store_true")
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
        args.project,
        experiment_name=f"real-pr-review-v0-{slug(args.model)}",
        data=cases,
        task=lambda input: review_case(
            input,
            model=args.model,
            judge_model=args.judge_model if args.judge else None,
            timeout=args.timeout,
        ),
        scores=[
            json_payload_present,
            expected_conclusion_matches,
            expected_finding_recall,
            expected_file_recall,
            conclusion_matches_teacher,
            finding_count_close_to_teacher,
            teacher_file_overlap,
            avoids_extra_findings,
            judge_groundedness,
            judge_actionability,
            judge_risk_relevance,
            judge_noise,
            judge_overall_usefulness,
        ],
        metadata={
            "runner": "evals/real_pr_review_v0.py",
            "model": args.model,
            "teacher_model": args.teacher_model,
            "judge_model": args.judge_model if args.judge else None,
        },
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def load_cases() -> list[dict[str, Any]]:
    cases = []
    for path in sorted(CASE_DIR.glob("*.json")):
        if path.name.endswith(".teacher.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = data.get("expected") or {}
        teacher_path = path.with_suffix(".teacher.json")
        if teacher_path.exists():
            expected = expected | json.loads(teacher_path.read_text(encoding="utf-8"))
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


def review_case(
    input: dict[str, Any],
    *,
    model: str,
    judge_model: str | None = None,
    timeout: int,
) -> dict[str, Any]:
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
    result = {
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
        "markdown": markdown,
        "payload": extract_json_payload(markdown),
    }
    if judge_model:
        result["judge"] = judge_review(input, review=result, model=judge_model, timeout=timeout)
    return result


def judge_review(
    input: dict[str, Any],
    *,
    review: dict[str, Any],
    model: str,
    timeout: int,
) -> dict[str, Any] | None:
    prompt = f"""You are judging an AI code review for usefulness.
Given the PR diff and the review output, grade whether the review is useful.

Focus on:
- groundedness: comments are supported by the diff
- actionability: comments tell the author what to fix or investigate
- risk_relevance: comments identify correctness/regression risk, not style noise
- noise: low is good; high means distracting or generic comments
- overall_usefulness: whether this review would help a busy maintainer

Return exactly one fenced json block:
{{
  "groundedness": 0.0,
  "actionability": 0.0,
  "risk_relevance": 0.0,
  "noise": 0.0,
  "overall_usefulness": 0.0,
  "rationale": "one short paragraph"
}}

Use numbers between 0 and 1. For noise, 0 means no noise and 1 means very noisy.

PR title: {input["title"]}

PR body:
{input["body"]}

Diff:
```diff
{input["diff"]}
```

Review output:
```json
{json.dumps(review.get("payload") or review.get("markdown"), indent=2)}
```
"""
    with tempfile.NamedTemporaryFile(prefix="real-pr-judge-v0-", suffix=".md") as output_file:
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
    payload = extract_json_payload(markdown)
    if payload is None:
        return {
            "returncode": completed.returncode,
            "markdown": markdown,
            "error": "missing judge json",
        }
    payload["returncode"] = completed.returncode
    return payload


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


def expected_conclusion_matches(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    wanted = expected.get("check_conclusion")
    if not wanted:
        return Score(name="expected_conclusion_matches", score=None, metadata={"reason": "missing labels"})
    actual = (output.get("payload") or {}).get("check_conclusion")
    return Score(
        name="expected_conclusion_matches",
        score=1.0 if actual == wanted else 0.0,
        metadata={"actual": actual, "expected": wanted},
    )


def expected_finding_recall(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    labels = expected.get("findings")
    if not isinstance(labels, list) or not labels:
        return Score(name="expected_finding_recall", score=None, metadata={"reason": "missing labels"})
    text = searchable_review_text(output)
    found = [label["id"] for label in labels if all(term.lower() in text for term in label.get("must_include", []))]
    return Score(
        name="expected_finding_recall",
        score=len(found) / len(labels),
        metadata={"found": found, "missing": [label["id"] for label in labels if label["id"] not in found]},
    )


def expected_file_recall(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    labels = expected.get("findings")
    if not isinstance(labels, list) or not labels:
        return Score(name="expected_file_recall", score=None, metadata={"reason": "missing labels"})
    student_files = finding_files(output.get("payload") or {})
    expected_files = {str(label["file"]) for label in labels if label.get("file")}
    overlap = expected_files & student_files
    return Score(
        name="expected_file_recall",
        score=len(overlap) / len(expected_files),
        metadata={"expected_files": sorted(expected_files), "student_files": sorted(student_files)},
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


def judge_groundedness(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return judge_score("judge_groundedness", output, "groundedness")


def judge_actionability(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return judge_score("judge_actionability", output, "actionability")


def judge_risk_relevance(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return judge_score("judge_risk_relevance", output, "risk_relevance")


def judge_noise(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    judge = output.get("judge")
    if not isinstance(judge, dict) or not isinstance(judge.get("noise"), int | float):
        return Score(name="judge_noise", score=None, metadata={"reason": "missing judge"})
    return Score(
        name="judge_noise",
        score=1.0 - float(judge["noise"]),
        metadata={"raw_noise": judge["noise"], "rationale": judge.get("rationale")},
    )


def judge_overall_usefulness(input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]) -> Score:
    return judge_score("judge_overall_usefulness", output, "overall_usefulness")


def judge_score(name: str, output: dict[str, Any], key: str) -> Score:
    judge = output.get("judge")
    if not isinstance(judge, dict) or not isinstance(judge.get(key), int | float):
        return Score(name=name, score=None, metadata={"reason": "missing judge"})
    return Score(
        name=name,
        score=float(judge[key]),
        metadata={"rationale": judge.get("rationale")},
    )


def finding_files(payload: dict[str, Any]) -> set[str]:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return set()
    return {str(item.get("file")) for item in findings if isinstance(item, dict) and item.get("file")}


def searchable_review_text(output: dict[str, Any]) -> str:
    return json.dumps(output.get("payload") or {}).lower() + "\n" + output.get("markdown", "").lower()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    sys.exit(main())
