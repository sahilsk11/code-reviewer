from __future__ import annotations

from pathlib import Path

from code_reviewer.workflow_builder import WorkflowConfig, render_workflow, write_workflow


def test_render_workflow_uses_configured_harness_model_and_prompt() -> None:
    workflow = render_workflow(
        WorkflowConfig(name="ai-code-review-test", harness="codex", model="gpt-test")
    )

    assert "name: ai-code-review-test" in workflow
    assert "provider: codex" in workflow
    assert "model: gpt-test" in workflow
    assert "Identify the canonical implementation transcript" in workflow
    assert "Review this PR for correctness and regressions." in workflow
    assert "depends_on: [aggregate_dedupe]" in workflow


def test_write_workflow_creates_parent_directory(tmp_path: Path) -> None:
    destination = tmp_path / ".archon" / "workflows" / "review.yaml"

    result = write_workflow(
        destination,
        WorkflowConfig(name="review", harness="opencode", model="model-a"),
    )

    assert result == destination
    assert destination.exists()
    assert "model: model-a" in destination.read_text(encoding="utf-8")
