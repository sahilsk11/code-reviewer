from __future__ import annotations

import json
from pathlib import Path

from evals.crumb_review_v0 import (
    expected_files_present,
    expected_terms_present,
    forbidden_terms_absent,
    load_cases,
    materialize_case,
    no_findings_when_expected,
    render_crumb_prompt,
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
