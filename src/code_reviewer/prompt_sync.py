from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from code_reviewer.env import braintrust_project, load_local_env
from code_reviewer.workflow_builder import BASH_NODE_IDS, AGENT_NODES, DEFAULT_MODEL, read_prompt

PROMPT_TAGS = ("code-reviewer", "archon", "auto-sync")


@dataclass(frozen=True)
class LocalPrompt:
    slug: str
    prompt_file: str
    raw_text: str
    rendered_text: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class SyncResult:
    slug: str
    name: str
    project_name: str
    prompt_file: str
    dry_run: bool
    metadata: dict[str, Any]
    braintrust_id: str | None = None
    messages: list[dict[str, str]] | None = None
    model: str | None = None
    tags: tuple[str, ...] = PROMPT_TAGS


def sync_prompts(
    *,
    project_name: str | None = None,
    dry_run: bool = False,
) -> list[SyncResult]:
    load_local_env()
    project_name = project_name or braintrust_project()
    local_prompts = read_local_prompts()
    if not local_prompts:
        raise RuntimeError("No local prompts found")
    current_git_sha = git_sha()

    if dry_run:
        return [
            dry_run_result(prompt, project_name=project_name, git_sha=current_git_sha)
            for prompt in local_prompts
        ]

    require_api_key()
    from braintrust import projects

    project = projects.create(name=project_name)
    results = []
    for prompt in local_prompts:
        metadata = prompt_metadata(prompt, git_sha=current_git_sha)
        saved = project.prompts.create(
            name=prompt.slug,
            slug=prompt.slug,
            description=f"Synced from code-reviewer prompts/{prompt.prompt_file}",
            messages=[{"role": "user", "content": prompt.rendered_text}],
            model=DEFAULT_MODEL,
            if_exists="replace",
            metadata=metadata,
            tags=PROMPT_TAGS,
        )
        results.append(
            SyncResult(
                slug=prompt.slug,
                name=prompt.slug,
                project_name=project_name,
                prompt_file=prompt.prompt_file,
                braintrust_id=getattr(saved, "id", None),
                dry_run=False,
                metadata=metadata,
            )
        )
    return results


def read_local_prompts() -> list[LocalPrompt]:
    prompts = []
    for node in AGENT_NODES:
        raw_text = read_prompt(node.prompt_file)
        prompts.append(
            LocalPrompt(
                slug=node.id,
                prompt_file=node.prompt_file,
                raw_text=raw_text,
                rendered_text=translate_archon_variables(raw_text),
                dependencies=node.depends_on,
            )
        )
    return prompts


def translate_archon_variables(text: str) -> str:
    names = archon_template_names()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        suffix = match.group(2) or ""
        if name not in names:
            return match.group(0)
        if suffix == ".output":
            return "{{" + name + "_output}}"
        return "{{" + name + "}}"

    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)(\.output)?", replace, text)


def archon_template_names() -> set[str]:
    return {"ARGUMENTS", *BASH_NODE_IDS, *(node.id for node in AGENT_NODES)}


def dry_run_result(prompt: LocalPrompt, *, project_name: str, git_sha: str | None) -> SyncResult:
    return SyncResult(
        slug=prompt.slug,
        name=prompt.slug,
        project_name=project_name,
        prompt_file=prompt.prompt_file,
        dry_run=True,
        metadata=prompt_metadata(prompt, git_sha=git_sha),
        messages=[{"role": "user", "content": prompt.rendered_text}],
        model=DEFAULT_MODEL,
    )


def prompt_metadata(prompt: LocalPrompt, *, git_sha: str | None) -> dict[str, Any]:
    return {
        "source": "code-reviewer",
        "prompt_file": f"src/code_reviewer/prompts/{prompt.prompt_file}",
        "workflow_node": prompt.slug,
        "dependencies": list(prompt.dependencies),
        "git_sha": git_sha,
    }


def require_api_key() -> None:
    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise RuntimeError("BRAINTRUST_API_KEY is not set")


def git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None
