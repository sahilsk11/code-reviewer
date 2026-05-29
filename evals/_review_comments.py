from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def flatten_pages(pages: Any) -> list[dict[str, Any]]:
    if isinstance(pages, list) and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages if isinstance(pages, list) else []


def compact_review_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "author": (comment.get("user") or {}).get("login"),
        "body": comment.get("body") or "",
        "commit_id": comment.get("commit_id"),
        "created_at": comment.get("created_at"),
        "html_url": comment.get("html_url"),
        "line": comment.get("line"),
        "original_line": comment.get("original_line"),
        "path": comment.get("path"),
        "url": comment.get("url"),
    }


def review_comment_title(body: str) -> str:
    first_line = body.strip().splitlines()[0] if body.strip() else "Imported review finding"
    first_line = re.sub(r"<[^>]+>", "", first_line)
    first_line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", first_line)
    first_line = first_line.replace("**", "").strip()
    return re.sub(r"\s+", " ", first_line) or "Imported review finding"


def review_comment_priority(body: str) -> str | None:
    match = re.search(r"\bP([0-3])\b", body)
    return f"P{match.group(1)}" if match else None


def review_comment_severity(body: str) -> str:
    priority = review_comment_priority(body)
    if not priority:
        return "unknown"
    return {"P0": "high", "P1": "high", "P2": "medium", "P3": "low"}[priority]


def review_comment_terms(body: str, title: str) -> list[str]:
    code_terms = [term.strip() for term in re.findall(r"`([^`]+)`", body) if term.strip()]
    title_terms = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", title)
        if word.lower() not in {"badge", "should", "review", "finding"}
    ]
    terms: list[str] = []
    for term in code_terms + title_terms:
        if term not in terms:
            terms.append(term)
        if len(terms) >= 5:
            break
    return terms
