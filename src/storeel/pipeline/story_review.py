"""A second look at a new part's storyboard: does every picture show what the words say?

The format checks (story.validate) see the shape of a script, not its sense. After a script
passes them, a text model reads the chapter next to the storyboard (who is on screen in each
beat, what is shown, when the picture switches) and lists the mismatches a viewer would notice:
the quoted character not on screen, a reveal shown before it is said, a portrait that
contradicts the moment (a dead character standing), an outfit that does not fit. They are sent
back to the script writer for one rewrite.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from ..jobs import JobContext
from ..meta import MetaAPIError
from ..meta.schema import OutputError, parse_output, text_format
from ..models import Bible, Novel
from ..prompts import load_prompt

MAX_OUTPUT = 16000


class MismatchOut(BaseModel):
    beat: int = Field(0, description="the beat's number, 0 when it is not about one beat")
    problem: str = Field("", description="what is wrong")
    fix: str = Field("", description="what to change in the script")


class ReviewOut(BaseModel):
    problems: list[MismatchOut] = Field(
        default_factory=list, description="empty when the storyboard is right"
    )


def enabled(ctx: JobContext) -> bool:
    return ctx.settings.story_review_effort != "off"


def storyboard(out, bible: Bible) -> dict:
    """The script as the reviewer needs it: who everyone is and looks like, and each beat."""
    looks = {x.id: x.outfit for x in out.looks}
    cast: dict[str, dict] = {}
    for c in bible.characters.values():
        last = sorted(c.looks, key=lambda x: x.chapter)
        outfit = looks.get(c.id) or (last[-1].outfit if last else "")
        cast[c.id] = {"name": c.name, "role": c.role, "who": c.description, "wears": outfit}
    for c in out.characters:
        cast[c.id] = {"name": c.name, "role": c.role, "who": c.description, "wears": c.outfit}
    for v in out.variants:
        base = cast.get(v.base, {})
        cast[v.id] = {"name": base.get("name", v.base), "variant_of": v.base, "change": v.change}

    def show(s) -> dict:
        data = {
            "characters": s.characters,
            "prop": s.prop,
            "photo": s.photo,
            "chat": [m.model_dump() for m in s.chat],
            "note": s.note.text,
            "tag": s.tag,
        }
        return {k: v for k, v in data.items() if v}

    beats = []
    for i, b in enumerate(out.beats, 1):
        beat = {"beat": i, "text": b.text, "speaker": b.speaker, "see": b.see, "show": show(b.show)}
        if b.then.at:
            beat["then"] = {"at": b.then.at, "show": show(b.then.show)}
        beats.append(beat)
    return {
        "characters": cast,
        "props": {
            p.id: {"description": p.description, "refs": p.refs, "people": p.people, "framing": p.framing}
            for p in out.props
        },
        "bible_props": {p.id: p.description for p in bible.props.values()},
        "photos": {p.id: p.description for p in out.photos},
        "beats": beats,
    }


def review_story(ctx: JobContext, novel: Novel, number: int, out, bible: Bible) -> list[str]:
    """The storyboard's mismatches, as notes for the script writer ("beat 3: ... -> ..."); none
    when the review could not be made (it never stops a part)."""
    chapter = novel.chapter(number)
    if chapter is None:
        return []
    model = ctx.settings.check_model
    text = f"CHAPTER {number}:\n<<<\n{chapter.text.strip()}\n>>>\n\nSTORYBOARD:\n" + json.dumps(
        storyboard(out, bible), ensure_ascii=False, indent=1
    )
    try:
        result = ctx.client.responses(
            {
                "model": model,
                "store": False,
                "instructions": load_prompt("story_review"),
                "input": [
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
                ],
                "reasoning": {"effort": ctx.settings.story_review_effort},
                "max_output_tokens": min(MAX_OUTPUT, ctx.settings.max_output_tokens),
                "text": text_format("story_review", ReviewOut),
            },
            cancel=ctx.cancelled,
        )
    except MetaAPIError as exc:
        if exc.usage:
            ctx.spend_text(model, exc.usage)
        ctx.log(f"storyboard review skipped: {exc}")
        return []
    ctx.spend_text(model, result.usage)
    try:
        review, _ = parse_output(ReviewOut, result.text)
    except (OutputError, ValidationError) as exc:
        ctx.log(f"storyboard review skipped: the answer could not be read ({exc.__class__.__name__})")
        return []
    notes = []
    for p in review.problems:
        problem = " ".join(p.problem.split())
        if not problem:
            continue
        where = f"beat {p.beat}" if 1 <= p.beat <= len(out.beats) else "the part"
        fix = " ".join(p.fix.split())
        notes.append(f"{where}: {problem}" + (f" -> {fix}" if fix else ""))
    ctx.log(f"storyboard review: {len(notes)} mismatch(es)" + "".join(f"\n  - {x}" for x in notes))
    return notes[:20]
