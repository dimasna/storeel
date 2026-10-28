"""Background jobs: worker threads take queued jobs from the database and run them.

A job is one long action on one project (write a script, process the clips, regenerate a
picture, render the reel). Handlers get a JobContext for logging, progress, cancellation
and atomic project updates. Model API usage is counted as it happens and added to the
project when the job ends, whether it succeeded or not, so the cost estimate stays honest.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from .common import Cancelled
from .config import ConfigError
from .db import Job
from .files import ProjectFiles
from .media.ffmpeg import FFmpegError
from .meta import MetaAPIError, MetaClient
from .models import Project, Usage, text_usd
from .services import Services

log = logging.getLogger(__name__)
T = TypeVar("T")

Handler = Callable[["JobContext"], None]


class PipelineError(RuntimeError):
    """An expected failure with a message meant for the user."""


class JobContext:
    def __init__(self, services: Services, job: Job) -> None:
        self.services = services
        self.settings = services.settings
        self.job = job
        self.project_id = job.project_id
        self.params = job.params
        self.files: ProjectFiles = services.files(job.project_id)
        self._usage = Usage()
        self._usage_lock = threading.Lock()
        self._cancel_checked = 0.0
        self._cancelled = False
        self._progress_written = 0.0
        self._progress_range = (0.0, 1.0)
        self._client: MetaClient | None = None
        self._client_lock = threading.Lock()

    @property
    def client(self) -> MetaClient:
        """A Model API client with the key of the user who started the job."""
        with self._client_lock:
            if self._client is None:
                key = self.services.keys.get(self.job.id)
                if key is None:
                    raise PipelineError(
                        "this job has no Model API key (the server restarted?):"
                        " add your key and start it again"
                    )
                self._client = self.services.client(key)
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    # ---- feedback ---------------------------------------------------------------------------

    def log(self, message: str) -> None:
        log.info("[%s %s] %s", self.job.kind, self.job.id[:8], message)
        self.services.db.append_log(self.job.id, f"{time.strftime('%H:%M:%S')} {message}\n")

    def step(self, name: str, start: float, end: float) -> None:
        """Start a stage that covers `start`..`end` of the job's progress bar."""
        self._progress_range = (start, end)
        self.services.db.set_progress(self.job.id, step=name, progress=start)
        self.log(f"== {name}")

    def progress(self, fraction: float) -> None:
        """Progress within the current stage (0..1), written at most a few times a second."""
        now = time.monotonic()
        if now - self._progress_written < 0.3 and fraction < 1.0:
            return
        self._progress_written = now
        lo, hi = self._progress_range
        self.services.db.set_progress(self.job.id, progress=lo + (hi - lo) * min(1.0, max(0.0, fraction)))

    # ---- cancellation -----------------------------------------------------------------------

    def cancelled(self) -> bool:
        """Cheap enough to call in tight loops: the database is read at most twice a second."""
        if self._cancelled:
            return True
        now = time.monotonic()
        if now - self._cancel_checked >= 0.5:
            self._cancel_checked = now
            self._cancelled = self.services.db.cancel_requested(self.job.id)
        return self._cancelled

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled

    # ---- project state ----------------------------------------------------------------------

    def project(self) -> Project:
        return self.services.db.get_project(self.project_id)

    def update(self, change: Callable[[Project], T]) -> tuple[Project, T]:
        return self.services.db.update_project(self.project_id, change)

    def spend(self, **amounts: float) -> None:
        """Count Model API usage, e.g. spend(images=1); safe to call from several threads."""
        with self._usage_lock:
            for name, amount in amounts.items():
                setattr(self._usage, name, getattr(self._usage, name) + amount)

    def spend_text(self, model: str, usage: dict) -> None:
        """Count one text-model call from its `usage`, priced by the model that made it."""
        input_tokens = int(usage.get("input_tokens") or 0)
        cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        self.spend(
            spark_input_tokens=input_tokens,
            spark_cached_tokens=cached,
            spark_output_tokens=output_tokens,
            text_usd=text_usd(model, input_tokens, cached, output_tokens),
        )

    def flush_usage(self) -> None:
        with self._usage_lock:
            usage, self._usage = self._usage, Usage()
        if usage != Usage():
            self.update(lambda p: p.usage.add(usage))


ABSOLUTE_PATH = re.compile(r"(?:/[\w.@~+-]+)+/([\w.@~+-]+)")


def describe_error(exc: BaseException) -> str:
    """A one-line message for the user, with file paths shortened to their file names."""
    if isinstance(exc, PipelineError | ConfigError | FFmpegError):
        message = str(exc)
    elif isinstance(exc, MetaAPIError):
        message = f"Model API: {exc}"
    elif isinstance(exc, ValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()))
        message = f"unexpected data ({where}: {first.get('msg', 'invalid')})"
    else:
        message = f"{type(exc).__name__}: {exc}"
    return ABSOLUTE_PATH.sub(r"\1", message)


def execute(services: Services, job: Job, handlers: dict[str, Handler]) -> str:
    """Run one claimed job to completion and record the outcome. Returns its final status."""
    db = services.db
    ctx = JobContext(services, job)
    status, error = "done", None
    try:
        handler = handlers.get(job.kind)
        if handler is None:
            raise PipelineError(f"unknown job kind {job.kind!r}")
        handler(ctx)
    except Cancelled:
        status = "cancelled"
        ctx.log("cancelled")
    except Exception as exc:
        status, error = "failed", describe_error(exc)
        log.exception("job %s (%s) failed", job.id, job.kind)
        ctx.log(f"failed: {error}")
    finally:
        services.keys.drop(job.id)  # the user's key is not kept past their job
        ctx.close()
        try:
            ctx.flush_usage()
        except Exception:
            log.exception("could not record usage for job %s", job.id)
    try:
        ctx.update(lambda p: setattr(p, "error", error if status == "failed" else None))
    except Exception:
        log.exception("could not update project %s after job %s", job.project_id, job.id)
    db.finish(job.id, status, error)
    return status


class Workers:
    def __init__(self, services: Services, handlers: dict[str, Handler], count: int) -> None:
        self.services = services
        self.handlers = handlers
        self.count = count
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        interrupted = self.services.db.fail_interrupted()
        if interrupted:
            log.warning("marked %d interrupted job(s) as failed", interrupted)
        for index in range(self.count):
            thread = threading.Thread(target=self._loop, name=f"storeel-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.services.db.job_added.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def _loop(self) -> None:
        db = self.services.db
        while not self._stop.is_set():
            try:
                job = db.claim()
            except Exception:
                log.exception("could not read the job queue")
                self._stop.wait(2.0)
                continue
            if job is None:
                db.job_added.wait(timeout=1.0)
                db.job_added.clear()
                continue
            execute(self.services, job, self.handlers)
