from __future__ import annotations

import os
import re
from importlib import resources
from pathlib import Path
from typing import Any

import requests

APP_URL = os.environ.get("BRAINTRUST_APP_URL", "https://api.braintrust.dev")
API_VERSION = "2024-05-14"
DEFAULT_PROJECT = "My Project"


def get_api_key() -> str:
    key = os.environ.get("BRAINTRUST_API_KEY")
    if not key:
        raise RuntimeError("BRAINTRUST_API_KEY is not set")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "X-Bt-Integration-Type": "braintrust",
    }


def list_prompts(project_name: str) -> list[dict[str, Any]]:
    url = f"{APP_URL}/v1/prompt"
    response = requests.get(
        url,
        headers=_headers(),
        params={"project_name": project_name},
    )
    response.raise_for_status()
    return response.json().get("objects", [])


def upsert_prompt(
    *,
    project_name: str,
    slug: str,
    name: str,
    prompt_data: dict[str, Any],
    description: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create or replace a prompt in Braintrust."""
    url = f"{APP_URL}/v1/prompt"
    payload: dict[str, Any] = {
        "project_name": project_name,
        "slug": slug,
        "name": name,
        "prompt_data": prompt_data,
    }
    if description:
        payload["description"] = description
    if tags:
        payload["tags"] = tags

    response = requests.post(url, headers=_headers(), json=payload)
    response.raise_for_status()
    return response.json()


def read_local_prompts() -> dict[str, str]:
    """Return a mapping from slug to raw markdown text."""
    prompts: dict[str, str] = {}
    prompts_dir = resources.files("code_reviewer").joinpath("prompts")
    for path in prompts_dir.iterdir():
        if path.name.endswith(".md"):
            slug = path.name[: -len(".md")]
            prompts[slug] = path.read_text(encoding="utf-8")
    return prompts


def translate_archon_variables(text: str) -> str:
    """Convert Archon-style $VAR and $node.output to Mustache {{VAR}} syntax."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        suffix = match.group(2) or ""
        if suffix == ".output":
            return "{{" + name + "_output}}"
        return "{{" + name + "}}"

    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)(\.output)?", replace, text)


def build_chat_prompt_data(text: str) -> dict[str, Any]:
    translated = translate_archon_variables(text)
    return {
        "type": "chat",
        "messages": [
            {
                "role": "user",
                "content": translated,
            }
        ],
    }


def sync_prompts(
    *,
    project_name: str = DEFAULT_PROJECT,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    local_prompts = read_local_prompts()
    if not local_prompts:
        raise RuntimeError("No local .md prompts found")

    if not dry_run:
        get_api_key()

    results = []
    for slug, text in sorted(local_prompts.items()):
        prompt_data = build_chat_prompt_data(text)
        description = f"Synced from code-reviewer prompts/{slug}.md"
        if dry_run:
            results.append({
                "slug": slug,
                "name": slug,
                "description": description,
                "prompt_data": prompt_data,
                "dry_run": True,
            })
            continue

        result = upsert_prompt(
            project_name=project_name,
            slug=slug,
            name=slug,
            prompt_data=prompt_data,
            description=description,
            tags=["code-reviewer", "auto-sync"],
        )
        results.append(result)
    return results
