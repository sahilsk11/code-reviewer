from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, REPO_ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discover_resolves_github_remotes() -> None:
    discover = load_module("evals/discover_pr_review_cases.py")

    assert discover.repo_from_remote("git@github.com:sahilsk11/friday.git") == "sahilsk11/friday"
    assert discover.repo_from_remote("https://github.com/sahilsk11/overwatch.git") == "sahilsk11/overwatch"
    assert discover.repo_from_value("https://github.com/sahilsk11/friday/pull/35") == "sahilsk11/friday"


def test_discover_summarizes_codex_review_comment() -> None:
    discover = load_module("evals/discover_pr_review_cases.py")
    body = """**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Keep CI errors from being treated as "no checks"**

Details.
"""

    assert discover.review_comment_title(body) == 'Keep CI errors from being treated as "no checks"'
    assert discover.review_comment_severity(body) == "P1"
    assert discover.has_followup_signal("Fixed in 123abc with a regression test.")


def test_capture_imports_review_comment_as_weak_label() -> None:
    capture = load_module("evals/capture_pr_case.py")
    comment = {
        "body": "**<sub><sub>![P2 Badge](badge)</sub></sub>  Prefer resolution attempts when selecting latest diagnostics**\n\nUse `resolution_attempts`.",
        "path": "src/overwatch/store.py",
        "line": 385,
        "html_url": "https://example.com/comment",
    }

    label = capture.review_comment_to_label(comment)

    assert label["severity"] == "medium"
    assert label["file"] == "src/overwatch/store.py"
    assert label["line"] == 385
    assert "resolution_attempts" in label["must_include"]
