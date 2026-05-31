from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def load_json_arg(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("JSON payload must be an object")
    return data


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"JSON file must contain an object: {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def gh_json(args: Sequence[str]) -> dict[str, Any]:
    result = run(["gh", *args])
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise SystemExit(f"gh returned non-object JSON for: gh {' '.join(args)}")
    return data


def first_json_value(text: str) -> Any | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        return data
    return None


def resolve_repository_and_pr(
    payload: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[str, int]:
    context = context or {}
    manifest = manifest or {}
    repository = payload.get("repository") or context.get("repository") or manifest.get("repository")
    pr_number = (
        payload.get("pull_request_number")
        or context.get("pr_number")
        or manifest.get("pr_number")
    )
    parsed_repository, parsed_number = parse_pr_url(
        payload.get("pull_request_url") if isinstance(payload.get("pull_request_url"), str) else None
    )
    repository = repository or parsed_repository
    pr_number = pr_number or parsed_number
    if not isinstance(repository, str) or not repository:
        raise SystemExit("Need repository or pull_request_url")
    if not isinstance(pr_number, int):
        raise SystemExit("Need pull_request_number or pull_request_url")
    return repository, pr_number


def parse_pr_url(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    match = re.search(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", value)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def sanitize_path_part(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = text.strip(".-")
    return text or "unknown"


def manifest_path_for(worktree_path: Path) -> Path:
    return Path.home() / ".code-reviews" / "manifests" / f"{worktree_path.name}.json"
