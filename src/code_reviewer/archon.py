from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping, Sequence


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
        for chunk in process.stdout:
            output_parts.append(chunk)
            print(chunk, end="")
        returncode = process.wait()
        output = "".join(output_parts)
        return ArchonResult(
            returncode=returncode,
            output=output,
            archon_run_id=extract_archon_run_id(output),
        )


def extract_run_id(run: Mapping[str, Any]) -> str | None:
    for key in ("id", "runId", "run_id", "workflowRunId", "workflow_run_id"):
        value = run.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def first_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    first: dict[str, Any] | None = None
    for match in re.finditer(r"\{", text):
        try:
            data, _end = decoder.raw_decode(text[match.start() :])
        except JSONDecodeError:
            continue
        if isinstance(data, dict):
            first = first or data
            if "runs" in data:
                return data
    if first is not None:
        return first
    raise RuntimeError("archon output did not contain JSON")


def extract_archon_run_id(output: str) -> str | None:
    for line in output.splitlines():
        if "workflowRunId" not in line:
            continue
        try:
            data = json.loads(line)
        except JSONDecodeError:
            continue
        if isinstance(data, dict):
            value = data.get("workflowRunId")
            if isinstance(value, str) and value:
                return value
    return None
