from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Sequence

WORKFLOW_NAME = "ai-code-review"
WORKFLOW_FILENAME = f"{WORKFLOW_NAME}.yaml"
BRAINTRUST_PROJECT = "My Project"


def main(argv: Sequence[str] | None = None) -> int:
    configure_braintrust(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def configure_braintrust(argv: Sequence[str] | None = None) -> None:
    if not os.environ.get("BRAINTRUST_API_KEY"):
        return

    import braintrust

    braintrust.auto_instrument()
    logger = braintrust.init_logger(project=BRAINTRUST_PROJECT)
    logger.log(
        input={"argv": list(argv) if argv is not None else sys.argv[1:]},
        metadata={"service": "code-reviewer"},
        tags=["code-reviewer", "cli"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-review",
        description="Run the Archon-powered AI code review workflow.",
    )
    parser.add_argument("--version", action="version", version="code-review 0.1.0")

    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install-workflow",
        help="Install the bundled Archon workflow into a repository.",
    )
    install.add_argument("--repo", default=".", help="Target repository path.")
    install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing workflow file.",
    )
    install.set_defaults(func=cmd_install_workflow)

    review = subparsers.add_parser("review", help="Run the bundled review workflow.")
    review.add_argument("--repo", default=".", help="Repository to review.")
    review.add_argument("--event-path", help="Path to the GitHub event JSON.")
    review.add_argument("--pr-url", help="Pull request URL for manual runs.")
    review.add_argument("--head-sha", help="Exact PR head SHA to review.")
    review.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Review mode requested by the operator.",
    )
    review.add_argument(
        "--workflow",
        default=WORKFLOW_NAME,
        help="Archon workflow name to run.",
    )
    review.add_argument(
        "--archon-bin",
        default="archon",
        help="Archon executable to invoke.",
    )
    review.add_argument(
        "--no-install",
        action="store_true",
        help="Do not install/update the bundled workflow before running.",
    )
    review.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the review without publishing GitHub comments or checks.",
    )
    review.set_defaults(func=cmd_review)

    control = subparsers.add_parser(
        "control",
        help="Emit reviewer control tokens for PR comments or logs.",
    )
    control_subparsers = control.add_subparsers(dest="control_command", required=True)
    for name in ("pause", "resume", "full", "incremental"):
        command = control_subparsers.add_parser(name)
        command.add_argument("--reason", default="")
        command.set_defaults(func=cmd_control)
    for name in ("ignore", "resolve"):
        command = control_subparsers.add_parser(name)
        command.add_argument("--finding-id", required=True)
        command.add_argument("--reason", default="")
        command.set_defaults(func=cmd_control)

    path = subparsers.add_parser(
        "workflow-path",
        help="Print the bundled workflow resource path.",
    )
    path.set_defaults(func=cmd_workflow_path)

    return parser


def cmd_install_workflow(args: argparse.Namespace) -> int:
    destination = install_workflow(Path(args.repo), force=args.force)
    print(destination)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository does not exist: {repo}")

    if not args.no_install:
        install_workflow(repo, force=True)

    payload = build_review_payload(
        repo=repo,
        event_path=Path(args.event_path).resolve() if args.event_path else None,
        pr_url=args.pr_url,
        head_sha=args.head_sha,
        mode=args.mode,
        dry_run=args.dry_run,
    )

    command = [
        args.archon_bin,
        "workflow",
        "run",
        args.workflow,
        "--cwd",
        str(repo),
        json.dumps(payload, sort_keys=True),
    ]
    env = os.environ.copy()
    env.setdefault("CODE_REVIEW_PYTHON", sys.executable)
    return subprocess.run(command, check=False, env=env).returncode


def cmd_control(args: argparse.Namespace) -> int:
    token = {
        "source": "code-review",
        "command": args.control_command,
    }
    if getattr(args, "finding_id", None):
        token["finding_id"] = args.finding_id
    if args.reason:
        token["reason"] = args.reason
    print(f"<!-- code-review:control {json.dumps(token, sort_keys=True)} -->")
    return 0


def cmd_workflow_path(_: argparse.Namespace) -> int:
    with resources.as_file(workflow_resource()) as path:
        print(path)
    return 0


def install_workflow(repo: Path, *, force: bool = False) -> Path:
    destination = repo.resolve() / ".archon" / "workflows" / WORKFLOW_FILENAME
    if destination.exists() and not force:
        raise SystemExit(
            f"Workflow already exists: {destination}. Re-run with --force to overwrite."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(workflow_resource()) as source:
        shutil.copyfile(source, destination)
    return destination


def workflow_resource() -> resources.abc.Traversable:
    return resources.files("code_reviewer").joinpath("workflows", WORKFLOW_FILENAME)


def build_review_payload(
    *,
    repo: Path,
    event_path: Path | None,
    pr_url: str | None,
    head_sha: str | None,
    mode: str,
    dry_run: bool = False,
) -> dict[str, object]:
    event = read_event(event_path) if event_path else {}
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    pr_url = pr_url or extract_pr_url(pull_request)
    head_sha = head_sha or extract_head_sha(pull_request) or resolve_head_sha(pr_url)
    if not head_sha:
        raise SystemExit("Need --head-sha, a pull_request event payload, or --pr-url")

    return {
        "repo": str(repo),
        "event_path": str(event_path) if event_path else None,
        "event_name": event.get("action") if isinstance(event, dict) else None,
        "head_sha": head_sha,
        "mode": mode,
        "dry_run": dry_run,
        "pull_request_url": pr_url,
        "pull_request_number": pull_request.get("number")
        if isinstance(pull_request, dict)
        else None,
        "repository": event.get("repository", {}).get("full_name")
        if isinstance(event, dict)
        else None,
    }


def read_event(event_path: Path | None) -> dict[str, object]:
    if event_path is None:
        return {}
    try:
        with event_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise SystemExit(f"GitHub event file does not exist: {event_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"GitHub event file is not valid JSON: {event_path}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"GitHub event JSON must be an object: {event_path}")
    return data


def extract_pr_url(pull_request: object) -> str | None:
    if not isinstance(pull_request, dict):
        return None
    url = pull_request.get("html_url")
    return url if isinstance(url, str) else None


def extract_head_sha(pull_request: object) -> str | None:
    if not isinstance(pull_request, dict):
        return None
    head = pull_request.get("head")
    if not isinstance(head, dict):
        return None
    sha = head.get("sha")
    return sha if isinstance(sha, str) else None


def resolve_head_sha(pr_url: str | None) -> str | None:
    if not pr_url:
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "headRefOid"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Could not resolve PR head SHA from {pr_url}: {exc}") from exc

    data = json.loads(result.stdout)
    sha = data.get("headRefOid") if isinstance(data, dict) else None
    return sha if isinstance(sha, str) else None


if __name__ == "__main__":
    sys.exit(main())
