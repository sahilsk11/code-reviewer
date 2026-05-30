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
        "find_implementation_transcript",
        "summarize_intent",
        "reviewer_correctness_regressions",
        "reviewer_design_layering_reuse",
        "reviewer_simplicity_alternatives",
        "aggregate_dedupe",
        "publish_review",
    ]
    assert prompts[0].prompt_file == "find_implementation_transcript.md"
    assert "$HOME" in prompts[0].rendered_text
    assert "{{ARGUMENTS}}" in prompts[0].rendered_text


def test_sync_prompts_dry_run_returns_braintrust_prompt_inputs(monkeypatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)

    results = prompt_sync.sync_prompts(project_name="Code Reviewer", dry_run=True)

    assert len(results) == 7
    assert results[0]["slug"] == "find_implementation_transcript"
    assert results[0]["project_name"] == "Code Reviewer"
    assert results[0]["messages"][0]["role"] == "user"
    assert results[0]["model"]
    assert results[0]["metadata"]["workflow_node"] == "find_implementation_transcript"
    assert "archon" in results[0]["tags"]
