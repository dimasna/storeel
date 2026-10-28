"""Path C: the pictures a novel part shows, and the character bible they keep consistent.

A chapter's new characters and recurring props
go into the novel's bible, each returning character gets this chapter's outfit, and the notes
the script gives are kept for later chapters. Re-processing a chapter replaces only what that
chapter added. Pictures are content-addressed, so an unchanged one is never drawn twice.

Characters are drawn full body on a plain background and cut out by SAM, then stand at the
bottom of the frame; returning characters are redrawn from their earlier portrait in this
chapter's outfit, so the face stays the same. Objects are cut out too; scenes, places and
photos are shown as framed cards. Muse Image returns opaque pictures, so every cut-out is SAM's.
"""

from __future__ import annotations

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PIL import Image

from ..common import digest
from ..files import ProjectFiles
from ..jobs import JobContext, PipelineError
from ..meta import MetaAPIError
from ..models import (
    Bible,
    BibleCharacter,
    BibleLook,
    BibleNote,
    BibleProp,
    Novel,
    PartPicture,
    Project,
    Region,
    Story,
)
from .assets import LANDSCAPE, NO_TEXT, PORTRAIT, SQUARE, STYLES, Request, generate
from .detect import _frame, _segment, cut_out
from .story_compose import take_spans

VERSION = 1
FACE_CONFIDENCE = 0.3
SHAPE_SIZE = {"wide": LANDSCAPE, "tall": PORTRAIT, "square": SQUARE}
PLAIN = "plain flat light grey background with nothing else in the picture"


# ---- the bible --------------------------------------------------------------------------------


def people_shown(story: Story) -> set[str]:
    """Every character or variant id the part draws: standing in a beat or in a scene's refs."""
    ids: set[str] = set()
    for beat in story.beats:
        ids.update(beat.show.characters)
        if beat.switch:
            ids.update(beat.switch.show.characters)
    for prop in story.props:
        ids.update(prop.refs)
    return ids


def update_bible(bible: Bible, story: Story) -> Bible:
    """The novel's bible with this part's additions in it (and an earlier run's replaced).
    Images already drawn for this chapter's looks are kept when the outfit is unchanged."""
    n = story.part
    kept_looks = {
        (cid, look.outfit): look.image
        for cid, c in bible.characters.items()
        for look in c.looks
        if look.chapter == n and look.image
    }
    kept_props = {pid: p.image for pid, p in bible.props.items() if p.created_in == n and p.image}
    out = Bible(
        characters={k: c.model_copy(deep=True) for k, c in bible.characters.items() if c.created_in != n},
        props={k: p.model_copy(deep=True) for k, p in bible.props.items() if p.created_in != n},
    )
    for c in out.characters.values():
        c.notes = [x for x in c.notes if x.chapter != n]
        c.looks = [x for x in c.looks if x.chapter != n]
    for c in story.characters:
        out.characters[c.id] = BibleCharacter(
            id=c.id,
            name=c.name,
            label=c.label,
            role=c.role,
            description=c.description,
            subject=c.subject,
            slot=c.slot,
            created_in=n,
            looks=[BibleLook(chapter=n, outfit=c.outfit, image=kept_looks.get((c.id, c.outfit)))],
        )
    shown = people_shown(story)
    for look in story.looks:
        c = out.characters.get(look.id)
        if c is not None and c.created_in != n and look.id in shown:
            c.looks.append(
                BibleLook(chapter=n, outfit=look.outfit, image=kept_looks.get((look.id, look.outfit)))
            )
    for prop in story.props:
        if prop.recurring and not prop.refs and prop.id not in out.props:
            out.props[prop.id] = BibleProp(
                id=prop.id,
                description=prop.description,
                subject=prop.subject,
                shape=prop.shape,
                created_in=n,
                image=kept_props.get(prop.id),
            )
    for note in story.bible_notes:
        c = out.characters.get(note.id)
        if c is not None:
            c.notes.append(BibleNote(chapter=n, note=note.note))
    for v in story.variants:
        c = out.characters.get(v.base)
        if c is not None and v.persistent:
            c.notes.append(BibleNote(chapter=n, note=f"look since part {n}: {v.change}"))
    return out


def chapter_look(c: BibleCharacter, n: int) -> BibleLook | None:
    """What the character wears in chapter `n`: its look for that chapter, else its latest before."""
    looks = sorted(c.looks, key=lambda x: x.chapter)
    current = [x for x in looks if x.chapter == n]
    earlier = [x for x in looks if x.chapter < n]
    return current[-1] if current else (earlier[-1] if earlier else None)


def base_portrait(c: BibleCharacter, before: int) -> str | None:
    """The character's earliest drawn portrait from before chapter `before` (their face)."""
    for look in sorted(c.looks, key=lambda x: x.chapter):
        if look.image and look.chapter < before:
            return look.image
    return None


# ---- drawing ----------------------------------------------------------------------------------


@dataclass
class Job:
    """One picture to draw (or reuse): what it is, where it goes, how it is shown."""

    id: str
    kind: str
    display: str
    scope: str
    key: str
    request: Request
    subject: str = ""  # cut out when set
    refs: list[str] = field(default_factory=list)  # ids of pictures this one is drawn from


def _ref_part(path) -> dict:
    """A reference image for Muse Image: a cut-out flattened onto the plain grey it was drawn on."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    plate = Image.new("RGBA", rgba.size, (238, 238, 238, 255))
    plate.alpha_composite(rgba)
    rgb = plate.convert("RGB")
    rgb.thumbnail((1024, 1024), Image.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=90)
    return {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
    }


def _text(text: str) -> dict:
    return {"type": "input_text", "text": text}


class Painter:
    """Draws a part's pictures into the novel's files (bible) or the reel's (this part only)."""

    def __init__(self, ctx: JobContext, novel: Novel, project_files: ProjectFiles, novel_files: ProjectFiles):
        self.ctx = ctx
        self.style = STYLES[novel.visual_style]
        self.model = ctx.settings.image_model
        self.files = {"project": project_files, "novel": novel_files}

    def key(self, scope: str, name: str, *parts: object) -> str:
        folder = "bible" if scope == "novel" else "part"
        return f"{folder}/{name}-{digest(VERSION, self.model, *parts)}.png"

    def path(self, scope: str, key: str):
        return self.files[scope].path(key)

    def exists(self, scope: str, key: str | None) -> bool:
        return bool(key) and self.files[scope].exists(key)

    def draw(self, job: Job) -> PartPicture:
        files = self.files[job.scope]
        prompt = " ".join(p["text"] for p in job.request.content if p["type"] == "input_text")
        picture = PartPicture(
            id=job.id, kind=job.kind, display=job.display, scope=job.scope, key=job.key, prompt=prompt
        )
        if files.exists(job.key):
            with Image.open(files.path(job.key)) as image:
                picture.width, picture.height = image.size
                picture.cutout = image.mode == "RGBA"
            return picture
        try:
            png, width, height, seconds = generate(self.ctx, job.request)
            cut = False
            if job.subject:
                made = cut_out(self.ctx, png, job.subject)
                if made is not None:
                    png, width, height = made
                    cut = True
                else:
                    self.ctx.log(f"SAM could not find {job.subject!r} in {job.id}; it is shown as a card")
            files.write_bytes(job.key, png)
            picture.width, picture.height, picture.cutout = width, height, cut
            shape = f"{width}x{height}" + (" cut out" if cut else "")
            self.ctx.log(f"Muse Image: {job.id} ({job.display}) {shape} in {seconds:.0f}s")
        except MetaAPIError as exc:
            picture.key, picture.error = None, str(exc)
            self.ctx.log(f"Muse Image: {job.id} failed: {exc}")
        return picture


def _portrait_text(name: str, description: str, outfit: str, subject: str, style: str) -> str:
    return (
        f"Full-body character portrait of {name}, a {subject}: {description.rstrip('.')}. Wearing:"
        f" {outfit.rstrip('.')}. One figure alone, standing, facing the viewer, the whole body visible from"
        f" head to feet with space around it, arms relaxed, empty hands, on a {PLAIN}. Style: {style}."
        f" {NO_TEXT}"
    )


def make_part_pictures(ctx: JobContext) -> dict[str, PartPicture]:
    """Update the bible and draw (or reuse) every picture the part shows."""
    project = ctx.project()
    story = project.story
    if story is None or project.novel_id is None:
        raise PipelineError("write the part first")
    db = ctx.services.db
    n = story.part
    novel = db.get_novel(project.novel_id)
    bible = update_bible(novel.bible, story)
    painter = Painter(ctx, novel, ctx.files, ctx.services.novel_files(novel.id))
    style = painter.style
    shown = people_shown(story)
    variants = {v.id: v for v in story.variants}
    used_props = {b.show.prop for b in story.beats} | {b.switch.show.prop for b in story.beats if b.switch}
    used_props |= {p.id for p in story.props if not p.refs}  # the end card shows the key object
    used_photos = {b.show.photo for b in story.beats}
    used_photos |= {b.switch.show.photo for b in story.beats if b.switch}

    first: list[Job] = []  # nothing to wait for
    second: list[Job] = []  # drawn from a picture made in the first round
    characters = {c for c in shown if c in bible.characters} | {
        variants[v].base for v in shown if v in variants
    }
    for cid in sorted(characters):
        c = bible.characters[cid]
        look = chapter_look(c, n)
        outfit = look.outfit if look else ""
        if look and look.image and painter.exists("novel", look.image):
            continue  # drawn already: this chapter's outfit, or the last one when the script kept it
        base = base_portrait(c, n)
        if c.created_in == n or not base or not painter.exists("novel", base):
            text = _portrait_text(c.name, c.description, outfit, c.subject, style)
            request = Request([_text(text)], PORTRAIT, False, [])
            key = painter.key("novel", c.id, text)
        else:
            text = (
                f"The {c.subject} in the reference is {c.name}: {c.description.rstrip('.')}. Draw {c.name}"
                f" again, the same face, hair, body and age, now wearing: {outfit.rstrip('.')}. One figure"
                f" alone, standing, facing the viewer, the whole body visible from head to feet, empty hands,"
                f" on a {PLAIN}."
                f" Style: {style}. {NO_TEXT}"
            )
            request = Request([_ref_part(painter.path("novel", base)), _text(text)], PORTRAIT, False, [cid])
            key = painter.key("novel", c.id, text, base)
        first.append(Job(cid, "character", "standing", "novel", key, request, subject=c.subject))
    for vid in sorted(v for v in shown if v in variants):
        v = variants[vid]
        c = bible.characters.get(v.base)
        if c is None:
            continue
        text = (
            f"The {c.subject} in the reference is {c.name}. Draw {c.name} again, the same person and clothes,"
            f" but: {v.change.rstrip('.')}. One figure alone, the whole body visible, on a {PLAIN}."
            f" Style: {style}. {NO_TEXT}"
        )
        request = Request([_text(text)], PORTRAIT, False, [v.base])
        second.append(
            Job(vid, "variant", "standing", "project", "", request, subject=c.subject, refs=[v.base])
        )
    for prop in story.props:
        if prop.id not in used_props:
            continue
        scope = "novel" if prop.id in bible.props else "project"
        size = SHAPE_SIZE[prop.shape]
        is_object = not (prop.refs or prop.backdrop or prop.framing == "close-up" or prop.people)
        if is_object:
            text = (
                f"{prop.description.rstrip('.')}. The object alone, whole and uncropped, centred with space"
                f" around it, on a {PLAIN}: no hands, no people, no table. Style: {style}. {NO_TEXT}"
            )
            first.append(
                Job(
                    prop.id,
                    "prop",
                    "object",
                    scope,
                    painter.key(scope, prop.id, text),
                    Request([_text(text)], size, False, []),
                    subject=prop.subject or prop.id.replace("_", " "),
                )
            )
        else:
            figures = (
                f" Exactly {prop.people} figure{'s' if prop.people != 1 else ''}." if prop.people else ""
            )
            text = f"Create one new image: {prop.description.rstrip('.')}.{figures} Style: {style}. {NO_TEXT}"
            job = Job(
                prop.id,
                "prop",
                "card",
                scope,
                "",
                Request([_text(text)], size, False, []),
                refs=list(prop.refs),
            )
            (second if prop.refs else first).append(job)
    for prop_id in sorted(used_props - {p.id for p in story.props}):
        bp = bible.props.get(prop_id)  # a bible prop from an earlier chapter, shown again
        if bp and bp.image:
            first.append(Job(prop_id, "prop", "object", "novel", bp.image, Request([], SQUARE, False, [])))
    for photo in story.photos:
        if photo.id in used_photos:
            text = f"{photo.description.rstrip('.')}. Realistic photo. {NO_TEXT}"
            first.append(
                Job(
                    photo.id,
                    "photo",
                    "card",
                    "project",
                    painter.key("project", photo.id, text),
                    Request([_text(text)], LANDSCAPE, False, []),
                )
            )

    ctx.log(f"part {n}: {len(first) + len(second)} pictures to draw or reuse ({len(characters)} characters)")
    pictures: dict[str, PartPicture] = {}
    for cid in characters:  # characters whose portrait for this chapter is already drawn
        look = chapter_look(bible.characters[cid], n)
        if look and look.image and painter.exists("novel", look.image):
            with Image.open(painter.path("novel", look.image)) as image:
                pictures[cid] = PartPicture(
                    id=cid,
                    kind="character",
                    display="standing",
                    scope="novel",
                    key=look.image,
                    cutout=image.mode == "RGBA",
                    width=image.width,
                    height=image.height,
                )
    with ThreadPoolExecutor(ctx.settings.image_parallel) as pool:
        for picture in pool.map(painter.draw, first):
            pictures[picture.id] = picture
    for job in second:  # scenes and variants are drawn from this part's portraits
        content: list[dict] = []
        refs = []
        for number, rid in enumerate(job.refs[:2], 1):
            ref = pictures.get(rid)
            if ref is None or not ref.key:
                continue
            c = bible.characters.get(rid)
            name = c.name if c else rid
            content += [
                _text(f"Reference {number}: {name}. Use it only for how {name} looks."),
                _ref_part(painter.path(ref.scope, ref.key)),
            ]
            refs.append(ref.key)
        job.request = Request([*content, *job.request.content], job.request.size, False, job.refs)
        job.key = painter.key(job.scope, job.id, [p.get("text") for p in job.request.content], refs)
    with ThreadPoolExecutor(ctx.settings.image_parallel) as pool:
        for picture in pool.map(painter.draw, second):
            pictures[picture.id] = picture
    for picture in pictures.values():  # this chapter's new portraits go into its looks
        if picture.kind == "character" and picture.key:
            look = chapter_look(bible.characters[picture.id], n)
            if look is not None and look.chapter == n:
                look.image = picture.key
        if picture.kind == "prop" and picture.scope == "novel" and picture.key and picture.id in bible.props:
            bible.props[picture.id].image = picture.key

    def save_bible(novel_doc: Novel) -> None:
        novel_doc.bible = update_bible(novel_doc.bible, story)
        for cid, c in bible.characters.items():  # carry the drawn images over
            target = novel_doc.bible.characters.get(cid)
            if target is not None:
                target.looks = c.looks
        for pid, p in bible.props.items():
            if pid in novel_doc.bible.props:
                novel_doc.bible.props[pid].image = p.image

    db.update_novel(novel.id, save_bible)
    failed = [p.id for p in pictures.values() if p.error]
    ctx.log(f"pictures: {len(pictures) - len(failed)} ready, {len(failed)} failed")

    def save(p: Project) -> None:
        p.part_pictures = pictures

    ctx.update(save)
    return pictures


# ---- faces, for "blur only when the face is covered" ------------------------------------------


def find_part_faces(ctx: JobContext) -> None:
    """Face boxes in the middle of each take (one SAM call per take), once per recording."""
    project = ctx.project()
    source = project.source
    if source is None:
        return
    wanted = [(take, span) for take, span in take_spans(project).items() if take not in project.part_faces]
    if not wanted:
        return
    found: dict[str, list[Region]] = {}
    for take, (start, end) in wanted:
        ctx.check()
        frame = _frame(ctx, source, (start + end) / 2)
        found[take] = [
            Region(
                x0=d.left / frame.width,
                y0=d.top / frame.height,
                x1=d.right / frame.width,
                y1=d.bottom / frame.height,
            )
            for d in _segment(ctx, frame, "face")
            if d.confidence >= FACE_CONFIDENCE
        ]
    ctx.log(f"SAM: looked for the face in {len(found)} take(s)")
    ctx.update(lambda p: p.part_faces.update(found))
