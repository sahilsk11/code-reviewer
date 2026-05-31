from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_reviewer.commands.common import first_json_value


@dataclass(frozen=True)
class ArchonRun:
    id: str
    workflow_name: str | None
    status: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ArchonResult:
    returncode: int
    output: str
    archon_run_id: str | None


class ArchonClient:
    def __init__(self, archon_bin: str = "archon") -> None:
        self.archon_bin = archon_bin

    def active_runs(self, *, cwd: Path) -> list[ArchonRun]:
        completed = subprocess.run(
            [self.archon_bin, "workflow", "status", "--json", "--cwd", str(cwd)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout.strip() or "archon workflow status failed")

        data = first_json_object(completed.stdout)
        runs = data.get("runs") if isinstance(data, dict) else None
        if not isinstance(runs, list):
            return []

        parsed = []
        for item in runs:
            if not isinstance(item, dict):
                continue
            run_id = extract_run_id(item)
            if not run_id:
                continue
            workflow_name = item.get("workflowName") or item.get("workflow_name") or item.get("name")
            status = item.get("status")
            parsed.append(
                ArchonRun(
                    id=str(run_id),
                    workflow_name=str(workflow_name) if workflow_name else None,
                    status=str(status) if status else None,
                    raw=item,
                )
            )
        return parsed

    def abandon_run(self, run_id: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.archon_bin, "workflow", "abandon", run_id],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def abandon_and_verify(
        self,
        run_id: str,
        *,
        cwd: Path,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 1.0,
    ) -> None:
        completed = self.abandon_run(run_id)
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stdout.strip() or f"archon workflow abandon {run_id} failed"
            )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if all(run.id != run_id for run in self.active_runs(cwd=cwd)):
                return
            time.sleep(poll_seconds)

        raise RuntimeError(f"Archon run {run_id} was still active after abandon")

    def run_workflow(
        self,
        *,
        workflow_name: str,
        cwd: Path,
        payload: Mapping[str, object],
        env: Mapping[str, str] | None = None,
    ) -> ArchonResult:
        repository = payload.get("repository")
        if isinstance(repository, str):
            repair_note = repair_workspace_source_symlink(repository=repository, cwd=cwd)
            if repair_note:
                print(repair_note)

        command = [
            self.archon_bin,
            "workflow",
            "run",
            workflow_name,
            "--cwd",
            str(cwd),
            json.dumps(payload, sort_keys=True),
        ]
        merged_env = os.environ.copy()
        merged_env.setdefault("CODE_REVIEW_PYTHON", sys.executable)
        if env:
            merged_env.update(env)

        try:
            process = subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Archon executable not found: {self.archon_bin}") from exc

        output_parts: list[str] = []
        assert process.stdout is not None
        observed_archon_run_id: str | None = None
        started_at = time.monotonic()
        next_heartbeat_at = started_at + 60
        while process.poll() is None:
            ready, _, _ = select.select([process.stdout], [], [], 5)
            if ready:
                chunk = process.stdout.readline()
                if chunk:
                    output_parts.append(chunk)
                    print(chunk, end="")
                    observed_archon_run_id = observed_archon_run_id or extract_archon_run_id(chunk)
                continue

            now = time.monotonic()
            if now >= next_heartbeat_at:
                heartbeat = self.workflow_heartbeat(
                    workflow_name=workflow_name,
                    cwd=cwd,
                    elapsed_seconds=now - started_at,
                )
                if heartbeat:
                    observed_archon_run_id = observed_archon_run_id or heartbeat.id
                next_heartbeat_at = now + 60

        for chunk in process.stdout:
            output_parts.append(chunk)
            print(chunk, end="")
        returncode = process.wait()
        output = "".join(output_parts)
        return ArchonResult(
            returncode=returncode,
            output=output,
            archon_run_id=extract_archon_run_id(output) or observed_archon_run_id,
        )

    def workflow_heartbeat(
        self,
        *,
        workflow_name: str,
        cwd: Path,
        elapsed_seconds: float,
    ) -> ArchonRun | None:
        try:
            runs = self.active_runs(cwd=cwd)
        except Exception as exc:
            print(
                f"Archon workflow still running after {elapsed_seconds:.0f}s; "
                f"status unavailable: {exc}",
                flush=True,
            )
            return None
        matching = next((run for run in runs if run.workflow_name == workflow_name), None)
        if matching is None:
            print(
                f"Archon workflow {workflow_name} still running after {elapsed_seconds:.0f}s; "
                "not present in active run status.",
                flush=True,
            )
            return None

        last_activity = (
            matching.raw.get("last_activity_at")
            or matching.raw.get("lastActivityAt")
            or "unknown"
        )
        print(
            f"Archon workflow {workflow_name} still running after {elapsed_seconds:.0f}s "
            f"(run={matching.id}, status={matching.status or 'unknown'}, "
            f"last_activity={last_activity})",
            flush=True,
        )
        return matching


def repair_workspace_source_symlink(*, repository: str, cwd: Path) -> str | None:
    parts = [part for part in repository.split("/") if part]
    if len(parts) != 2:
        return None
    source_link = Path.home() / ".archon" / "workspaces" / parts[0] / parts[1] / "source"
    if not source_link.is_symlink():
        return None
    current_target = source_link.resolve(strict=False)
    expected_target = cwd.resolve()
    if current_target == expected_target:
        return None

    source_link.unlink()
    source_link.symlink_to(expected_target)
    return (
        "Repaired stale Archon source symlink: "
        f"{source_link} was {current_target}, now {expected_target}"
    )


def extract_run_id(run: Mapping[str, Any]) -> str | None:
    for key in ("id", "runId", "run_id", "workflowRunId", "workflow_run_id"):
        value = run.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def first_json_object(text: str) -> dict[str, Any]:
    first: dict[str, Any] | None = None
    remaining = text
    while True:
        data = first_json_value(remaining)
        if data is None:
            break
        if isinstance(data, dict):
            first = first or data
            if "runs" in data:
                return data
        next_start = remaining.find("{")
        if next_start < 0:
            break
        remaining = remaining[next_start + 1 :]
    if first is not None:
        return first
    raise RuntimeError("archon output did not contain JSON")


def extract_archon_run_id(output: str) -> str | None:
    for line in output.splitlines():
        if "workflowRunId" not in line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            value = data.get("workflowRunId")
            if isinstance(value, str) and value:
                return value
    return None
