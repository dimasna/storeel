"""Time-to-live cleanup: the hosted studio keeps nothing for long.

Renders, uploads and every other asset live only on ephemeral working storage, so a project
(and the novel that owns a set of chapter reels) is deleted once it has been untouched for
`ttl_hours`. The user is expected to download their reel within that window. The web app runs
the sweep on a thread (see Cleaner) when STOREEL_TTL_HOURS is set; it skips anything that still
has a job queued or running, and the showcase.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from datetime import UTC, datetime, timedelta

from .db import NotFound
from .services import Services

log = logging.getLogger(__name__)
DEFAULT_TTL_HOURS = 24


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def purge_expired(
    services: Services, ttl_hours: float = DEFAULT_TTL_HOURS, keep: frozenset[str] = frozenset()
) -> dict[str, int]:
    """Delete projects and novels untouched for `ttl_hours`, with their media.

    Returns a count of what was removed. A project with an active (queued or running) job is
    left alone so a reel is never deleted out from under the job making it. `keep` holds the
    ids of reels and novels never to delete (the showcase); a kept novel keeps its chapters' reels.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    db = services.db
    projects = novels = 0

    for project in db.list_projects():
        if project.id in keep or (project.novel_id and project.novel_id in keep):
            continue
        updated = _parse(project.updated_at)
        if updated is None or updated >= cutoff:
            continue
        job = db.latest_job(project.id)
        if job is not None and job.active:
            continue
        try:
            db.delete_project(project.id)
            services.files(project.id).remove_all()
            projects += 1
        except NotFound:
            pass
        except Exception:  # one bad project must not stop the sweep
            log.exception("purge: failed to delete project %s", project.id)

    # The reels left now were touched within the window or are busy; a novel stays while any of
    # its chapters' reels does, so working on a part keeps the whole novel.
    alive = {p.id for p in db.list_projects()}
    for novel in db.list_novels():
        if novel.id in keep:
            continue
        updated = _parse(novel.updated_at)
        if updated is None or updated >= cutoff:
            continue
        reels = [c.project_id for c in novel.chapters if c.project_id]
        if any(pid in keep or pid in alive for pid in reels):
            continue
        try:
            for pid in reels:
                with contextlib.suppress(NotFound):
                    db.delete_project(pid)
                services.files(pid).remove_all()
            db.delete_novel(novel.id)
            services.novel_files(novel.id).remove_all()
            novels += 1
        except Exception:
            log.exception("purge: failed to delete novel %s", novel.id)

    if projects or novels:
        log.info("purge: removed %d project(s) and %d novel(s) older than %gh", projects, novels, ttl_hours)
    return {"projects": projects, "novels": novels}


class Cleaner:
    """Runs the purge every `every` seconds on a thread of the web process.

    The purge must run in the one process that writes the database: on a Modal Volume a
    second container committing its copy of the SQLite file would replace the web container's
    (last write wins), losing whatever was saved in between.
    """

    def __init__(self, services: Services, ttl_hours: float, keep: frozenset[str], every: float = 900):
        self.services, self.ttl_hours, self.keep, self.every = services, ttl_hours, keep, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="storeel-cleaner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        delay = 60.0  # the first sweep waits for the app to finish starting
        while not self._stop.wait(delay):
            delay = self.every
            try:
                purge_expired(self.services, self.ttl_hours, self.keep)
            except Exception:  # a failed sweep is retried on the next one
                log.exception("purge: the sweep failed")
