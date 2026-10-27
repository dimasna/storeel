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
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

from ..common import digest
from ..jobs import JobContext, PipelineError
from ..media.ffmpeg import HEIGHT, WIDTH
from ..meta import MetaAPIError
from ..models import Analysis, Asset, Entity, Moment, Project, Style
from .compose import shown_region

VERSION = 1
STYLES = {
    "cinematic": "cinematic photograph, natural light, realistic detail, shallow depth of field",
    "illustration": "clean modern digital illustration, soft shading, rich colours",
    "3d": "stylised 3D animated film still, soft global illumination, expressive characters",
    "anime": "anime film still, clean line art, vibrant colours, painted background",
    "watercolor": "soft watercolour illustration on textured paper, gentle colours",
    "comic": "bold comic-book art, thick black outlines, flat vivid colours",
}
NO_TEXT = "No text, letters, captions, logos or watermarks anywhere in the image."
CARD_SIZES = [(16 / 9, "1600x900"), (4 / 3, "1440x1080"), (1.0, "1080x1080"), (3 / 4, "1080x1440")]
FULL_SIZE = "1080x1920"
MAX_REFERENCES = 4
ANCHOR = {
    "character": (
        "1024x1536",
        "Character reference of {name}: {description}. One figure, full body, standing, facing the viewer, "
        "neutral expression, plain light grey background.",
    ),
    "object": (
        "1080x1080",
        "Reference image of {name}: {description}. The object alone, centred, plain light grey background, "
        "soft even light.",
    ),
    "place": ("1536x1024", "Establishing shot of {name}: {description}. No people."),
}


@dataclass
class Request:
    content: list[dict]
    size: str
    image_search: bool
    references: list[str]  # entity ids whose reference image is included

    def fingerprint(self) -> list:
        """Everything that changes the image, with image parts reduced to their hashes."""
        parts = []
        for part in self.content:
            if part["type"] == "input_image":
                parts.append(digest(part["image_url"]))
            else:
                parts.append(part["text"])
        return [parts, self.size, self.image_search]


def card_size(moment: Moment, style: Style) -> str:
    region = shown_region(moment, style.caption_position, style.captions != "off")
    if region is None:
        return FULL_SIZE
    aspect = (region.width * WIDTH) / (region.height * HEIGHT)
    return min(CARD_SIZES, key=lambda option: abs(math.log(aspect / option[0])))[1]


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
    size = card_size(moment, style)
    text = f"Create one new image: {moment.prompt.rstrip('.')}."
    for entity in shown:
        if entity not in with_refs and entity.description:
            text += f" {entity.name} looks like this: {entity.description.rstrip('.')}."
    text += f" Style: {STYLES[style.visual_style]}."
    if size == FULL_SIZE:
        text += (
            " Vertical 9:16 frame. Keep the main subject in the upper two thirds; the bottom third sits under"
            " captions, so keep it simple."
        )
    else:
        text += " The subject is centred and fills the frame."
    text += f" {NO_TEXT}"
    if with_refs:
        text += " Draw a new scene: do not copy the reference images or their plain backgrounds."
    content.append({"type": "input_text", "text": text})
    image_search = any(entity.real_world for entity in shown)
    return Request(content, size, image_search, [e.id for e in with_refs])


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
            png, width, height, seconds = generate(ctx, request)
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
                prompt = " ".join(p["text"] for p in request.content if p["type"] == "input_text")
                asset = Asset(
                    key=key, width=width, height=height, digest=key.rsplit("-", 1)[-1][:-4], prompt=prompt
                )
            done["reused"] += 1
        else:
            try:
                try:
                    png, width, height, seconds = generate(ctx, request)
                except MetaAPIError as exc:
                    if not (exc.content_policy and request.references):
                        raise
                    ctx.log(f"Muse Image refused {moment.id} with references; trying from words only")
                    request = moment_request(ctx, moment, entities, style, use_references=False)
                    png, width, height, seconds = generate(ctx, request)
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
                )
                done["made"] += 1
                ctx.log(f"Muse Image: {moment.id} {width}x{height} ({request.size} asked) in {seconds:.1f}s")
            except MetaAPIError as exc:
                error = str(exc)
                done["failed"] += 1
                ctx.log(f"Muse Image: {moment.id} failed: {exc}")
        old_key = moment.asset.key if moment.asset else None

        def save(project: Project) -> None:
            if project.analysis is None:
                return
            for stored in project.analysis.moments:
                if stored.id == moment.id:
                    stored.asset = asset if asset is not None else stored.asset
                    stored.error = error
                    stored.note = (
                        "no room beside the face, so it is shown full screen"
                        if stored.display == "overlay" and request.size == FULL_SIZE
                        else None
                    )

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
