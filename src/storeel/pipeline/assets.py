"""Muse Image: reference pictures for recurring entities, then one picture per moment.

Consistency comes from reference images, as Meta's "keep an image series consistent"
recipe recommends: an entity seen in the video is cut out of it by SAM; an entity that
appears in several pictures but not in the video gets a generated reference first. Each
moment's request interleaves the references (captioned) with the scene description.
Requests use `store: false`, so nothing the user sends is kept server-side.
"""

from __future__ import annotations

import base64
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

from ..common import digest
from ..jobs import JobContext, PipelineError
from ..meta import MetaAPIError
from ..models import Analysis, Asset, Entity, Moment, Project, Style
from .detect import cut_out

VERSION = 2  # 2: cards in 3:2, cut-outs on a plain background, cut by SAM
STYLES = {
    "realistic_3d": "realistic 3D character render, soft studio lighting",
    "cinematic": "cinematic photograph, natural light, realistic detail, shallow depth of field",
    "illustration": "clean modern digital illustration, soft shading, rich colours",
    "3d": "stylised 3D animated film still, soft global illumination, expressive characters",
    "anime": "anime film still, clean line art, vibrant colours, painted background",
    "watercolor": "soft watercolour illustration on textured paper, gentle colours",
    "comic": "bold comic-book art, thick black outlines, flat vivid colours",
}
NO_TEXT = "No text, letters, captions, logos or watermarks anywhere in the image."
# The Responses API's image_generation tool takes only these sizes ("auto" aside) and rejects
# any other "WxH" with "unknown value", even though the guide describes free-form sizes.
LANDSCAPE, SQUARE, PORTRAIT = "1536x1024", "1024x1024", "1024x1536"
# Cards are 3:2 photos, the nearest allowed shape to a 16:9 card. Full-screen pictures
# are asked for in the tallest shape, 2:3, and centre-cropped to 9:16. Cut-outs: a standing
# character is tall, anything else square.
CARD_SIZE, FULL_SIZE = LANDSCAPE, PORTRAIT
CUTOUT_BACKGROUND = (
    "Show only {subject}, whole and uncropped, centred with space around it, on a plain flat light grey"
    " background with nothing else in the picture: no other objects, no floor, no shadow on the ground."
)
MAX_REFERENCES = 4
ANCHOR = {
    "character": (
        PORTRAIT,
        "Character reference of {name}: {description}. One figure, full body, standing, facing the viewer, "
        "neutral expression, plain light grey background.",
    ),
    "object": (
        SQUARE,
        "Reference image of {name}: {description}. The object alone, centred, plain light grey background, "
        "soft even light.",
    ),
    "place": (LANDSCAPE, "Establishing shot of {name}: {description}. No people."),
}


@dataclass
class Request:
    content: list[dict]
    size: str
    image_search: bool
    references: list[str]  # entity ids whose reference image is included
    display: str = "overlay"
    subject: str = ""  # for a cut-out: what SAM cuts out

    @property
    def full_screen(self) -> bool:
        return self.display == "cutaway"

    def fingerprint(self) -> list:
        """Everything that changes the image, with image parts reduced to their hashes."""
        parts = []
        for part in self.content:
            if part["type"] == "input_image":
                parts.append(digest(part["image_url"]))
            else:
                parts.append(part["text"])
        return [parts, self.size, self.image_search, self.display, self.subject]


def cutout_subject(moment: Moment, entities: dict[str, Entity]) -> str:
    """The noun phrase SAM looks for: the planner's, else the main entity's."""
    if moment.subject.strip():
        return " ".join(moment.subject.split())[:60]
    for entity_id in moment.entities:
        entity = entities.get(entity_id)
        if entity is not None:
            return entity.segment_prompt or entity.name
    return ""


def picture_size(moment: Moment, entities: dict[str, Entity]) -> str:
    if moment.display == "cutaway":
        return FULL_SIZE
    if moment.display == "cutout":
        main = next((entities[e] for e in moment.entities if e in entities), None)
        return PORTRAIT if main is not None and main.kind == "character" else SQUARE
    return CARD_SIZE


def _image_part(ctx: JobContext, key: str) -> dict:
    with Image.open(ctx.files.path(key)) as image:
        rgb = image.convert("RGB")
    rgb.thumbnail((1024, 1024), Image.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=90)
    return {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
    }


def anchor_request(entity: Entity, style: Style) -> Request:
    size, template = ANCHOR[entity.kind]
    text = template.format(name=entity.name, description=entity.description.rstrip("."))
    text += f" Style: {STYLES[style.visual_style]}. {NO_TEXT}"
    return Request([{"type": "input_text", "text": text}], size, entity.real_world, [])


def moment_request(
    ctx: JobContext, moment: Moment, entities: dict[str, Entity], style: Style, use_references: bool = True
) -> Request:
    shown = [entities[e] for e in moment.entities if e in entities]
    with_refs = [e for e in shown if use_references and ctx.files.exists(e.ref_key)][:MAX_REFERENCES]
    content: list[dict] = []
    for number, entity in enumerate(with_refs, 1):
        content.append(
            {
                "type": "input_text",
                "text": f"Reference {number}: {entity.name}. Use it only for how {entity.name} looks.",
            }
        )
        content.append(_image_part(ctx, entity.ref_key or ""))
    display = moment.display
    subject = cutout_subject(moment, entities) if display == "cutout" else ""
    if display == "cutout" and not subject:
        display = "overlay"  # nothing to cut out by name: a card instead
    text = f"Create one new image: {moment.prompt.rstrip('.')}."
    for entity in shown:
        if entity not in with_refs and entity.description:
            text += f" {entity.name} looks like this: {entity.description.rstrip('.')}."
    text += f" Style: {STYLES[style.visual_style]}."
    if display == "cutaway":
        text += (
            " Vertical frame, cropped to 9:16 at the sides: keep the main subject centred and in the upper"
            " two thirds; the bottom third sits under captions, so keep it simple."
        )
    elif display == "cutout":
        text += " " + CUTOUT_BACKGROUND.format(subject=subject)
    else:
        text += " A horizontal photo: the subject is centred and fills the frame."
    text += f" {NO_TEXT}"
    if with_refs:
        text += " Draw a new scene: do not copy the reference images or their plain backgrounds."
    content.append({"type": "input_text", "text": text})
    image_search = any(entity.real_world for entity in shown)
    size = picture_size(moment, entities) if display == moment.display else CARD_SIZE
    return Request(content, size, image_search, [e.id for e in with_refs], display=display, subject=subject)


def generate(ctx: JobContext, request: Request) -> tuple[bytes, int, int, float]:
    """One image from Muse Image, normalised to PNG."""
    started = time.monotonic()
    result = ctx.client.responses(
        {
            "model": ctx.settings.image_model,
            "store": False,
            "input": [{"type": "message", "role": "user", "content": request.content}],
            "tools": [
                {
                    "type": "image_generation",
                    "size": request.size,
                    "output_format": "png",
                    "reasoning_strength": ctx.settings.image_reasoning,
                    "enable_image_search": request.image_search,
                    "enable_web_search": False,
                    "enable_shell": False,
                }
            ],
        },
        cancel=ctx.cancelled,
    )
    if not result.images:
        raise MetaAPIError("Muse Image returned no image")
    ctx.spend(images=1)
    with Image.open(io.BytesIO(base64.b64decode(result.images[0]))) as image:
        rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), rgb.width, rgb.height, time.monotonic() - started


POLICY_TRIES = 3  # drawings of one request: the safety filter refuses some and passes others


def generate_allowed(ctx: JobContext, request: Request, name: str) -> tuple[bytes, int, int, float]:
    """generate(), asked again when Muse Image's safety filter refuses the drawing. The filter
    judges each drawing, so the same request often passes on another try (on the real API, two
    scenes refused in a part were both drawn on the next one or two), and a refused drawing is not
    billed. Raises the last refusal after POLICY_TRIES."""
    for attempt in range(1, POLICY_TRIES + 1):
        try:
            return generate(ctx, request)
        except MetaAPIError as exc:
            if not exc.content_policy or attempt == POLICY_TRIES:
                raise
            ctx.log(
                f"Muse Image's safety filter refused {name}; drawing it again ({attempt + 1}/{POLICY_TRIES})"
            )
    raise AssertionError("unreachable")


def _anchors_needed(analysis: Analysis, only: set[str] | None) -> list[Entity]:
    moments = [m for m in analysis.moments if m.enabled and (only is None or m.id in only)]
    uses: dict[str, int] = {}
    for moment in analysis.moments:
        if moment.enabled:
            for entity_id in moment.entities:
                uses[entity_id] = uses.get(entity_id, 0) + 1
    wanted = {e for m in moments for e in m.entities}
    return [
        e for e in analysis.entities if e.id in wanted and uses.get(e.id, 0) >= 2 and e.ref_source != "video"
    ]


def make_anchors(ctx: JobContext, analysis: Analysis, style: Style, only: set[str] | None = None) -> None:
    """Generated references for entities that recur in the pictures but are not in the video."""
    todo: list[tuple[Entity, Request, str]] = []
    for entity in _anchors_needed(analysis, only):
        request = anchor_request(entity, style)
        key = f"refs/{entity.id}-{digest(VERSION, ctx.settings.image_model, request.fingerprint())}.png"
        if ctx.files.exists(key):
            entity.ref_key, entity.ref_source = key, "generated"
        else:
            todo.append((entity, request, key))
    made: dict[str, str] = {}

    def run(item: tuple[Entity, Request, str]) -> None:
        entity, request, key = item
        try:
            png, width, height, seconds = generate_allowed(ctx, request, f"the reference for {entity.name}")
        except MetaAPIError as exc:
            ctx.log(f"Muse Image: reference for {entity.name} failed ({exc}); it will be drawn from words")
            return
        ctx.files.write_bytes(key, png)
        made[entity.id] = key
        ctx.log(f"Muse Image: reference for {entity.name}, {width}x{height} in {seconds:.1f}s")

    if todo:
        with ThreadPoolExecutor(ctx.settings.image_parallel) as pool:
            list(pool.map(run, todo))
    keys = {e.id: e.ref_key for e in analysis.entities if e.ref_source == "generated" and e.ref_key}
    keys.update(made)
    for entity in analysis.entities:
        if entity.id in made:
            entity.ref_key, entity.ref_source = made[entity.id], "generated"

    def save(project: Project) -> None:
        if project.analysis is None:
            return
        for entity in project.analysis.entities:
            if entity.id in keys:
                entity.ref_key, entity.ref_source = keys[entity.id], "generated"

    ctx.update(save)


def make_pictures(ctx: JobContext, analysis: Analysis, style: Style, only: set[str] | None = None) -> None:
    """One picture per enabled moment; pictures whose request has not changed are reused."""
    entities = {e.id: e for e in analysis.entities}
    moments = [m for m in analysis.moments if m.enabled and (only is None or m.id in only)]
    if not moments:
        return
    done = {"count": 0, "made": 0, "reused": 0, "failed": 0}

    def run(moment: Moment) -> None:
        ctx.check()
        request = moment_request(ctx, moment, entities, style)
        version = digest(VERSION, ctx.settings.image_model, request.fingerprint(), moment.take)
        key = f"assets/{moment.id}-{version}.png"
        asset: Asset | None = None
        error: str | None = None
        if ctx.files.exists(key):
            if moment.asset is not None and moment.asset.key == key:
                asset = moment.asset
            else:  # made by an earlier run that stopped before saving it
                with Image.open(ctx.files.path(key)) as image:
                    width, height = image.size
                    cut = image.mode == "RGBA"
                prompt = " ".join(p["text"] for p in request.content if p["type"] == "input_text")
                asset = Asset(
                    key=key,
                    width=width,
                    height=height,
                    digest=key.rsplit("-", 1)[-1][:-4],
                    prompt=prompt,
                    cutout=cut,
                )
            done["reused"] += 1
        else:
            try:
                try:
                    png, width, height, seconds = generate_allowed(ctx, request, moment.id)
                except MetaAPIError as exc:
                    if not (exc.content_policy and request.references):
                        raise
                    ctx.log(f"Muse Image refused {moment.id} with references; trying from words only")
                    request = moment_request(ctx, moment, entities, style, use_references=False)
                    png, width, height, seconds = generate_allowed(ctx, request, moment.id)
                cut = False
                if request.display == "cutout":
                    try:
                        made = cut_out(ctx, png, request.subject)
                    except MetaAPIError as exc:
                        made = None
                        ctx.log(f"SAM: cutting out {moment.id} failed ({exc}); shown as a card")
                    if made is not None:
                        png, width, height = made
                        cut = True
                ctx.files.write_bytes(key, png)
                prompt = " ".join(p["text"] for p in request.content if p["type"] == "input_text")
                asset = Asset(
                    key=key,
                    width=width,
                    height=height,
                    digest=key.rsplit("-", 1)[-1].removesuffix(".png"),
                    prompt=prompt,
                    references=request.references,
                    seconds=round(seconds, 1),
                    cutout=cut,
                )
                done["made"] += 1
                shape = f"cut out {width}x{height}" if cut else f"{width}x{height} ({request.size} asked)"
                ctx.log(f"Muse Image: {moment.id} {shape} in {seconds:.1f}s")
            except MetaAPIError as exc:
                error = str(exc)
                done["failed"] += 1
                ctx.log(f"Muse Image: {moment.id} failed: {exc}")
        old_key = moment.asset.key if moment.asset else None
        note = None
        if asset is not None and moment.display == "cutout" and not asset.cutout:
            note = (
                f"SAM could not find {request.subject!r} in the picture, so it is shown as a card"
                if request.display == "cutout"
                else "no subject to cut out, so it is shown as a card"
            )

        def save(project: Project) -> None:
            if project.analysis is None:
                return
            for stored in project.analysis.moments:
                if stored.id == moment.id:
                    stored.asset = asset if asset is not None else stored.asset
                    stored.error = error
                    stored.note = note

        ctx.update(save)
        if asset is not None and old_key and old_key != asset.key:
            ctx.files.delete(old_key)
        done["count"] += 1
        ctx.progress(done["count"] / len(moments))

    with ThreadPoolExecutor(ctx.settings.image_parallel) as pool:
        list(pool.map(run, moments))
    ctx.log(f"pictures: {done['made']} new, {done['reused']} reused, {done['failed']} failed")
    if done["failed"] and not (done["made"] or done["reused"]):
        raise PipelineError("Muse Image could not make any picture; see the log")
