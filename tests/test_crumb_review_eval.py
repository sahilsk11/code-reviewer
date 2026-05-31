from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evals import crumb_review_v0
from evals.crumb_review_v0 import (
    EvalInfrastructureError,
    expected_files_present,
    expected_terms_present,
    forbidden_terms_absent,
    load_cases,
    materialize_case,
    no_findings_when_expected,
    render_crumb_prompt,
    run_codex_prompt,
    run_crumb_case,
)


def test_load_cases_filters_by_crumb_id(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    (case_dir / "keep.json").write_text(
        json.dumps(
            {
                "name": "keep",
                "crumb_id": "reviewer_correctness_regressions",
                "repo": {"base_files": {}, "changed_files": {}},
                "expected": {},
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "skip.json").write_text(
        json.dumps(
            {
                "name": "skip",
                "crumb_id": "summarize_intent",
                "repo": {"base_files": {}, "changed_files": {}},
                "expected": {},
            }
        ),
        encoding="utf-8",
    )

    cases = load_cases(case_dir, crumb_id="reviewer_correctness_regressions")

    assert [case["metadata"]["case"] for case in cases] == ["keep"]


def test_materialize_case_creates_real_git_history_and_manifest(tmp_path: Path) -> None:
    case = {
        "name": "sample",
        "crumb_id": "reviewer_correctness_regressions",
        "input": {"repository": "eval/sample", "pull_request_number": 7},
        "repo": {
            "base_files": {"app.py": "def value():\n    return 1\n"},
            "changed_files": {"app.py": "def value():\n    return 2\n"},
        },
    }

    materialized = materialize_case(case, tmp_path)

    assert (materialized.repo_path / "app.py").read_text(encoding="utf-8") == (
        "def value():\n    return 2\n"
    )
    assert materialized.base_sha != materialized.head_sha
    assert "-    return 1" in materialized.diff
    assert "+    return 2" in materialized.diff
    manifest = json.loads(materialized.manifest_path.read_text(encoding="utf-8"))
    assert manifest["repository"] == "eval/sample"
    assert manifest["pr_number"] == 7
    assert manifest["worktree_path"] == str(materialized.repo_path)


def test_render_crumb_prompt_substitutes_archon_context(tmp_path: Path) -> None:
    case = {
        "name": "sample",
        "crumb_id": "reviewer_correctness_regressions",
        "input": {},
        "repo": {
            "base_files": {"app.py": "def value():\n    return 1\n"},
            "changed_files": {"app.py": "def value():\n    return 2\n"},
        },
        "upstream": {"summarize_intent_output": "Intent brief from eval."},
    }
    materialized = materialize_case(case, tmp_path)

    prompt = render_crumb_prompt("reviewer_correctness_regressions", materialized)

    assert "$ARGUMENTS" not in prompt
    assert "$prepare_worktree.output" not in prompt
    assert "$summarize_intent.output" not in prompt
    assert str(materialized.manifest_path) in prompt
    assert "Intent brief from eval." in prompt
    assert materialized.head_sha in prompt


def test_render_crumb_prompt_does_not_substitute_inside_values(tmp_path: Path) -> None:
    case = {
        "name": "sample",
        "crumb_id": "reviewer_correctness_regressions",
        "input": {"repository": "eval/$prepare_worktree.output"},
        "repo": {
            "base_files": {"app.py": "def value():\n    return 1\n"},
            "changed_files": {"app.py": "def value():\n    return 2\n"},
        },
    }
    materialized = materialize_case(case, tmp_path)

    prompt = render_crumb_prompt("reviewer_correctness_regressions", materialized)

    assert '"repository": "eval/$prepare_worktree.output"' in prompt
    assert str(materialized.manifest_path) in prompt


def test_scoring_helpers_measure_terms_files_and_forbidden_noise() -> None:
    output = {
        "markdown": (
            "Finding: `delete_user` no longer calls `require_admin`, allowing a "
            "non-admin request to mutate users in app.py."
        )
    }
    expected = {
        "must_include": ["delete_user", "require_admin", "non-admin"],
        "expected_files": ["app.py"],
        "should_not_include": ["nit", "formatting"],
    }

    assert expected_terms_present({}, output, expected).score == 1.0
    assert expected_files_present({}, output, expected).score == 1.0
    assert forbidden_terms_absent({}, output, expected).score == 1.0


def test_no_findings_score_accepts_clean_review_output() -> None:
    output = {"markdown": "No high-confidence findings."}

    score = no_findings_when_expected({}, output, {"no_findings": True})

    assert score.score == 1.0


def test_no_findings_score_ignores_format_echo_without_finding_block() -> None:
    output = {
        "markdown": (
            "No regressions detected.\n\n"
            "If there were findings, they would include `source: new_finding` "
            "and `blocking: true`."
        )
    }

    score = no_findings_when_expected({}, output, {"no_findings": True})

    assert score.score == 1.0


def test_no_findings_score_rejects_actual_finding_block() -> None:
    output = {
        "markdown": (
            "Finding:\n"
            "severity: medium\n"
            "blocking: true\n"
            "source: new_finding\n"
        )
    }

    score = no_findings_when_expected({}, output, {"no_findings": True})

    assert score.score == 0.0


def test_run_codex_prompt_returns_scored_timeout(monkeypatch, tmp_path: Path) -> None:
    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=1, stderr="timed out")

    monkeypatch.setattr(crumb_review_v0.subprocess, "run", timeout_run)

    markdown, completed = run_codex_prompt("prompt", cwd=tmp_path, model="model", timeout=1)

    assert markdown == ""
    assert completed.returncode == 124
    assert "timed out" in completed.stderr


def test_run_crumb_case_returns_scored_infrastructure_failure(monkeypatch) -> None:
    def fail_materialize(*args, **kwargs):
        raise EvalInfrastructureError("git failed", stderr="fatal: no git")

    monkeypatch.setattr(crumb_review_v0, "materialize_case", fail_materialize)

    result = run_crumb_case(
        {
            "name": "sample",
            "crumb_id": "reviewer_correctness_regressions",
            "repo": {"base_files": {}, "changed_files": {}},
        },
        model="model",
        timeout=1,
    )

    assert result["returncode"] == 1
    assert result["error"] == "git failed"
    assert result["stderr_tail"] == "fatal: no git"
