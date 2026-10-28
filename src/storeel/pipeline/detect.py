"""SAM 3.1 on frames of the user's video.

Two jobs: cut out the characters and objects the video shows (so Muse Image draws *their*
cat, not a cat), and find the speaker's face while each picture card is on screen (so the
card is placed beside it, not over it).
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageFilter

from ..common import digest
from ..jobs import JobContext
from ..media import ffmpeg as ff
from ..meta.sam import Detection, segment_image
from ..models import Analysis, Entity, Moment, Region, Source, Style

VERSION = 1
MIN_CONFIDENCE = 0.35
FACE_CONFIDENCE = 0.3
MIN_AREA = 0.003  # of the frame
CUTOUT_MIN_AREA = 0.02  # of a generated picture: the subject is meant to be large
REF_SIDE = 1024
REF_BACKGROUND = (238, 238, 238)
PARALLEL = 4


def _frame(ctx: JobContext, source: Source, seconds: float) -> Image.Image:
    key = f"work/frames/{seconds:09.3f}.png"
    path = ctx.files.prepare(key)
    if not path.exists():
        ff.extract_frame(ctx.files.path(source.key), seconds, path, duration=source.duration)
    with Image.open(path) as image:
        return image.convert("RGB")


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def _segment(ctx: JobContext, image: Image.Image, prompt: str) -> list[Detection]:
    detections = segment_image(
        ctx.client,
        model=ctx.settings.sam_model,
        image=_jpeg(image),
        mime="image/jpeg",
        prompt=prompt,
        cancel=ctx.cancelled,
    )
    ctx.spend(sam_images=1)
    return detections


def cutout(frame: Image.Image, detection: Detection) -> Image.Image:
    """The detected object on a plain light background, cropped with a little room around it."""
    mask = detection.full_mask(frame.width, frame.height)
    alpha = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.2))
    pad_x = round((detection.right - detection.left) * 0.08)
    pad_y = round((detection.bottom - detection.top) * 0.08)
    box = (
        max(0, detection.left - pad_x),
        max(0, detection.top - pad_y),
        min(frame.width, detection.right + pad_x),
        min(frame.height, detection.bottom + pad_y),
    )
    plate = Image.new("RGB", frame.size, REF_BACKGROUND)
    plate.paste(frame, (0, 0), alpha)
    crop = plate.crop(box)
    crop.thumbnail((REF_SIDE, REF_SIDE), Image.LANCZOS)
    return crop


def transparent_cutout(image: Image.Image, detection: Detection) -> Image.Image:
    """The detected subject alone (RGBA, soft 1 px edge), cropped to it with a little room."""
    mask = detection.full_mask(image.width, image.height)
    alpha = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.0))
    rgba = image.convert("RGB").convert("RGBA")
    rgba.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
    if bbox is None:
        return rgba
    pad = round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.02)
    return rgba.crop(
        (
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(image.width, bbox[2] + pad),
            min(image.height, bbox[3] + pad),
        )
    )


def cut_out(ctx: JobContext, png: bytes, subject: str) -> tuple[bytes, int, int] | None:
    """`subject` cut out of a generated picture by SAM, as an RGBA PNG; None when not found."""
    with Image.open(io.BytesIO(png)) as opened:
        picture = opened.convert("RGB")
    found = [
        d
        for d in _segment(ctx, picture, subject)
        if d.confidence >= MIN_CONFIDENCE and d.box_area >= CUTOUT_MIN_AREA * picture.width * picture.height
    ]
    if not found:
        return None
    best = max(found, key=lambda d: d.score)  # only this one's mask gets decoded
    cut = transparent_cutout(picture, best)
    return _png(cut), cut.width, cut.height


def _times(entity: Entity, duration: float) -> list[float]:
    """Where to look: the time Muse Spark gave, around it, then across the video."""
    times: list[float] = []
    if entity.visible_at is not None:
        times += [entity.visible_at, entity.visible_at + 1.0, entity.visible_at - 1.0]
    times += [duration * 0.5, duration * 0.25]
    out: list[float] = []
    for t in times:
        t = round(min(max(0.0, t), max(0.0, duration - 0.1)), 2)
        if all(abs(t - u) > 0.3 for u in out):
            out.append(t)
    return out[:4]


def _reference(ctx: JobContext, source: Source, entity: Entity) -> tuple[str, str] | None:
    version = digest(VERSION, source.digest, entity.kind, entity.segment_prompt, entity.visible_at)
    key = f"refs/{entity.id}-{version}.png"
    if ctx.files.exists(key):
        return entity.id, key
    for seconds in _times(entity, source.duration):
        ctx.check()
        frame = _frame(ctx, source, seconds)
        if entity.kind == "place":
            image = frame.copy()
            image.thumbnail((REF_SIDE, REF_SIDE), Image.LANCZOS)
            ctx.files.write_bytes(key, _png(image))
            return entity.id, key
        min_area = MIN_AREA * frame.width * frame.height
        found = [d for d in _segment(ctx, frame, entity.segment_prompt) if d.confidence >= MIN_CONFIDENCE]
        found = [d for d in found if d.box_area >= min_area]
        if found:
            best = max(found, key=lambda d: d.score)  # only this one's mask gets decoded
            ctx.files.write_bytes(key, _png(cutout(frame, best)))
            ctx.log(f"SAM: {entity.name} ({entity.segment_prompt!r}) found at {seconds:.1f}s")
            return entity.id, key
    ctx.log(
        f"SAM: {entity.name} ({entity.segment_prompt!r}) not found in the video; it will be drawn from words"
    )
    return None


def references(ctx: JobContext, source: Source, analysis: Analysis) -> None:
    """Reference images, cut from the video, for every entity Muse Spark saw in it."""
    wanted = [e for e in analysis.entities if e.visible_in_video and not ctx.files.exists(e.ref_key)]
    if not wanted:
        return
    with ThreadPoolExecutor(PARALLEL) as pool:
        found = dict(r for r in pool.map(lambda e: _reference(ctx, source, e), wanted) if r)

    def save(project) -> None:
        if project.analysis is None:
            return
        for entity in project.analysis.entities:
            if entity.id in found:
                entity.ref_key, entity.ref_source = found[entity.id], "video"

    ctx.update(save)
    for entity in analysis.entities:
        if entity.id in found:
            entity.ref_key, entity.ref_source = found[entity.id], "video"


def _faces(ctx: JobContext, source: Source, moment: Moment) -> list[Region]:
    seconds = (moment.start + moment.end) / 2
    frame = _frame(ctx, source, seconds)
    faces = []
    for d in _segment(ctx, frame, "face"):
        if d.confidence >= FACE_CONFIDENCE:
            faces.append(
                Region(
                    x0=d.left / frame.width,
                    y0=d.top / frame.height,
                    x1=d.right / frame.width,
                    y1=d.bottom / frame.height,
                )
            )
    return faces


def find_faces(
    ctx: JobContext, source: Source, analysis: Analysis, style: Style, only: set[str] | None = None
) -> None:
    """Face boxes while each card or cut-out is on screen: for "blur only when the face is
    covered", and so a standing cut-out stands on the side away from the face."""

    def needs(m: Moment) -> bool:
        if m.display == "cutaway" or m.faces is not None or not m.enabled:
            return False
        return style.speaker_behind == "auto" or m.display == "cutout"

    wanted = [m for m in analysis.moments if needs(m) and (only is None or m.id in only)]
    if not wanted:
        return
    with ThreadPoolExecutor(PARALLEL) as pool:
        results = dict(
            zip((m.id for m in wanted), pool.map(lambda m: _faces(ctx, source, m), wanted), strict=True)
        )
    ctx.log(f"SAM: looked for faces at {len(results)} moment(s)")

    def save(project) -> None:
        if project.analysis is None:
            return
        for moment in project.analysis.moments:
            if moment.id in results:
                moment.faces = results[moment.id]

    ctx.update(save)
    for moment in analysis.moments:
        if moment.id in results:
            moment.faces = results[moment.id]
