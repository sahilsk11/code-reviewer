from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from importlib import resources
from typing import Any

RESOURCE_PACKAGE = "code_reviewer.resources"
MANIFEST_RESOURCE = "github-app-manifest.json"


def default_manifest() -> dict[str, Any]:
    manifest_text = (
        resources.files(RESOURCE_PACKAGE)
        .joinpath(MANIFEST_RESOURCE)
        .read_text(encoding="utf-8")
    )
    data = json.loads(manifest_text)
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_RESOURCE} must contain a JSON object")
    return data


def build_manifest(
    *,
    name: str | None = None,
    url: str | None = None,
    webhook_url: str | None = None,
    redirect_url: str | None = None,
    callback_urls: Iterable[str] | None = None,
    setup_url: str | None = None,
) -> dict[str, Any]:
    manifest = copy.deepcopy(default_manifest())

    if name:
        manifest["name"] = name
    if url:
        manifest["url"] = url
    if webhook_url:
        hook_attributes = manifest.setdefault("hook_attributes", {})
        if not isinstance(hook_attributes, dict):
            raise ValueError("manifest hook_attributes must be an object")
        hook_attributes["url"] = webhook_url
    if redirect_url:
        manifest["redirect_url"] = redirect_url
    if callback_urls is not None:
        manifest["callback_urls"] = list(callback_urls)
    if setup_url:
        manifest["setup_url"] = setup_url

    return manifest


def render_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"
