from __future__ import annotations

import json

from code_reviewer.github_app_manifest import build_manifest, render_manifest


def test_default_manifest_has_code_review_app_contract() -> None:
    manifest = build_manifest()

    assert manifest["default_events"] == ["pull_request"]
    assert manifest["hook_attributes"]["active"] is True
    assert manifest["hook_attributes"]["url"].endswith("/github-code-review-app")
    assert manifest["default_permissions"]["contents"] == "read"
    assert manifest["default_permissions"]["pull_requests"] == "write"
    assert manifest["default_permissions"]["checks"] == "write"


def test_manifest_overrides_operator_values() -> None:
    manifest = build_manifest(
        name="Example Reviewer",
        url="https://reviewer.example.test",
        webhook_url="https://sas.example.test/github-code-review-app",
        redirect_url="https://reviewer.example.test/github-app/callback",
        callback_urls=["https://reviewer.example.test/oauth/callback"],
        setup_url="https://reviewer.example.test/setup",
    )

    assert manifest["name"] == "Example Reviewer"
    assert manifest["url"] == "https://reviewer.example.test"
    assert manifest["hook_attributes"]["url"] == (
        "https://sas.example.test/github-code-review-app"
    )
    assert manifest["redirect_url"] == "https://reviewer.example.test/github-app/callback"
    assert manifest["callback_urls"] == ["https://reviewer.example.test/oauth/callback"]
    assert manifest["setup_url"] == "https://reviewer.example.test/setup"


def test_render_manifest_outputs_json_object_with_trailing_newline() -> None:
    rendered = render_manifest(build_manifest(name="Example Reviewer"))

    assert rendered.endswith("\n")
    assert json.loads(rendered)["name"] == "Example Reviewer"
