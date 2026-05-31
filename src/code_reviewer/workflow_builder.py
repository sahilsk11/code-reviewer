from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

WORKFLOW_NAME = "ai-code-review"
WORKFLOW_FILENAME = f"{WORKFLOW_NAME}.yaml"
DEFAULT_HARNESS = "opencode"
DEFAULT_MODEL = "opencode-go/deepseek-v4-pro"
DEFAULT_ADDITIONAL_DIRECTORIES: tuple[str, ...] = ()
AGENT_MAX_ATTEMPTS = 2
AGENT_IDLE_TIMEOUT_MS = 180000
BASH_NODE_IDS = (
    "prepare_worktree",
    "collect_github_context",
    "find_implementation_transcript",
    "summarize_intent",
    "publish_review",
    "cleanup_worktree",
)


@dataclass(frozen=True)
class WorkflowConfig:
    name: str = WORKFLOW_NAME
    harness: str = DEFAULT_HARNESS
    model: str = DEFAULT_MODEL
    additional_directories: tuple[str, ...] = DEFAULT_ADDITIONAL_DIRECTORIES


@dataclass(frozen=True)
class AgentNode:
    id: str
    prompt_file: str
    depends_on: tuple[str, ...] = ()


AGENT_NODES = (
    AgentNode(
        "reviewer_correctness_regressions",
        "reviewer_correctness_regressions.md",
        ("summarize_intent",),
    ),
    AgentNode(
        "reviewer_design_layering_reuse",
        "reviewer_design_layering_reuse.md",
        ("summarize_intent",),
    ),
    AgentNode(
        "reviewer_simplicity_alternatives",
        "reviewer_simplicity_alternatives.md",
        ("summarize_intent",),
    ),
    AgentNode(
        "aggregate_dedupe",
        "aggregate_dedupe.md",
        (
            "collect_github_context",
            "reviewer_correctness_regressions",
            "reviewer_design_layering_reuse",
            "reviewer_simplicity_alternatives",
        ),
    ),
)


def render_workflow(config: WorkflowConfig) -> str:
    lines = [
        f"name: {config.name}",
        "description: |",
        *indent_lines(
            [
                "Use when: A GitHub pull request needs a required AI Code Review check backed by",
                "Archon and the code-review Python CLI.",
                "Input: JSON from the code-review CLI with repo URL/path, PR URL/number, exact",
                "head SHA, base SHA when available, and requested review mode.",
                "Output: Stable PR summary comment, high-confidence inline comments, final check",
                "conclusion, and cleaned-up temporary worktree.",
                "NOT for: Ad hoc local linting, broad product planning, or non-PR review.",
            ],
            2,
        ),
        "",
        f"provider: {config.harness}",
        f"model: {config.model}",
    ]
    if config.additional_directories:
        lines.append("additionalDirectories:")
        lines.extend(f"  - {directory}" for directory in config.additional_directories)
    lines.extend(
        [
            "worktree:",
            "  enabled: false",
            "",
            "",
            "nodes:",
            f"  - id: {BASH_NODE_IDS[0]}",
            "    bash: |",
            '      set -euo pipefail',
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.prepare_worktree \\',
            '        --payload-json "$ARGUMENTS" \\',
            '        --worktree-root "$HOME/wt"',
            "",
            f"  - id: {BASH_NODE_IDS[1]}",
            "    bash: |",
            '      set -euo pipefail',
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.collect_github_context \\',
            '        --payload-json "$ARGUMENTS"',
            "",
            f"  - id: {BASH_NODE_IDS[2]}",
            "    bash: |",
            '      set -euo pipefail',
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.discover_transcripts \\',
            '        --payload-json "$ARGUMENTS" \\',
            '        --kanna-root "$HOME/.kanna" \\',
            '        --cleaner loki \\',
            '        --optional \\',
            '        --select',
            "",
            f"  - id: {BASH_NODE_IDS[3]}",
            "    bash: |",
            '      set -euo pipefail',
            '      transcript_selection_file="$(mktemp)"',
            '      trap \'rm -f "$transcript_selection_file"\' EXIT',
            '      cat > "$transcript_selection_file" <<\'CODE_REVIEW_TRANSCRIPT_SELECTION\'',
            "      $find_implementation_transcript.output",
            "      CODE_REVIEW_TRANSCRIPT_SELECTION",
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.summarize_intent \\',
            '        --payload-json "$ARGUMENTS" \\',
            '        --github-context "$collect_github_context.output" \\',
            '        --worktree-manifest "$prepare_worktree.output" \\',
            '        --transcript-selection-file "$transcript_selection_file"',
            "    depends_on:",
            "      - prepare_worktree",
            "      - collect_github_context",
            "      - find_implementation_transcript",
            "",
        ]
    )

    for node in AGENT_NODES:
        lines.extend(render_agent_node(node, config.model))

    lines.extend(
        [
            f"  - id: {BASH_NODE_IDS[4]}",
            "    bash: |",
            '      set -euo pipefail',
            '      aggregate_output_file="$(mktemp)"',
            '      trap \'rm -f "$aggregate_output_file"\' EXIT',
            '      cat > "$aggregate_output_file" <<\'CODE_REVIEW_AGGREGATE_OUTPUT\'',
            "      $aggregate_dedupe.output",
            "      CODE_REVIEW_AGGREGATE_OUTPUT",
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.publish_review \\',
            '        --payload-json "$ARGUMENTS" \\',
            '        --github-context "$collect_github_context.output" \\',
            '        --aggregate-output-file "$aggregate_output_file" \\',
            '        --worktree-manifest "$prepare_worktree.output"',
            "    depends_on:",
            "      - prepare_worktree",
            "      - collect_github_context",
            "      - aggregate_dedupe",
            "",
            f"  - id: {BASH_NODE_IDS[5]}",
            "    bash: |",
            '      set -euo pipefail',
            '      "${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.cleanup_worktree \\',
            '        --worktree-manifest "$prepare_worktree.output"',
            "    depends_on:",
            "      - prepare_worktree",
            "      - publish_review",
            "    trigger_rule: all_done",
            "",
        ]
    )
    return "\n".join(lines)


def render_agent_node(node: AgentNode, model: str) -> list[str]:
    lines = [
        f"  - id: {node.id}",
        "    context: fresh",
        f"    model: {model}",
        f"    idle_timeout: {AGENT_IDLE_TIMEOUT_MS}",
        "    retry:",
        f"      max_attempts: {AGENT_MAX_ATTEMPTS}",
        "      delay_ms: 10000",
        "      on_error: all",
        "    prompt: |",
        *indent_text(read_prompt(node.prompt_file), 6),
    ]
    if node.depends_on:
        if len(node.depends_on) == 1:
            lines.append(f"    depends_on: [{node.depends_on[0]}]")
        else:
            lines.append("    depends_on:")
            lines.extend(f"      - {dependency}" for dependency in node.depends_on)
    lines.append("")
    return lines


def read_prompt(name: str) -> str:
    return resources.files("code_reviewer").joinpath("prompts", name).read_text(
        encoding="utf-8"
    )


def write_workflow(destination: Path, config: WorkflowConfig) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_workflow(config), encoding="utf-8")
    return destination


def indent_text(text: str, spaces: int) -> list[str]:
    prefix = " " * spaces
    return [f"{prefix}{line}" if line else prefix.rstrip() for line in text.splitlines()]


def indent_lines(lines: list[str], spaces: int) -> list[str]:
    prefix = " " * spaces
    return [f"{prefix}{line}" if line else "" for line in lines]
