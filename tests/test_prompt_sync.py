from __future__ import annotations

from code_reviewer import prompt_sync


def test_translate_archon_variables_preserves_shell_variables() -> None:
    text = "$ARGUMENTS $prepare_worktree.output $summarize_intent.output $HOME ${CODE_REVIEW_PYTHON:-python3}"

    assert prompt_sync.translate_archon_variables(text) == (
        "{{ARGUMENTS}} {{prepare_worktree_output}} {{summarize_intent_output}} "
        "$HOME ${CODE_REVIEW_PYTHON:-python3}"
    )


def test_read_local_prompts_follows_workflow_nodes() -> None:
    prompts = prompt_sync.read_local_prompts()

    assert [prompt.slug for prompt in prompts] == [
        "reviewer_correctness_regressions",
        "reviewer_design_layering_reuse",
        "reviewer_simplicity_alternatives",
        "aggregate_dedupe",
    ]
    assert prompts[0].prompt_file == "reviewer_correctness_regressions.md"
    assert "{{ARGUMENTS}}" in prompts[0].rendered_text


def test_sync_prompts_dry_run_returns_braintrust_prompt_inputs(monkeypatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)

    results = prompt_sync.sync_prompts(project_name="Code Reviewer", dry_run=True)

    assert len(results) == 4
    assert results[0].slug == "reviewer_correctness_regressions"
    assert results[0].project_name == "Code Reviewer"
    assert results[0].messages is not None
    assert results[0].messages[0]["role"] == "user"
    assert results[0].model
    assert results[0].metadata["workflow_node"] == "reviewer_correctness_regressions"
    assert "archon" in results[0].tags


def test_require_api_key_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)

    try:
        prompt_sync.require_api_key()
    except RuntimeError as exc:
        assert "BRAINTRUST_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing BRAINTRUST_API_KEY to fail")
