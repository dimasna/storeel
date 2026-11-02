"""Time-to-live cleanup: the hosted studio keeps nothing for long.

Renders, uploads and every other asset live only on ephemeral working storage, so a project
(and the novel that owns a set of chapter reels) is deleted once it has been untouched for
`ttl_hours`. The user is expected to download their reel within that window. A scheduled task
calls `purge_expired` (see modal_app.py); it is safe to run at any time and skips anything
that still has a job queued or running.
"""

from __future__ import annotations

import contextlib
import logging
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


def purge_expired(services: Services, ttl_hours: float = DEFAULT_TTL_HOURS) -> dict[str, int]:
    """Delete projects and novels untouched for `ttl_hours`, with their media.

    Returns a count of what was removed. A project with an active (queued or running) job is
    left alone so a reel is never deleted out from under the job making it.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    db = services.db
    projects = novels = 0

    for project in db.list_projects():
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

    for novel in db.list_novels():
        updated = _parse(novel.updated_at)
        if updated is None or updated >= cutoff:
            continue
        reels = [c.project_id for c in novel.chapters if c.project_id]
        if any((j := db.latest_job(pid)) is not None and j.active for pid in reels):
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
