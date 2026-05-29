from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = ("running", "canceling")


@dataclass(frozen=True)
class ReviewRun:
    id: str
    repository: str
    pr_number: int
    head_sha: str
    mode: str
    harness: str
    model: str
    repo_path: str
    workflow_name: str
    workflow_path: str
    status: str
    archon_run_id: str | None = None
    exit_code: int | None = None


class RunStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists code_review_runs (
                  id text primary key,
                  repository text not null,
                  pr_number integer not null,
                  head_sha text not null,
                  mode text not null,
                  harness text not null,
                  model text not null,
                  repo_path text not null,
                  workflow_name text not null,
                  workflow_path text not null,
                  workflow_yaml text not null,
                  status text not null,
                  archon_run_id text,
                  exit_code integer,
                  created_at text not null default (datetime('now')),
                  started_at text,
                  finished_at text,
                  updated_at text not null default (datetime('now')),
                  superseded_by text references code_review_runs(id)
                )
                """
            )
            connection.execute(
                """
                create index if not exists idx_code_review_runs_pr_active
                on code_review_runs(repository, pr_number, status)
                """
            )

    def active_runs_for_pr(self, *, repository: str, pr_number: int) -> list[ReviewRun]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                select * from code_review_runs
                where repository = ?
                  and pr_number = ?
                  and status in ({placeholders})
                order by created_at asc
                """,
                (repository, pr_number, *ACTIVE_STATUSES),
            ).fetchall()
        return [row_to_run(row) for row in rows]

    def create_run(
        self,
        *,
        run_id: str | None = None,
        repository: str,
        pr_number: int,
        head_sha: str,
        mode: str,
        harness: str,
        model: str,
        repo_path: Path,
        workflow_name: str,
        workflow_path: Path,
        workflow_yaml: str,
    ) -> ReviewRun:
        run_id = run_id or uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                insert into code_review_runs (
                  id,
                  repository,
                  pr_number,
                  head_sha,
                  mode,
                  harness,
                  model,
                  repo_path,
                  workflow_name,
                  workflow_path,
                  workflow_yaml,
                  status,
                  started_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', datetime('now'))
                """,
                (
                    run_id,
                    repository,
                    pr_number,
                    head_sha,
                    mode,
                    harness,
                    model,
                    str(repo_path),
                    workflow_name,
                    str(workflow_path),
                    workflow_yaml,
                ),
            )
        return self.get_run(run_id)

    def mark_canceling(self, run_id: str) -> None:
        self._update_status(run_id, "canceling")

    def mark_canceled(self, run_id: str, *, superseded_by: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update code_review_runs
                set status = 'canceled',
                    superseded_by = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                where id = ?
                """,
                (superseded_by, run_id),
            )

    def mark_succeeded(self, run_id: str, *, exit_code: int) -> None:
        self._finish(run_id, status="succeeded", exit_code=exit_code)

    def mark_failed(self, run_id: str, *, exit_code: int) -> None:
        self._finish(run_id, status="failed", exit_code=exit_code)

    def set_archon_run_id(self, run_id: str, archon_run_id: str | None) -> None:
        if not archon_run_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                update code_review_runs
                set archon_run_id = ?, updated_at = datetime('now')
                where id = ?
                """,
                (archon_run_id, run_id),
            )

    def get_run(self, run_id: str) -> ReviewRun:
        with self._connect() as connection:
            row = connection.execute(
                "select * from code_review_runs where id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row_to_run(row)

    def _update_status(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update code_review_runs
                set status = ?, updated_at = datetime('now')
                where id = ?
                """,
                (status, run_id),
            )

    def _finish(self, run_id: str, *, status: str, exit_code: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update code_review_runs
                set status = ?,
                    exit_code = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                where id = ?
                """,
                (status, exit_code, run_id),
            )


def default_db_path() -> Path:
    return Path.home() / ".code-reviews" / "runs.db"


def row_to_run(row: sqlite3.Row) -> ReviewRun:
    data: dict[str, Any] = dict(row)
    return ReviewRun(
        id=data["id"],
        repository=data["repository"],
        pr_number=int(data["pr_number"]),
        head_sha=data["head_sha"],
        mode=data["mode"],
        harness=data["harness"],
        model=data["model"],
        repo_path=data["repo_path"],
        workflow_name=data["workflow_name"],
        workflow_path=data["workflow_path"],
        status=data["status"],
        archon_run_id=data["archon_run_id"],
        exit_code=data["exit_code"],
    )
