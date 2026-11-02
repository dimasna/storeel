"""Novel operations shared by the web app: create a novel, add chapters, open a chapter's reel."""

from __future__ import annotations

import uuid
from typing import Any

from .common import now_iso
from .jobs import PipelineError
from .models import Chapter, Novel, Project, Style
from .projects import summary
from .services import Services

MIN_CHAPTER_CHARS = 200


def create_novel(services: Services, **fields: Any) -> Novel:
    stamp = now_iso()
    novel = Novel(id=uuid.uuid4().hex, created_at=stamp, updated_at=stamp, **fields)
    services.db.create_novel(novel)
    return novel


def add_chapter(
    services: Services, novel_id: str, text: str, title: str = "", number: int | None = None
) -> Novel:
    text = text.strip()
    if len(text) < MIN_CHAPTER_CHARS:
        raise PipelineError("paste the whole chapter text (at least a few paragraphs)")

    def add(novel: Novel) -> None:
        existing = {c.number for c in novel.chapters}
        n = int(number) if number else (max(existing) + 1 if existing else 1)
        if n in existing:
            raise PipelineError(f"chapter {n} already exists")
        novel.chapters.append(
            Chapter(number=n, title=" ".join(title.split())[:160], text=text, created_at=now_iso())
        )
        novel.chapters.sort(key=lambda c: c.number)

    novel, _ = services.db.update_novel(novel_id, add)
    return novel


def chapter_style(novel: Novel) -> Style:
    """A chapter reel's starting style: the novel's look and watermark; the speaker sharp, and
    blurred only while a picture is up top (a place, a photo, a scene or an object)."""
    return Style(
        visual_style=novel.visual_style,
        watermark=novel.watermark,
        language=novel.language,
        picture_layout="cards",
        speaker_behind="top",
    )


def open_chapter(services: Services, novel_id: str, number: int) -> Project:
    """The chapter's reel, created on first use."""
    novel = services.db.get_novel(novel_id)
    chapter = novel.chapter(number)
    if chapter is None:
        raise PipelineError(f"the novel has no chapter {number}")
    if chapter.project_id:
        try:
            return services.db.get_project(chapter.project_id)
        except LookupError:
            pass  # deleted: make a new one
    stamp = now_iso()
    label = f": {chapter.title}" if chapter.title else ""
    project = Project(
        id=uuid.uuid4().hex,
        title=f"{novel.title} - Part {number}{label}"[:120],
        path="novel",
        created_at=stamp,
        updated_at=stamp,
        style=chapter_style(novel),
        novel_id=novel.id,
        chapter=number,
        owner=novel.owner,  # a chapter's reel belongs to whoever owns the novel
    )
    services.db.create_project(project)

    def link(n: Novel) -> None:
        found = n.chapter(number)
        if found is not None:
            found.project_id = project.id

    services.db.update_novel(novel_id, link)
    return project


def novel_view(services: Services, novel: Novel) -> dict[str, Any]:
    data = novel.model_dump(mode="json")
    data.pop("owner", None)  # the browser's id is the server's business
    data["read_only"] = novel.id in services.settings.showcase
    chapters = []
    for chapter in novel.chapters:
        row = {
            "number": chapter.number,
            "title": chapter.title,
            "chars": len(chapter.text),
            "project_id": chapter.project_id,
            "stage": None,
            "renders": 0,
        }
        if chapter.project_id:
            try:
                project = services.db.get_project(chapter.project_id)
            except LookupError:
                row["project_id"] = None
            else:
                info = summary(services, project)
                row.update(stage=info["stage"], renders=info["renders"])
                if project.story is not None:
                    row["title"] = row["title"] or project.story.chapter_title
        chapters.append(row)
    data["chapters"] = chapters
    data["next_chapter"] = max((c.number for c in novel.chapters), default=0) + 1
    return data


def novel_summary(services: Services, novel: Novel) -> dict[str, Any]:
    return {
        "id": novel.id,
        "title": novel.title,
        "language": novel.language,
        "chapters": len(novel.chapters),
        "characters": len(novel.bible.characters),
        "updated_at": novel.updated_at,
        "read_only": novel.id in services.settings.showcase,
    }
