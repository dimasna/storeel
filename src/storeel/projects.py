"""Project operations shared by the web app and the CLI: create, import clips, describe."""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO

from .common import now_iso
from .db import Job
from .estimate import estimate_part
from .jobs import PipelineError
from .media import ffmpeg as ff
from .models import DEFAULT_TITLE, Clip, Project, Style
from .pipeline.heard import caption_review, heard_report
from .pipeline.story import hook_opening
from .pipeline.story_compose import calm, timeline
from .services import Services

log = logging.getLogger(__name__)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"})
ACTIVE_STAGE = {
    "script": "scripting",
    "story": "scripting",
    "process": "processing",
    "regenerate": "regenerating",
    "render": "rendering",
    "agent": "editing",
    "agent_apply": "regenerating",
}


def create_project(
    services: Services,
    path: str,
    title: str = DEFAULT_TITLE,
    style: Style | None = None,
    owner: str | None = None,
) -> Project:
    stamp = now_iso()
    project = Project(
        id=uuid.uuid4().hex,
        title=" ".join(title.split())[:120] or DEFAULT_TITLE,
        path=path,
        created_at=stamp,
        updated_at=stamp,
        style=style or Style(),
        owner=owner,
    )
    services.db.create_project(project)
    return project


def display_name(filename: str | None) -> str:
    name = Path(filename or "video").name
    return re.sub(r"[\x00-\x1f]", "", name)[:120] or "video"


def import_clip(
    services: Services,
    project: Project,
    source: BinaryIO | Path,
    filename: str | None,
    *,
    replacing: Clip | None = None,
) -> Clip:
    """Store an uploaded or recorded video in the project and check it can be used.

    The clip is returned, not attached: the caller adds it to the project in its own update.
    `replacing` is a clip that will be removed, so its length does not count twice.
    """
    suffix = Path(filename or "").suffix.lower() or ".mp4"
    if suffix not in VIDEO_SUFFIXES:
        raise PipelineError(f"unsupported file type {suffix!r}; use MP4, MOV or WebM")
    settings = services.settings
    files = services.files(project.id)
    clip_id = uuid.uuid4().hex[:12]
    key = f"uploads/{clip_id}{suffix}"
    path = files.prepare(key)
    tmp = path.with_name(f".{path.name}.tmp")
    limit = settings.max_upload_mb * 1_000_000
    try:
        if isinstance(source, Path):
            if source.stat().st_size > limit:
                raise PipelineError(f"the file is larger than {settings.max_upload_mb} MB")
            shutil.copyfile(source, tmp)
        else:
            written = 0
            with tmp.open("wb") as out:
                while chunk := source.read(1 << 20):
                    written += len(chunk)
                    if written > limit:
                        raise PipelineError(f"the file is larger than {settings.max_upload_mb} MB")
                    out.write(chunk)
        try:
            info = ff.probe(tmp)
        except ff.FFmpegError as exc:
            log.info("rejected upload %r: %s", filename, exc)
            raise PipelineError("this file can't be used: it is not a video ffmpeg can read") from exc
        if info.duration < 0.5:
            raise PipelineError("the video is too short")
        used = sum(c.duration for c in project.inputs() if replacing is None or c.id != replacing.id)
        if used + info.duration > settings.max_input_seconds + 1:
            total, limit_s = used + info.duration, settings.max_input_seconds
            raise PipelineError(f"the reel would be {total:.0f}s long; the limit is {limit_s}s")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return Clip(
        id=clip_id,
        name=display_name(filename),
        key=key,
        duration=round(info.duration, 3),
        width=info.width,
        height=info.height,
        fps=round(info.fps, 3),
        has_audio=info.has_audio,
        hdr=info.hdr,
        size=path.stat().st_size,
    )


def stage(project: Project, job: Job | None) -> str:
    """Where the project is in the flow, derived from its data (never stored)."""
    if job is not None and job.active:
        return ACTIVE_STAGE.get(job.kind, "working")
    if project.path == "novel":
        if project.story is None:
            return "story"
        if not project.clips and (
            project.script is None or any(scene.take is None for scene in project.script.scenes)
        ):
            return "record"
    elif project.path == "idea":
        if project.script is None:
            return "idea"
        if any(scene.take is None for scene in project.script.scenes):
            return "record"
    elif not project.clips:
        return "upload"
    if project.analysis is None:
        return "ready"
    return "done" if project.renders else "review"


def view(services: Services, project: Project) -> dict[str, Any]:
    """The project as the web UI sees it."""
    job = services.db.latest_job(project.id)
    data = project.model_dump(mode="json")
    data.pop("owner", None)  # the browser's id is the server's business
    data["read_only"] = is_showcase(services, project)
    data["stage"] = stage(project, job)
    data["job"] = job.view() if job else None
    data["usage"]["estimated_usd"] = project.usage.estimated_usd
    data["input_seconds"] = round(sum(c.duration for c in project.inputs()), 2)
    # how the recording compares with the script, for the warnings and the caption review
    data["heard"] = heard_report(project)
    data["caption_notes"] = {str(turn): asdict(note) for turn, note in caption_review(project).items()}
    if project.path == "novel" and project.novel_id:
        data["novel"] = _novel_part(services, project)
        data["screens"] = part_screens(project)
    return data


def part_screens(project: Project) -> list[dict[str, Any]]:
    """What a novel part's reel shows when: the hook, each beat's screens (as the render cuts
    them), the poll and the call to action, on the reel's timeline. Empty until it is processed."""
    story = project.story
    if story is None or project.source is None or project.transcript is None:
        return []
    number = {id(beat): n for n, beat in enumerate(story.beats, 1)}
    try:
        lines = calm(timeline(project))
    except Exception:  # a half-rewritten part must not break its page: the timeline waits
        log.exception("part %s: no timeline", project.id)
        return []
    out = []
    for line in lines:
        show = line.show
        item: dict[str, Any] = {"kind": line.kind, "start": round(line.start, 2), "end": round(line.end, 2)}
        if line.beat is not None:
            item["beat"] = number.get(id(line.beat))
        if show is not None:
            item.update(characters=list(show.characters), prop=show.prop, photo=show.photo, tag=show.tag)
        out.append(item)
    return out


def _novel_part(services: Services, project: Project) -> dict[str, Any] | None:
    """What a chapter reel's page needs from its novel."""
    try:
        novel = services.db.get_novel(project.novel_id or "")
    except LookupError:
        return None
    number = project.chapter or 1
    chapter = novel.chapter(number)
    return {
        "id": novel.id,
        "title": novel.title,
        "language": novel.language,
        "narration": novel.narration,
        "visual_style": novel.visual_style,
        "chapter_title": chapter.title if chapter else "",
        "chapter_text": chapter.text if chapter else "",
        "opening": hook_opening(novel, number, any(c.number < number for c in novel.chapters)),
        "estimate": estimate_part(len(chapter.text) if chapter else 0),
    }


def summary(services: Services, project: Project) -> dict[str, Any]:
    job = services.db.latest_job(project.id)
    cover = None
    if project.analysis:
        cover = next((m.asset.key for m in project.analysis.moments if m.asset), None)
    return {
        "id": project.id,
        "title": project.title,
        "path": project.path,
        "stage": stage(project, job),
        "updated_at": project.updated_at,
        "input_seconds": round(sum(c.duration for c in project.inputs()), 1),
        "renders": len(project.renders),
        "cover": cover,
        "read_only": is_showcase(services, project),
    }


def is_showcase(services: Services, project: Project) -> bool:
    """A reel everyone may watch and nobody may change: listed, or its novel listed."""
    showcase = services.settings.showcase
    return project.id in showcase or bool(project.novel_id and project.novel_id in showcase)
