from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from code_reviewer.archon import ArchonClient, ArchonRun
from code_reviewer.run_store import ReviewRun, RunStore
from code_reviewer.workflow_builder import (
    DEFAULT_HARNESS,
    DEFAULT_MODEL,
    WORKFLOW_FILENAME,
    WORKFLOW_NAME,
    WorkflowConfig,
    render_workflow,
    write_workflow,
)

BRAINTRUST_PROJECT = "My Project"
SENSITIVE_ARG_NAMES = {
    "--api-key",
    "--password",
    "--reason",
    "--secret",
    "--token",
}


def main(argv: Sequence[str] | None = None) -> int:
    configure_braintrust(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def configure_braintrust(argv: Sequence[str] | None = None) -> None:
    if not os.environ.get("BRAINTRUST_API_KEY"):
        return

    try:
        import braintrust

        braintrust.auto_instrument()
        logger = braintrust.init_logger(project=BRAINTRUST_PROJECT)
        logger.log(
            input={"argv": sanitize_argv(list(argv) if argv is not None else sys.argv[1:])},
            metadata={"service": "code-reviewer"},
            tags=["code-reviewer", "cli"],
        )
    except Exception:
        return


def sanitize_argv(argv: Sequence[str]) -> list[str]:
    sanitized = []
    redact_next = False
    for item in argv:
        if redact_next:
            sanitized.append("[redacted]")
            redact_next = False
            continue
        if "=" in item:
            name, _value = item.split("=", 1)
            sanitized.append(f"{name}=[redacted]" if name in SENSITIVE_ARG_NAMES else item)
            continue
        sanitized.append(item)
        redact_next = item in SENSITIVE_ARG_NAMES
    return sanitized


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
    review.add_argument("--pr-url", required=True, help="Pull request URL to review.")
    review.add_argument("--head-sha", help="Exact PR head SHA to review.")
    review.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Review mode requested by the operator.",
    )
    review.add_argument(
        "--harness",
        default=DEFAULT_HARNESS,
        help="Archon provider/harness to render into the workflow.",
    )
    review.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model identifier to render into agent workflow nodes.",
    )
    review.add_argument(
        "--archon-bin",
        default="archon",
        help="Archon executable to invoke.",
    )
    review.add_argument(
        "--no-install",
        action="store_true",
        help="Do not write the generated workflow before running.",
    )
    review.add_argument("--db-path", help=argparse.SUPPRESS)
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
        help="Explain where generated workflows are written.",
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

    payload = build_review_payload(
        repo=repo,
        pr_url=args.pr_url,
        head_sha=args.head_sha,
        mode=args.mode,
        dry_run=args.dry_run,
    )

    repository = payload.get("repository")
    pr_number = payload.get("pull_request_number")
    head_sha = payload.get("head_sha")
    if not isinstance(repository, str) or not isinstance(pr_number, int):
        raise SystemExit("Need a GitHub pull request URL with repository and PR number")
    if not isinstance(head_sha, str):
        raise SystemExit("Need a resolved PR head SHA")

    run_id = uuid4().hex
    workflow_name = f"{WORKFLOW_NAME}-{run_id[:8]}"
    workflow_path = repo / ".archon" / "workflows" / f"{workflow_name}.yaml"
    workflow_config = WorkflowConfig(
        name=workflow_name,
        harness=args.harness,
        model=args.model,
    )
    workflow_yaml = render_workflow(workflow_config)
    if not args.no_install:
        write_workflow(workflow_path, workflow_config)

    store = RunStore(Path(args.db_path).expanduser().resolve() if args.db_path else None)
    archon = ArchonClient(args.archon_bin)
    cancel_active_runs(
        store=store,
        archon=archon,
        repository=repository,
        pr_number=pr_number,
        replacement_run_id=run_id,
    )
    run = store.create_run(
        run_id=run_id,
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        mode=args.mode,
        harness=args.harness,
        model=args.model,
        repo_path=repo,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
        workflow_yaml=workflow_yaml,
    )

    try:
        result = archon.run_workflow(
            workflow_name=run.workflow_name,
            cwd=repo,
            payload=payload,
        )
    except Exception:
        store.mark_failed(run.id, exit_code=1)
        raise

    store.set_archon_run_id(run.id, result.archon_run_id)
    if result.returncode == 0:
        store.mark_succeeded(run.id, exit_code=result.returncode)
    else:
        store.mark_failed(run.id, exit_code=result.returncode)
    return result.returncode


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
    print(f"Generated workflows are written to .archon/workflows/{WORKFLOW_FILENAME}")
    return 0


def install_workflow(repo: Path, *, force: bool = False) -> Path:
    destination = repo.resolve() / ".archon" / "workflows" / WORKFLOW_FILENAME
    if destination.exists() and not force:
        raise SystemExit(
            f"Workflow already exists: {destination}. Re-run with --force to overwrite."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    write_workflow(destination, WorkflowConfig())
    return destination


def build_review_payload(
    *,
    repo: Path,
    pr_url: str,
    head_sha: str | None,
    mode: str,
    dry_run: bool = False,
) -> dict[str, object]:
    pr = resolve_pr(pr_url) if not head_sha else {}
    head_sha = head_sha or (
        pr.get("headRefOid") if isinstance(pr.get("headRefOid"), str) else None
    )
    if not head_sha:
        raise SystemExit("Need --head-sha or a PR URL that GitHub CLI can resolve")
    parsed_repository, parsed_pr_number = parse_pr_url(pr_url)
    if not parsed_repository or parsed_pr_number is None:
        raise SystemExit(f"Pull request URL is not a GitHub PR URL: {pr_url}")

    return {
        "repo": str(repo),
        "head_sha": head_sha,
        "mode": mode,
        "dry_run": dry_run,
        "pull_request_url": pr_url,
        "pull_request_number": parsed_pr_number,
        "repository": parsed_repository,
    }


def resolve_pr(pr_url: str | None) -> dict[str, object]:
    if not pr_url:
        return {}
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
    return data if isinstance(data, dict) else {}


def parse_pr_url(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    import re

    match = re.search(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", value)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def cancel_active_runs(
    *,
    store: RunStore,
    archon: ArchonClient,
    repository: str,
    pr_number: int,
    replacement_run_id: str,
) -> None:
    for run in store.active_runs_for_pr(repository=repository, pr_number=pr_number):
        store.mark_canceling(run.id)
        archon_run = find_archon_run(archon, run)
        if archon_run is not None:
            archon.abandon_and_verify(archon_run.id, cwd=Path(run.repo_path))
        store.mark_canceled(run.id, superseded_by=replacement_run_id)


def find_archon_run(archon: ArchonClient, run: ReviewRun) -> ArchonRun | None:
    active = archon.active_runs(cwd=Path(run.repo_path))

    for archon_run in active:
        if run.archon_run_id and archon_run.id == run.archon_run_id:
            return archon_run
        if archon_run.workflow_name == run.workflow_name:
            return archon_run
    return None


if __name__ == "__main__":
    sys.exit(main())
