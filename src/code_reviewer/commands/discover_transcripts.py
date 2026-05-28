from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import load_json_arg, parse_pr_url, sanitize_path_part, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find and normalize matching Kanna transcripts.")
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--kanna-root", default="~/.kanna")
    parser.add_argument("--cleaner", default="builtin")
    parser.add_argument("--optional", action="store_true")
    args = parser.parse_args(argv)

    payload = load_json_arg(args.payload_json)
    kanna_root = Path(args.kanna_root).expanduser()
    data_dir = kanna_root / "data"
    transcripts_dir = data_dir / "transcripts"
    if not transcripts_dir.exists():
        if args.optional:
            print("none")
            return 0
        raise SystemExit(f"Kanna transcripts directory not found: {transcripts_dir}")

    pr_url = payload.get("pull_request_url")
    repository, pr_number = parse_pr_url(pr_url if isinstance(pr_url, str) else None)
    exact_terms, fallback_terms = build_search_terms(payload, repository, pr_number)
    output_root = Path.home() / ".code-reviews" / "transcripts"
    output_root.mkdir(parents=True, exist_ok=True)

    exact_matches: list[dict[str, Any]] = []
    fallback_matches: list[dict[str, Any]] = []
    for transcript_path in sorted(transcripts_dir.glob("*.jsonl")):
        try:
            raw_text = transcript_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matched_exact_terms = [term for term in exact_terms if term and term in raw_text]
        matched_fallback_terms = [term for term in fallback_terms if term and term in raw_text]
        if not matched_exact_terms and not matched_fallback_terms:
            continue
        session = normalize_kanna_transcript(transcript_path, data_dir)
        matched_terms = matched_exact_terms or matched_fallback_terms
        session["matched_terms"] = matched_terms
        out_path = output_root / f"{transcript_path.stem}.json"
        write_json(out_path, session)
        match = {
            "source_path": str(transcript_path),
            "normalized_path": str(out_path),
            "session_id": transcript_path.stem,
            "title": session.get("title"),
            "project_path": session.get("project_path"),
            "matched_terms": matched_terms,
            "message_count": len(session.get("messages", [])),
        }
        if matched_exact_terms:
            exact_matches.append(match)
        else:
            fallback_matches.append(match)

    matches = sorted(
        exact_matches or fallback_matches,
        key=lambda item: (len(item["matched_terms"]), item["message_count"]),
        reverse=True,
    )[:10]
    retained_paths = {match["normalized_path"] for match in matches}
    for match in exact_matches + fallback_matches:
        if match["normalized_path"] not in retained_paths:
            Path(match["normalized_path"]).unlink(missing_ok=True)

    summary_name = "unknown-pr"
    if repository and pr_number:
        summary_name = f"{sanitize_path_part(repository.replace('/', '-'))}-pr-{pr_number}"
    summary_path = output_root / f"{summary_name}-matches.json"
    write_json(
        summary_path,
        {
            "payload": payload,
            "cleaner": args.cleaner,
            "exact_terms": exact_terms,
            "fallback_terms": fallback_terms,
            "used_fallback": not bool(exact_matches),
            "matches": matches,
        },
    )
    print(summary_path)
    return 0


def build_search_terms(
    payload: dict[str, Any],
    repository: str | None,
    pr_number: int | None,
) -> tuple[list[str], list[str]]:
    exact_terms: list[str] = []
    fallback_terms: list[str] = []
    for key in ("pull_request_url", "head_sha"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            exact_terms.append(value)
    if repository and pr_number:
        exact_terms.append(f"https://github.com/{repository}/pull/{pr_number}")
        exact_terms.append(f"github.com/{repository}/pull/{pr_number}")
        exact_terms.append(f"{repository}#{pr_number}")
    if repository:
        fallback_terms.append(repository)
    return list(dict.fromkeys(exact_terms)), list(dict.fromkeys(fallback_terms))


def normalize_kanna_transcript(transcript_path: Path, data_dir: Path) -> dict[str, Any]:
    chat_id = transcript_path.stem
    chats = load_chats(data_dir)
    projects = load_projects(data_dir)
    chat = chats.get(chat_id, {})
    project_id = chat.get("projectId") if isinstance(chat.get("projectId"), str) else None
    messages = [
        message
        for row in read_jsonl(transcript_path)
        if (message := normalize_message(row)) is not None
    ]
    created_values = [message["created_at"] for message in messages if message.get("created_at")]
    return {
        "provider": "kanna",
        "session_id": chat_id,
        "title": chat.get("title") if isinstance(chat.get("title"), str) else None,
        "project_id": project_id,
        "project_path": projects.get(project_id or ""),
        "started_at": min(created_values) if created_values else chat.get("createdAt"),
        "updated_at": max(created_values) if created_values else chat.get("updatedAt"),
        "messages": messages,
        "metadata": {"source_path": str(transcript_path)},
    }


def normalize_message(row: dict[str, Any]) -> dict[str, Any] | None:
    kind = row.get("kind")
    if kind == "user_prompt":
        return {
            "id": row.get("_id"),
            "role": "user",
            "created_at": row.get("createdAt"),
            "text": str(row.get("content") or ""),
            "attachments": row.get("attachments") if isinstance(row.get("attachments"), list) else [],
            "metadata": {"steered": True} if row.get("steered") is True else {},
        }
    if kind == "assistant_text":
        return {
            "id": row.get("_id"),
            "role": "assistant",
            "created_at": row.get("createdAt"),
            "text": str(row.get("text") or ""),
            "attachments": [],
            "metadata": {},
        }
    if kind == "result":
        return {
            "id": row.get("_id"),
            "role": "result",
            "created_at": row.get("createdAt"),
            "text": str(row.get("result") or ""),
            "attachments": [],
            "metadata": {
                "subtype": row.get("subtype"),
                "is_error": row.get("isError"),
            },
        }
    return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows


def load_chats(data_dir: Path) -> dict[str, dict[str, Any]]:
    chats: dict[str, dict[str, Any]] = {}
    snapshot = load_snapshot(data_dir)
    for chat in snapshot.get("chats", []):
        if isinstance(chat, dict) and isinstance(chat.get("id"), str):
            chats[chat["id"]] = dict(chat)
    for event in read_jsonl(data_dir / "chats.jsonl"):
        chat_id = event.get("chatId")
        if not isinstance(chat_id, str):
            continue
        if event.get("type") == "chat_created":
            chats.setdefault(chat_id, {}).update(
                {
                    "id": chat_id,
                    "projectId": event.get("projectId"),
                    "title": event.get("title"),
                    "createdAt": event.get("timestamp"),
                    "updatedAt": event.get("timestamp"),
                }
            )
        elif event.get("type") == "chat_renamed":
            chats.setdefault(chat_id, {})["title"] = event.get("title")
    return chats


def load_projects(data_dir: Path) -> dict[str, str]:
    projects: dict[str, str] = {}
    snapshot = load_snapshot(data_dir)
    for project in snapshot.get("projects", []):
        if isinstance(project, dict) and isinstance(project.get("id"), str):
            local_path = project.get("localPath")
            if isinstance(local_path, str):
                projects[project["id"]] = local_path
    for event in read_jsonl(data_dir / "projects.jsonl"):
        if event.get("type") == "project_opened":
            project_id = event.get("projectId")
            local_path = event.get("localPath")
            if isinstance(project_id, str) and isinstance(local_path, str):
                projects[project_id] = local_path
    return projects


def load_snapshot(data_dir: Path) -> dict[str, Any]:
    snapshot_path = data_dir / "snapshot.json"
    if not snapshot_path.exists():
        return {}
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
