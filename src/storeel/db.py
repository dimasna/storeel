"""SQLite storage: one JSON document per project, and the background job queue.

Connections are opened per operation (cheap for SQLite) so any thread can use the
database. Read-modify-write updates run in `BEGIN IMMEDIATE` transactions, so the web
handlers and the job workers never overwrite each other's changes to a project.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from .common import now_iso
from .models import Novel, Project

T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    params TEXT NOT NULL DEFAULT '{}',
    log TEXT NOT NULL DEFAULT '',
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs (project_id, created_at);
CREATE TABLE IF NOT EXISTS novels (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MAX_LOG_CHARS = 200_000


class NotFound(LookupError):
    """No project or job with that id."""


class Conflict(RuntimeError):
    """The request clashes with work in progress (e.g. a job is already running)."""


@dataclass(frozen=True)
class Job:
    id: str
    project_id: str
    kind: str
    status: str  # queued | running | done | failed | cancelled
    step: str
    progress: float
    params: dict[str, Any]
    log: str
    error: str | None
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Job:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            kind=row["kind"],
            status=row["status"],
            step=row["step"],
            progress=row["progress"],
            params=json.loads(row["params"] or "{}"),
            log=row["log"],
            error=row["error"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def view(self, log_chars: int = 6000) -> dict[str, Any]:
        """What the web UI shows: everything but the full log."""
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "step": self.step,
            "progress": round(self.progress, 3),
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log": self.log[-log_chars:],
        }


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.job_added = threading.Event()  # wakes idle workers
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # ---- projects ---------------------------------------------------------------------------

    def create_project(self, project: Project) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO projects (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (project.id, project.model_dump_json(), project.created_at, project.updated_at),
            )

    def get_project(self, project_id: str) -> Project:
        with self._connection() as conn:
            row = conn.execute("SELECT data FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise NotFound(f"no project {project_id}")
        return Project.model_validate_json(row["data"])

    def list_projects(self) -> list[Project]:
        with self._connection() as conn:
            rows = conn.execute("SELECT data FROM projects ORDER BY updated_at DESC").fetchall()
        return [Project.model_validate_json(row["data"]) for row in rows]

    def update_project(self, project_id: str, change: Callable[[Project], T]) -> tuple[Project, T]:
        """Apply `change` to the stored project atomically; an exception leaves it untouched."""
        with self._transaction() as conn:
            row = conn.execute("SELECT data FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise NotFound(f"no project {project_id}")
            project = Project.model_validate_json(row["data"])
            result = change(project)
            project.updated_at = now_iso()
            # Re-validate, so a change can never store a document that would not load again.
            project = Project.model_validate(project.model_dump())
            conn.execute(
                "UPDATE projects SET data = ?, updated_at = ? WHERE id = ?",
                (project.model_dump_json(), project.updated_at, project_id),
            )
        return project, result

    def delete_project(self, project_id: str) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # ---- novels -----------------------------------------------------------------------------

    def create_novel(self, novel: Novel) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO novels (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (novel.id, novel.model_dump_json(), novel.created_at, novel.updated_at),
            )

    def get_novel(self, novel_id: str) -> Novel:
        with self._connection() as conn:
            row = conn.execute("SELECT data FROM novels WHERE id = ?", (novel_id,)).fetchone()
        if row is None:
            raise NotFound(f"no novel {novel_id}")
        return Novel.model_validate_json(row["data"])

    def list_novels(self) -> list[Novel]:
        with self._connection() as conn:
            rows = conn.execute("SELECT data FROM novels ORDER BY updated_at DESC").fetchall()
        return [Novel.model_validate_json(row["data"]) for row in rows]

    def update_novel(self, novel_id: str, change: Callable[[Novel], T]) -> tuple[Novel, T]:
        """Apply `change` to the stored novel atomically; an exception leaves it untouched."""
        with self._transaction() as conn:
            row = conn.execute("SELECT data FROM novels WHERE id = ?", (novel_id,)).fetchone()
            if row is None:
                raise NotFound(f"no novel {novel_id}")
            novel = Novel.model_validate_json(row["data"])
            result = change(novel)
            novel.updated_at = now_iso()
            novel = Novel.model_validate(novel.model_dump())
            conn.execute(
                "UPDATE novels SET data = ?, updated_at = ? WHERE id = ?",
                (novel.model_dump_json(), novel.updated_at, novel_id),
            )
        return novel, result

    def delete_novel(self, novel_id: str) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))

    # ---- jobs -------------------------------------------------------------------------------

    def enqueue(
        self, project_id: str, kind: str, params: dict[str, Any] | None = None, *, job_id: str | None = None
    ) -> Job:
        """Queue a job; at most one job per project can be queued or running. Pass `job_id` to
        prepare things the job needs (its API key) before a worker can pick it up."""
        job_id = job_id or uuid.uuid4().hex
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise NotFound(f"no project {project_id}")
            busy = conn.execute(
                "SELECT kind FROM jobs WHERE project_id = ? AND status IN ('queued', 'running')",
                (project_id,),
            ).fetchone()
            if busy is not None:
                raise Conflict(f"this project is busy ({busy['kind']} job in progress)")
            conn.execute(
                "INSERT INTO jobs (id, project_id, kind, status, params, created_at)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, project_id, kind, json.dumps(params or {}), now_iso()),
            )
        self.job_added.set()
        return self.get_job(job_id)

    def claim(self, job_id: str | None = None) -> Job | None:
        """Mark the oldest queued job (or `job_id`) as running and return it."""
        with self._transaction() as conn:
            if job_id is None:
                row = conn.execute(
                    "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM jobs WHERE id = ? AND status = 'queued'", (job_id,)
                ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?", (now_iso(), row["id"])
            )
        return self.get_job(row["id"])

    def get_job(self, job_id: str) -> Job:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise NotFound(f"no job {job_id}")
        return Job.from_row(row)

    def latest_job(self, project_id: str) -> Job | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return Job.from_row(row) if row else None

    def set_progress(self, job_id: str, *, step: str | None = None, progress: float | None = None) -> None:
        with self._connection() as conn:
            if step is not None:
                conn.execute("UPDATE jobs SET step = ? WHERE id = ?", (step, job_id))
            if progress is not None:
                conn.execute(
                    "UPDATE jobs SET progress = ? WHERE id = ?", (min(1.0, max(0.0, progress)), job_id)
                )

    def append_log(self, job_id: str, text: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE jobs SET log = substr(log || ?, -?) WHERE id = ?", (text, MAX_LOG_CHARS, job_id)
            )

    def finish(self, job_id: str, status: str, error: str | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ?,"
                " progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END WHERE id = ?",
                (status, error, now_iso(), status, job_id),
            )

    def cancel(self, job_id: str) -> Job:
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise NotFound(f"no job {job_id}")
            if row["status"] == "queued":
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ?", (now_iso(), job_id)
                )
            elif row["status"] == "running":
                conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
        return self.get_job(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def fail_interrupted(self) -> int:
        """Jobs a previous process left running or queued: mark them failed. Their users' API
        keys were only in that process's memory, and retrying is cheap (each stage reuses
        what it already made), while an automatic restart could repeat a failure."""
        with self._transaction() as conn:
            running = conn.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?,"
                " error = 'interrupted: the server stopped while this job was running; start it again'"
                " WHERE status = 'running'",
                (now_iso(),),
            ).rowcount
            queued = conn.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?,"
                " error = 'the server restarted before this job started; start it again'"
                " WHERE status = 'queued'",
                (now_iso(),),
            ).rowcount
        return running + queued
