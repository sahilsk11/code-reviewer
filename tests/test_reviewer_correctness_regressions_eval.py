from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

from evals import reviewer_correctness_regressions as eval_module


def test_render_prompt_uses_real_prompt_and_archon_context(tmp_path: Path) -> None:
    case = {
        "name": "sample",
        "repo": "https://github.com/example/project.git",
        "base_sha": "base123",
        "head_sha": "head456",
        "title": "Sample PR",
    }
    manifest_path = tmp_path / "prepare_worktree_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    prompt = eval_module.render_prompt(
        case,
        manifest_path=manifest_path,
        diff="diff --git a/app.py b/app.py\n",
        diff_stat=" app.py | 1 +\n",
    )

    assert "Review this PR for correctness and regressions." in prompt
    assert "$ARGUMENTS" not in prompt
    assert "$prepare_worktree.output" not in prompt
    assert "$summarize_intent.output" not in prompt
    assert str(manifest_path) in prompt
    assert "Sample PR" in prompt
    assert "diff --git a/app.py b/app.py" in prompt


def test_clone_case_repo_checks_out_head_commit(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    git(source_repo, "init", "-q")
    git(source_repo, "config", "user.email", "eval@example.com")
    git(source_repo, "config", "user.name", "Eval")
    (source_repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(source_repo, "add", ".")
    git(source_repo, "commit", "-q", "-m", "base")
    base_sha = git(source_repo, "rev-parse", "HEAD").stdout.strip()
    (source_repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    git(source_repo, "commit", "-am", "head", "-q")
    head_sha = git(source_repo, "rev-parse", "HEAD").stdout.strip()

    repo_path = eval_module.clone_case_repo(
        {
            "name": "local",
            "repo": str(source_repo),
            "base_sha": base_sha,
            "head_sha": head_sha,
        },
        tmp_path / "work",
    )

    assert git(repo_path, "rev-parse", "HEAD").stdout.strip() == head_sha
    assert "value = 2" in (repo_path / "app.py").read_text(encoding="utf-8")


def test_scores_check_known_issue_terms() -> None:
    output = {
        "returncode": 0,
        "markdown": (
            "The count_blocking helper lets blocking_count override a "
            "per-comment blocking: true flag, so a blocking review can be "
            "treated as non-blocking."
        ),
        "stderr_tail": "",
    }
    case = {
        "must_notice_terms": [
            ["count_blocking"],
            ["blocking_count"],
            ["blocking: true", "per-comment"],
            ["mask", "override", "undercount", "ignore", "non-blocking"],
        ]
    }

    assert eval_module.completed({}, output, {}).score == 1.0
    assert eval_module.output_present({}, output, {}).score == 1.0
    known_issue = eval_module.known_issue_present(case, output, {})
    assert known_issue.score == 1.0


def test_known_issue_score_fails_when_review_misses_case_issue() -> None:
    output = {
        "markdown": (
            "No high-confidence correctness regressions or concrete defects "
            "were found in the provided diff."
        )
    }
    case = {
        "must_notice_terms": [
            ["count_blocking"],
            ["blocking_count"],
            ["blocking: true", "per-comment"],
            ["mask", "override", "undercount", "ignore", "non-blocking"],
        ]
    }

    known_issue = eval_module.known_issue_present(case, output, {})

    assert known_issue.score == 0.0
    metadata = cast(dict[str, Any], known_issue.metadata)
    assert metadata["missing"] == case["must_notice_terms"]


def test_review_quality_scores_explain_usefulness_dimensions() -> None:
    case = {
        "must_notice_terms": [
            ["count_blocking"],
            ["blocking_count"],
            ["blocking: true", "per-comment"],
            ["mask", "override", "undercount", "ignore", "non-blocking"],
        ]
    }
    output = {
        "markdown": (
            "This is a blocking correctness bug in count_blocking. Because "
            "blocking_count can override a per-comment blocking: true flag, "
            "the publisher can silently treat a blocking review as non-blocking."
        )
    }

    assert eval_module.no_false_clean_bill(case, output, {}).score == 1.0
    assert eval_module.evidence_specificity(case, output, {}).score == 1.0
    assert eval_module.actionable_finding(case, output, {}).score == 1.0
    assert eval_module.severity_reasonable(case, output, {}).score == 1.0
    assert eval_module.avoid_known_bad_claims(case, output, {}).score == 1.0


def test_review_quality_scores_penalize_clean_bill_on_known_bug() -> None:
    case = {
        "must_notice_terms": [
            ["count_blocking"],
            ["blocking_count"],
        ]
    }
    output = {
        "markdown": (
            "No high-confidence correctness regressions or concrete defects "
            "were found in the provided diff."
        )
    }

    assert eval_module.no_false_clean_bill(case, output, {}).score == 0.0
    assert eval_module.evidence_specificity(case, output, {}).score == 0.0
    assert eval_module.actionable_finding(case, output, {}).score == 0.0
    assert eval_module.severity_reasonable(case, output, {}).score == 0.0
    assert eval_module.avoid_known_bad_claims(case, output, {}).score == 0.0


def test_code_reviewer_case_captures_validated_pr8_regression() -> None:
    case = next(
        case
        for case in eval_module.CASES
        if case["name"] == "code-reviewer-publish-blocking-count-override"
    )

    assert case["source_pr"] == "https://github.com/sahilsk11/code-reviewer/pull/8"
    assert case["base_sha"] == "69c41ee0a1350dfa09818bce929eec5fdc06d758"
    assert case["head_sha"] == "b19ebf5093a7c82f04b980c2f332247a978232c8"
    assert case["validated_comments"][0]["grade"] == "partial"
    assert "blocking_count" in case["validated_comments"][0]["body"]
    assert any("undercount blocking comments" in item for item in case["must_notice"])
    assert ["count_blocking"] in case["must_notice_terms"]


def test_recent_validated_cases_capture_source_prs_and_terms() -> None:
    expected = {
        "sas-deploy-planner-missing-deployments-role": {
            "source_pr": "https://github.com/sahilsk11/sas/pull/149",
            "head_sha": "88c8918d425fe464b39e975481790fd9787ea941",
            "term": "deployments",
            "grade": "valid",
        },
        "sas-prefect-control-plane-tags-drift": {
            "source_pr": "https://github.com/sahilsk11/sas/pull/150",
            "head_sha": "8cef5a8c666b4edd70413f33fa268c4728921acf",
            "term": "CONTROL_PLANE_TAGS",
            "grade": "valid",
        },
        "sas-prefect-work-pool-create-failure": {
            "source_pr": "https://github.com/sahilsk11/sas/pull/150",
            "head_sha": "8cef5a8c666b4edd70413f33fa268c4728921acf",
            "term": "work pool",
            "grade": "partial",
        },
        "code-reviewer-braintrust-configure-crash": {
            "source_pr": "https://github.com/sahilsk11/code-reviewer/pull/2",
            "head_sha": "abca301c6b4927be21456fe6ee2cb3a50485dafd",
            "term": "configure_braintrust",
            "grade": "valid",
        },
        "kanna-opencode-concurrent-server-startup": {
            "source_pr": "https://github.com/sahilsk11/kanna/pull/17",
            "head_sha": "df59d72931d07e4e7288d986fed0571088f921fa",
            "term": "OpenCode",
            "grade": "valid",
        },
    }
    cases = {case["name"]: case for case in eval_module.CASES}

    for name, fields in expected.items():
        case = cases[name]
        assert case["source_pr"] == fields["source_pr"]
        assert case["head_sha"] == fields["head_sha"]
        assert case["validated_comments"][0]["grade"] == fields["grade"]
        assert any(fields["term"] in terms for terms in case["must_notice_terms"])


def test_all_cases_have_known_issue_terms() -> None:
    for case in eval_module.CASES:
        assert case["must_notice_terms"], case["name"]
        assert all(isinstance(terms, list) and terms for terms in case["must_notice_terms"])


def test_case_metadata_exposes_braintrust_filter_fields() -> None:
    case = next(
        case
        for case in eval_module.CASES
        if case["name"] == "code-reviewer-publish-blocking-count-override"
    )

    metadata = eval_module.case_metadata(case, model="gpt-test")

    assert metadata == {
        "eval_case": "code-reviewer-publish-blocking-count-override",
        "case": "code-reviewer-publish-blocking-count-override",
        "case_kind": "validated_pr",
        "repo": "https://github.com/sahilsk11/code-reviewer.git",
        "source_pr": "https://github.com/sahilsk11/code-reviewer/pull/8",
        "base_sha": "69c41ee0a1350dfa09818bce929eec5fdc06d758",
        "head_sha": "b19ebf5093a7c82f04b980c2f332247a978232c8",
        "model": "gpt-test",
        "prompt_node": "reviewer_correctness_regressions",
        "prompt_file": "src/code_reviewer/prompts/reviewer_correctness_regressions.md",
    }


def test_max_concurrency_default_can_be_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_EVAL_MAX_CONCURRENCY", "3")

    assert eval_module.default_max_concurrency() == 3


def test_positive_int_rejects_non_positive_values() -> None:
    assert eval_module.positive_int("1") == 1

    try:
        eval_module.positive_int("0")
    except Exception as exc:
        assert "must be >= 1" in str(exc)
    else:
        raise AssertionError("expected positive_int to reject zero")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
