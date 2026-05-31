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


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
