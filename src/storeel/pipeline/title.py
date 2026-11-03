"""The reel's title over its first seconds: what it says and when it is up.

For a novel part it is the novel's title, over the hook (the storyteller on camera); for a reel
from a video or an idea it is the reel's title, over its first words. The words can be changed
in the style (title_text). The masks that put it behind the speaker are made for this window
(see depth.py), so the two are worked out here, once.
"""

from __future__ import annotations

from ..models import DEFAULT_TITLE, Project

TITLE_LEAD = 0.3  # seconds into the reel before the title comes in
TITLE_SECONDS = 3.0  # how long it stays at most
TITLE_MIN = 1.2  # a hook shorter than this (plus the lead) gets no title
HOOK_TAKE = "t1"


def title_words(project: Project) -> str:
    """The title's words: the style's, or the novel's title, or the reel's own title."""
    words = " ".join(project.style.title_text.split())
    if words:
        return words
    if project.path == "novel":
        return project.title.split(" - Part")[0].strip()
    title = project.analysis.title.strip() if project.analysis else ""
    if not title or title == DEFAULT_TITLE:
        title = project.title.strip()
    return "" if title == DEFAULT_TITLE else title


def title_window(project: Project) -> tuple[float, float] | None:
    """When the title is up, in seconds on the reel's timeline, or None for no title: it starts
    just after the reel does and leaves before the hook ends (a novel part's first take)."""
    source = project.source
    if source is None or project.style.title_style == "off" or not title_words(project):
        return None
    hook_end = source.duration
    for segment in source.segments:
        if segment.scene_id == HOOK_TAKE:
            hook_end = segment.end
            break
    start = TITLE_LEAD
    end = min(start + TITLE_SECONDS, hook_end - 0.2, source.duration)
    if end - start < TITLE_MIN:
        return None
    return round(start, 3), round(end, 3)
