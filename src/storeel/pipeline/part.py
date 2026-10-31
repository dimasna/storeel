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
from dataclasses import dataclass, field, replace

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
from . import picture_check
from .assets import LANDSCAPE, NO_TEXT, POLICY_TRIES, PORTRAIT, SQUARE, STYLES, Request, generate_allowed
from .detect import _frame, _segment, cut_out
from .screen import GREEN_AGAIN, GREEN_SCREEN, key_out_green
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
    name: str = ""  # a character's name, for the portrait check
    screen: bool = False  # drawn on a green screen and keyed out (a scene, a close-up)


@dataclass
class Take:
    """One drawing of a picture: the PNG (cut out when SAM found the subject) and its size."""

    png: bytes
    width: int
    height: int
    cutout: bool


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
    """Draws a part's pictures into the novel's files (bible) or the reel's (this part only).
    A character portrait is checked by a text model and drawn again once if it is wrong."""

    def __init__(
        self,
        ctx: JobContext,
        novel: Novel,
        project_files: ProjectFiles,
        novel_files: ProjectFiles,
        earlier: dict[str, PartPicture] | None = None,
    ):
        self.ctx = ctx
        self.style = STYLES[novel.visual_style]
        self.model = ctx.settings.image_model
        self.files = {"project": project_files, "novel": novel_files}
        self.earlier = earlier or {}  # the part's pictures from the last run, with their checks

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
            before = self.earlier.get(job.id)
            if before is not None and before.key == job.key:  # checked when it was drawn
                picture.checked, picture.problems = before.checked, before.problems
            return picture
        try:
            take = self._drawn(job)
            if job.kind in ("character", "variant") and picture_check.enabled(self.ctx):
                take, check = self._checked(job, take)
                if check is not None:
                    picture.checked, picture.problems = True, [] if check.ok else check.problems
            files.write_bytes(job.key, take.png)
            picture.width, picture.height, picture.cutout = take.width, take.height, take.cutout
        except MetaAPIError as exc:
            picture.key, picture.error = None, str(exc)
            if exc.content_policy:
                portraits = job.kind == "prop" and any(
                    p["type"] == "input_image" for p in job.request.content
                )
                picture.error = (
                    f"Muse Image's safety filter refused this picture {POLICY_TRIES} times"
                    + (", also without the portraits" if portraits else "")
                    + ". It often passes on another try: press Update to draw it again."
                )
            self.ctx.log(f"Muse Image: {job.id} failed: {exc}")
        return picture

    def _drawn(self, job: Job) -> Take:
        """The picture, drawn again while the safety filter refuses it. A scene it keeps refusing
        with the characters' portraits is drawn from its words alone: the people may look less
        like their portraits, but the beat has its picture (on the real API, both scenes refused
        with portraits were drawn without them)."""
        try:
            return self._take(job, job.request)
        except MetaAPIError as exc:
            content = job.request.content
            words = [
                p for p in content if p["type"] == "input_text" and not p["text"].startswith("Reference ")
            ]
            if not (exc.content_policy and job.kind == "prop" and len(words) < len(content)):
                raise
            self.ctx.log(f"Muse Image: {job.id} is drawn from its words only, without the portraits")
            return self._take(job, replace(job.request, content=words, references=[]))

    def _take(self, job: Job, request: Request) -> Take:
        png, width, height, seconds = generate_allowed(self.ctx, request, job.id)
        cut = False
        if job.screen:  # drawn on a green screen: keyed out here
            png, width, height, cut = self._keyed(job, request, png, width, height)
        elif job.subject:
            made = cut_out(self.ctx, png, job.subject)
            if made is not None:
                png, width, height = made
                cut = True
            else:
                self.ctx.log(f"SAM could not find {job.subject!r} in {job.id}; it is shown as a card")
        shape = f"{width}x{height}" + (" cut out" if cut else "")
        self.ctx.log(f"Muse Image: {job.id} ({job.display}) {shape} in {seconds:.0f}s")
        return Take(png, width, height, cut)

    def _keyed(
        self, job: Job, request: Request, png: bytes, width: int, height: int
    ) -> tuple[bytes, int, int, bool]:
        """The picture with its green screen keyed out; drawn once more when the screen is not
        there (the model filled the background), and shown as a card when it still is not."""
        for attempt in range(2):
            with Image.open(io.BytesIO(png)) as opened:
                keyed = key_out_green(opened)
            if keyed is not None:
                buffer = io.BytesIO()
                keyed.save(buffer, "PNG", optimize=True)
                return buffer.getvalue(), keyed.width, keyed.height, True
            if attempt:
                break
            self.ctx.log(f"Muse Image: {job.id} has no green screen around it; drawing it again")
            content = [*request.content]
            last = max(i for i, p in enumerate(content) if p["type"] == "input_text")
            content[last] = _text(content[last]["text"] + GREEN_AGAIN)
            try:
                png, width, height, _ = generate_allowed(self.ctx, replace(request, content=content), job.id)
            except MetaAPIError as exc:
                self.ctx.log(f"Muse Image: {job.id} redraw failed: {exc}")
                break
        self.ctx.log(f"Muse Image: {job.id} kept its background; it is shown as a card")
        return png, width, height, False

    def _checked(self, job: Job, take: Take) -> tuple[Take, picture_check.Check | None]:
        """The portrait as checked, drawn again with the checker's fix when it is wrong; the
        better of the two is kept."""
        content = job.request.content
        last = max(i for i, p in enumerate(content) if p["type"] == "input_text")  # the drawing prompt
        text = content[last]["text"]
        references = [p for p in content if p["type"] == "input_image"]
        name = job.name or job.id
        check = picture_check.check_portrait(self.ctx, take.png, text, references, name)
        best = (take, check)
        for _ in range(picture_check.RETAKES):
            if check is None or check.ok:
                break
            self.ctx.log(f"portrait check: {job.id}: {'; '.join(check.problems)}; drawing it again")
            again = [*content[:last], _text(picture_check.retake_text(text, check)), *content[last + 1 :]]
            try:
                retake = self._take(job, replace(job.request, content=again))
            except MetaAPIError as exc:
                self.ctx.log(f"Muse Image: {job.id} redraw failed: {exc}")
                break
            check = picture_check.check_portrait(self.ctx, retake.png, text, references, name)
            if check is None:
                break
            if best[1] is None or check.score < best[1].score:
                best = (retake, check)
        kept = best[1]
        if kept is not None:
            verdict = "ok" if kept.ok else f"still: {'; '.join(kept.problems)} (used anyway)"
            self.ctx.log(f"portrait check: {job.id} {verdict}")
        return best


CALM = "a calm, neutral face, not smiling"  # a standing figure is on screen in sad beats and happy ones


def _portrait_text(name: str, description: str, outfit: str, subject: str, style: str) -> str:
    return (
        f"Full-body character portrait of {name}, a {subject}: {description.rstrip('.')}. Wearing:"
        f" {outfit.rstrip('.')}. One figure alone, standing, facing the viewer, the whole body visible from"
        f" head to feet with space around it, {CALM}, arms relaxed, empty hands, on a {PLAIN}."
        f" Style: {style}. {NO_TEXT}"
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
    painter = Painter(ctx, novel, ctx.files, ctx.services.novel_files(novel.id), project.part_pictures)
    style = painter.style
    shown = people_shown(story)
    variants = {v.id: v for v in story.variants}
    used_props = {b.show.prop for b in story.beats} | {b.switch.show.prop for b in story.beats if b.switch}
    used_props |= {p.id for p in story.props if not p.refs}  # the end card shows the key object
    used_props.discard("")
    used_photos = {b.show.photo for b in story.beats}
    used_photos |= {b.switch.show.photo for b in story.beats if b.switch}
    used_photos.discard("")

    first: list[Job] = []  # nothing to wait for
    second: list[Job] = []  # drawn from a picture made in the first round
    characters = {c for c in shown if c in bible.characters} | {
        variants[v].base for v in shown if v in variants
    }
    for cid in sorted(characters):
        c = bible.characters[cid]
        look = chapter_look(c, n)
        outfit = look.outfit if look else ""
        base = base_portrait(c, n)
        if c.created_in == n or not base or not painter.exists("novel", base):
            text = _portrait_text(c.name, c.description, outfit, c.subject, style)
            request = Request([_text(text)], PORTRAIT, False, [])
            key = painter.key("novel", c.id, text)
        else:
            text = (
                f"The {c.subject} in the reference is {c.name}: {c.description.rstrip('.')}. Draw {c.name}"
                f" again, the same face, hair, body and age, now wearing: {outfit.rstrip('.')}. One figure"
                f" alone, standing, facing the viewer, the whole body visible from head to feet, {CALM},"
                f" empty hands, on a {PLAIN}."
                f" Style: {style}. {NO_TEXT}"
            )
            request = Request([_ref_part(painter.path("novel", base)), _text(text)], PORTRAIT, False, [cid])
            key = painter.key("novel", c.id, text, base)
        if (
            look
            and look.image
            and painter.exists("novel", look.image)
            and (look.chapter != n or look.image == key)
        ):
            # Drawn already: this chapter's look as it would be drawn now, or an earlier chapter's
            # that the script kept. One drawn otherwise (in another look style) is drawn again.
            continue
        first.append(Job(cid, "character", "standing", "novel", key, request, subject=c.subject, name=c.name))
    for vid in sorted(v for v in shown if v in variants):
        v = variants[vid]
        c = bible.characters.get(v.base)
        if c is None:
            continue
        text = (
            f"The {c.subject} in the reference is {c.name}. Keep {c.name}'s face, hair, body and identity"
            " exactly the same, and the clothes unless the change says otherwise. New image:"
            f" {c.name} alone, drawn once, full body, standing upright facing the viewer, now"
            f" {v.change.rstrip('.')}. Whatever the change covers stays hidden (nothing of the old outfit"
            " or shoes shows), and nothing is added that the change does not describe. One figure alone,"
            f" the whole body visible from head to feet, on a {PLAIN}. Style: {style}. {NO_TEXT}"
        )
        request = Request([_text(text)], PORTRAIT, False, [v.base])
        second.append(
            Job(
                vid,
                "variant",
                "standing",
                "project",
                "",
                request,
                subject=c.subject,
                refs=[v.base],
                name=c.name,
            )
        )

    def named(rid: str) -> str:
        """What a scene calls a character or a variant (by the base character's name)."""
        base = variants[rid].base if rid in variants else rid
        c = bible.characters.get(base)
        return c.name if c else rid

    def looks(rid: str) -> str:
        """How a character or a variant looks in this chapter, written out for a picture drawn
        without their portrait."""
        v = variants.get(rid)
        c = bible.characters.get(v.base if v else rid)
        if c is None:
            return ""
        look = chapter_look(c, n)
        wearing = f", wearing {look.outfit.rstrip('.')}" if look and look.outfit else ""
        change = f"; at this moment {v.change.rstrip('.')}" if v else ""
        return f"{c.name} looks like this: {c.description.rstrip('.')}{wearing}{change}."

    for prop in story.props:
        if prop.id not in used_props:
            continue
        scope = "novel" if prop.id in bible.props else "project"
        size = SHAPE_SIZE[prop.shape]
        close_up = prop.framing == "close-up"
        is_object = not (prop.refs or prop.backdrop or close_up or prop.people)
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
            continue
        count = prop.people or len(prop.refs)
        if close_up:
            # A detail (hands gripping, a face) is drawn from its words alone, the looks written
            # out: portraits pull the image model back to full bodies. Cut out like a scene.
            who = "".join(f" {x}" for x in (looks(r) for r in prop.refs) if x)
            text = (
                f"Close-up detail shot: {prop.description.rstrip('.')}.{who} Only what the close-up"
                f" frames is visible, no full bodies, isolated. Style: {style}. {NO_TEXT} {GREEN_SCREEN}"
            )
            request = Request([_text(text)], size, False, [])
            job = Job(prop.id, "prop", "scene", scope, painter.key(scope, prop.id, text, size), request)
            job.screen = True
            first.append(job)
            continue
        if prop.backdrop:
            # A place, or a moment that needs its place, keeps its background: a framed picture in
            # the upper part of the screen, always wide (a tall one would cover most of the frame).
            size = LANDSCAPE
            figures = f" Exactly {count} figure{'s' if count != 1 else ''}." if count else ""
            acting = (
                " The people act the moment out in its place, caught in the middle of what they are"
                " doing: not posed side by side facing the viewer like a portrait. A medium shot: the"
                " people fill most of the picture's height, their faces and feelings clearly visible,"
                " the place around them."
                if count
                else ""
            )
            text = (
                f"Create one new image: {prop.description.rstrip('.')}.{figures}{acting}"
                f" Style: {style}. {NO_TEXT}"
            )
            job = Job(prop.id, "prop", "card", scope, "", Request([_text(text)], size, False, []))
        else:
            # A scene of people is cut out of its background:
            # the figures and what they use float over the video. Drawn on a green screen and keyed
            # out here (SAM cuts out one thing at a time, not two people and their bench).
            names = [named(r) for r in prop.refs]
            cast = ""
            if names:
                verb = "each appear" if len(names) > 1 else "appears"
                cast = (
                    f" {' and '.join(names)} {verb} exactly once, in the pose and place the scene describes."
                    " Do not copy the reference pictures or their standing pose, and do not place them"
                    " beside the scene."
                )
            text = (
                f"Create one new image, one single scene: {prop.description.rstrip('.')}.{cast}"
                f" {count} {'person' if count == 1 else 'people'} in total. Only the figures and what"
                " they use, fully visible and centred: no walls, no floor, no room around them."
                f" Style: {style}. {NO_TEXT} {GREEN_SCREEN}"
            )
            job = Job(prop.id, "prop", "scene", scope, "", Request([_text(text)], size, False, []))
            job.screen = True
        job.refs = list(prop.refs)
        if prop.refs:
            second.append(job)  # its key depends on the portraits drawn first
        else:
            job.key = painter.key(scope, prop.id, text, job.request.size)
            first.append(job)
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
    earlier = project.part_pictures or {}
    for cid in characters:  # characters whose portrait for this chapter is already drawn
        look = chapter_look(bible.characters[cid], n)
        if look and look.image and painter.exists("novel", look.image):
            before = earlier.get(cid)
            checked = before is not None and before.key == look.image  # checked when it was drawn
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
                    checked=checked and before.checked,
                    problems=list(before.problems) if checked else [],
                )
    with ThreadPoolExecutor(ctx.settings.image_parallel) as pool:
        for picture in pool.map(painter.draw, first):
            kept = pictures.get(picture.id)
            if picture.error and kept is not None and kept.key:  # a redraw that failed: the old one stays
                ctx.log(f"Muse Image: {picture.id} keeps the portrait it had ({picture.error})")
                continue
            pictures[picture.id] = picture
    for job in second:  # scenes and variants are drawn from this part's portraits
        content: list[dict] = []
        refs = []
        for number, rid in enumerate(job.refs[:2], 1):
            ref = pictures.get(rid)
            if ref is None or not ref.key:
                continue
            name = named(rid)
            content += [
                _text(f"Reference {number}: {name}. Use it only for how {name} looks."),
                _ref_part(painter.path(ref.scope, ref.key)),
            ]
            refs.append(ref.key)
        job.request = Request([*content, *job.request.content], job.request.size, False, job.refs)
        drawn = [job.request.size] if job.kind == "prop" else []  # scenes became wide: draw them again
        job.key = painter.key(job.scope, job.id, [p.get("text") for p in job.request.content], refs, *drawn)
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
