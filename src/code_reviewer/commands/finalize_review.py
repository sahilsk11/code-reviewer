from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from code_reviewer.commands import cleanup_worktree


JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?:publish_payload)?\s*(?P<body>.*?)\s*```",
    re.IGNORECASE | re.DOTALL,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean the review worktree and exit non-zero for blocking findings."
    )
    aggregate_group = parser.add_mutually_exclusive_group(required=True)
    aggregate_group.add_argument("--aggregate-output")
    aggregate_group.add_argument("--aggregate-output-file", type=Path)
    parser.add_argument("--worktree-manifest", required=True)
    args = parser.parse_args(argv)

    aggregate_output = args.aggregate_output
    if args.aggregate_output_file is not None:
        aggregate_output = args.aggregate_output_file.read_text()

    payload = extract_publish_payload(aggregate_output)
    cleanup_status = cleanup_worktree.main(
        ["--worktree-manifest", args.worktree_manifest]
    )
    if cleanup_status != 0:
        return cleanup_status

    validation_error = validate_publish_payload(payload)
    if validation_error:
        print(
            json.dumps(
                {
                    "check_conclusion": "failure",
                    "blocking_count": 0,
                    "reason": validation_error,
                },
                sort_keys=True,
            )
        )
        return 1

    blocking_count = count_blocking_findings(payload)
    if blocking_count > 0:
        print(
            json.dumps(
                {
                    "check_conclusion": "failure",
                    "blocking_count": blocking_count,
                    "reason": "blocking_findings",
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "check_conclusion": "success",
                "blocking_count": blocking_count,
                "reason": "no_blocking_findings",
            },
            sort_keys=True,
        )
    )
    return 0


def extract_publish_payload(text: str) -> dict[str, Any]:
    candidates = [match.group("body") for match in JSON_FENCE_RE.finditer(text)]
    candidates.append(text)
    if not candidates:
        raise SystemExit("aggregate_dedupe output did not contain publish_payload JSON")

    for candidate in reversed(candidates):
        data = first_publish_payload(candidate)
        if data is not None:
            return data

    raise SystemExit("aggregate_dedupe output did not contain publish_payload JSON")


def first_publish_payload(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and looks_like_publish_payload(data):
            return data
    return None


def looks_like_publish_payload(data: dict[str, Any]) -> bool:
    required = ("blocking_count", "non_blocking_count", "check_conclusion", "findings")
    if all(key in data for key in required):
        return True
    return isinstance(data.get("publish_payload"), dict)


def validate_publish_payload(payload: dict[str, Any]) -> str | None:
    if isinstance(payload.get("publish_payload"), dict):
        return "invalid_publish_payload_wrapped"

    required = ("blocking_count", "non_blocking_count", "check_conclusion", "findings")
    missing = [key for key in required if key not in payload]
    if missing:
        return f"invalid_publish_payload_missing_{'_'.join(missing)}"

    if not isinstance(payload.get("findings"), list):
        return "invalid_publish_payload_findings_not_list"

    return None


def count_blocking_findings(payload: dict[str, Any]) -> int:
    explicit = payload.get("blocking_count")
    if isinstance(explicit, int):
        return explicit
    if isinstance(explicit, str) and explicit.isdigit():
        return int(explicit)

    findings = payload.get("findings")
    if not isinstance(findings, list):
        findings = payload.get("comments")
    if not isinstance(findings, list):
        return 0

    count = 0
    for finding in findings:
        if isinstance(finding, dict) and finding.get("blocking") is True:
            count += 1
    return count


if __name__ == "__main__":
    sys.exit(main())
