"""Compile the reel: the user's video with the generated pictures, captions and watermark.

In the layout, the speaker's video fills the frame, and pictures
float over it as photo cards in the upper part, cut-out characters standing at the bottom,
or cut-out objects in the upper middle. A picture can also fill the screen (a cutaway with a
slow Ken Burns zoom). While a card or cut-out is up, the speaker can be blurred and dimmed
behind it (style "speaker_behind"), fading in and out over half a second.

Python draws only the overlay layer (RGBA) and the blur level; ffmpeg decodes the user's
video, blurs a copy, blends the two by that level, puts the layer on top and encodes. The
blur level rides in two extra rows under each overlay frame, so one pipe carries both.
Frames where nothing moves are drawn once and resent, which keeps the Python side cheap.
Audio is the user's own, loudness-normalised to -14 LUFS.
"""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from ..common import Cancelled, now_iso
from ..files import ProjectFiles
from ..jobs import JobContext, PipelineError
from ..media import ffmpeg as ff
from ..models import Moment, Project, Region, Render, Style
from .captions import build_pages
from .layout import (
    CAPTION_CENTER,
    CHARACTER_BOTTOM,
    CHARACTER_HEIGHT,
    CHARACTER_MAX_WIDTH,
    card_box,
    character_x,
    covered,
    object_box,
    to_region,
)
from .render import caption_page, card, cutout_sprite, watermark

W, H = ff.WIDTH, ff.HEIGHT
MASK_ROWS = 2  # under each overlay frame: the blur level, as the alpha of these rows
OVERLAY_FPS_MAX = 30  # the overlay layer runs at half rate on 50/60 fps reels
CAPTION_SIZE = 0.042  # of the height
CAPTION_WIDTH = 0.76  # of the width: the platforms' buttons cover the right edge
WATERMARK_SIZE = 0.026
WATERMARK_Y = {"center": 0.5, "top": 0.135, "bottom": 0.865}
CUT_FADE = 0.2
POP_IN, FADE_OUT = 0.21, 0.15  # sprite entrance (fade + 2% rise) and exit
ZOOM = 0.08  # Ken Burns: cutaways zoom by this much over their time on screen
BLUR_FADE = 0.5  # the speaker blurs and clears over this long
BLUR_JOIN = 1.0  # blurred stretches closer than this are joined, so the speaker does not flicker
BLUR_SIGMA = 18  # at quarter size
BLUR_DIM = 0.56
KEEP_RENDERS = 5


def _composite(canvas: Image.Image, image: Image.Image, x: int, y: int) -> None:
    """alpha_composite, clipped to the canvas."""
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(image.width, canvas.width - x), min(image.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, image.width, image.height):
        image = image.crop((left, top, right, bottom))
    canvas.alpha_composite(image, (x + left, y + top))


def _faded(image: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return image
    faded = image.copy()
    faded.putalpha(image.getchannel("A").point(lambda v: round(v * alpha)))
    return faded


def _ease_out(p: float) -> float:
    return 1 - (1 - min(1.0, max(0.0, p))) ** 3


def _smooth(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


@dataclass
class Placed:
    """Where a card or cut-out goes: the sprite (RGBA, shadow included), its centre, and the
    box the picture itself covers (for checking the face)."""

    image: Image.Image
    center: tuple[int, int]
    box: Region


def place(moment: Moment, picture: Image.Image, style: Style) -> Placed:
    """A card or cut-out sprite for `moment`, placed where the layout puts it."""
    position = style.caption_position
    if moment.display == "cutout" and moment.asset is not None and moment.asset.cutout:
        standing = picture.height >= picture.width * 1.15  # a tall cut-out: a character standing
        if standing:
            height = round(CHARACTER_HEIGHT * H)
            sprite = cutout_sprite(picture, round(CHARACTER_MAX_WIDTH * W), height)
            inner = ImageOps.contain(picture, (round(CHARACTER_MAX_WIDTH * W), height)).size
            cx = round(character_x(moment.faces) * W)
            bottom = round(CHARACTER_BOTTOM * H)
            cy = bottom - inner[1] // 2
            box = to_region(cx - inner[0] // 2, bottom - inner[1], *inner)
            return Placed(sprite, (cx, cy), box)
        max_w, max_h, cy = object_box(position)
        sprite = cutout_sprite(picture, max_w, max_h)
        inner = ImageOps.contain(picture, (max_w, max_h)).size
        return Placed(sprite, (W // 2, cy), to_region(W // 2 - inner[0] // 2, cy - inner[1] // 2, *inner))
    max_w, max_h, cy = card_box(position)
    sprite = card(picture, max_w, max_h)
    inner = ImageOps.contain(picture, (max_w, max_h)).size
    return Placed(sprite, (W // 2, cy), to_region(W // 2 - inner[0] // 2, cy - inner[1] // 2, *inner))


def blur_windows(spans: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """The stretches where the speaker is blurred: the spans, with short gaps joined."""
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] < BLUR_JOIN:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(max(0.0, a), min(duration, b)) for a, b in merged]


@dataclass
class _Page:
    start: float
    end: float
    image: Image.Image
    xy: tuple[int, int]
    marks: list[tuple[Image.Image, tuple[int, int]]]
    word_starts: list[float]

    def word_at(self, t: float) -> int:
        index = -1
        for k, start in enumerate(self.word_starts):
            if t >= start:
                index = k
        return max(index, 0)


@dataclass
class _Cutaway:
    start: float
    end: float
    source: Image.Image  # RGB, (1 + ZOOM) times the frame
    zoom_in: bool

    def frame(self, t: float) -> Image.Image:
        progress = _smooth((t - self.start) / max(0.01, self.end - self.start))
        zoom = 1 + ZOOM * (progress if self.zoom_in else 1 - progress)
        box_w, box_h = self.source.width / zoom, self.source.height / zoom
        cx, cy = self.source.width / 2, self.source.height / 2
        box = (cx - box_w / 2, cy - box_h / 2, cx + box_w / 2, cy + box_h / 2)
        frame = self.source.resize((W, H), Image.BILINEAR, box=box).convert("RGBA")
        alpha = min(1.0, (t - self.start) / CUT_FADE, (self.end - t) / CUT_FADE)
        return _faded(frame, max(0.0, alpha))


@dataclass
class _Card:
    """A card or cut-out: pops in (fade and a small rise), fades out. With `animate` off it is
    simply there for its time; with `enter` off it is there from its first frame (the part badge,
    which the platforms' cover frame must show) and still fades out when it leaves."""

    start: float
    end: float
    image: Image.Image  # RGBA
    center: tuple[int, int]
    ident: int = field(default=0)
    animate: bool = True
    enter: bool = True

    def animating(self, t: float) -> bool:
        entering = self.enter and t - self.start < POP_IN
        return self.animate and (entering or self.end - t < FADE_OUT)

    def draw(self, canvas: Image.Image, t: float) -> None:
        alpha, rise = 1.0, 0.0
        if self.animate and self.enter and t - self.start < POP_IN:
            eased = _ease_out((t - self.start) / POP_IN)
            alpha, rise = eased, (1 - eased) * 0.02 * H
        elif self.animate and self.end - t < FADE_OUT:
            alpha = max(0.0, (self.end - t) / FADE_OUT)
        image = _faded(self.image, alpha)
        x = round(self.center[0] - image.width / 2)
        y = round(self.center[1] - image.height / 2 + rise)
        _composite(canvas, image, x, y)


class Compositor:
    """Builds every overlay element up front, then yields the layer frame by frame."""

    def __init__(self, project: Project, files: ProjectFiles) -> None:
        if project.source is None:
            raise PipelineError("process the clips before rendering")
        self.duration = project.source.duration
        fps = project.source.fps
        self.overlay_fps = fps if fps <= OVERLAY_FPS_MAX else fps // 2
        style = project.style
        self.pages: list[_Page] = []
        if style.captions != "off" and project.transcript is not None:
            size = round(H * CAPTION_SIZE)
            center_y = CAPTION_CENTER[style.caption_position] * H
            for page in build_pages(project.transcript.turns, style.caption_case):
                layout = caption_page(
                    [w.text for w in page.words],
                    size,
                    round(W * CAPTION_WIDTH),
                    style.captions,
                    style.caption_color,
                )
                xy = (round(W / 2 - layout.image.width / 2), round(center_y - layout.image.height / 2))
                starts = [w.start for w in page.words]
                self.pages.append(_Page(page.start, page.end, layout.image, xy, layout.marks, starts))
        self.cutaways: list[_Cutaway] = []
        self.cards: list[_Card] = []
        self.unchecked_faces = 0  # "auto" blur without face boxes: blurred to be safe
        self.blurs = blur_windows(self._build_pictures(project, files), self.duration)
        self.mark: tuple[Image.Image, tuple[int, int]] | None = None
        if style.watermark:
            image = watermark(style.watermark, round(H * WATERMARK_SIZE), round(W * 0.8))
            y = WATERMARK_Y[style.watermark_position] * H
            self.mark = (image, (round(W / 2 - image.width / 2), round(y - image.height / 2)))

    def _build_pictures(self, project: Project, files: ProjectFiles) -> list[tuple[float, float]]:
        """The moments' pictures as cutaways and cards; returns the spans to blur the speaker in."""
        style = project.style
        spans: list[tuple[float, float]] = []
        moments = project.analysis.moments if project.analysis else []
        for moment in moments:
            if not (moment.enabled and moment.asset and files.exists(moment.asset.key)):
                continue
            start, end = max(0.0, moment.start), min(self.duration, moment.end)
            if end - start < 0.3:
                continue
            with Image.open(files.path(moment.asset.key)) as opened:
                picture = opened.convert("RGBA" if moment.asset.cutout else "RGB")
            if moment.display == "cutaway":
                size = (round(W * (1 + ZOOM)), round(H * (1 + ZOOM)))
                source = ImageOps.fit(picture.convert("RGB"), size, Image.LANCZOS)
                self.cutaways.append(_Cutaway(start, end, source, zoom_in=len(self.cutaways) % 2 == 0))
                continue
            placed = place(moment, picture, style)
            self.cards.append(_Card(start, end, placed.image, placed.center, ident=len(self.cards) + 1))
            blur = style.speaker_behind == "blur"
            if style.speaker_behind == "auto":
                hit = covered(placed.box, moment.faces)
                if hit is None:
                    self.unchecked_faces += 1
                blur = hit is not False
            if blur:
                spans.append((start, end))
        return spans

    @property
    def frame_count(self) -> int:
        return max(1, math.ceil(self.duration * self.overlay_fps - 1e-6))

    def _page_at(self, t: float) -> int | None:
        for index, page in enumerate(self.pages):
            if page.start <= t < page.end:
                return index
        return None

    def blur_level(self, t: float) -> float:
        """0 (sharp) to 1 (fully blurred and dimmed): fades in before a window, out after it."""
        level = 0.0
        half = BLUR_FADE / 2
        for start, end in self.blurs:
            if start - half <= t <= end + half:
                rise = _smooth((t - (start - half)) / BLUR_FADE)
                fall = _smooth(((end + half) - t) / BLUR_FADE)
                level = max(level, min(rise, fall))
        return level

    def frame(self, t: float) -> Image.Image:
        """The overlay layer at `t`, with MASK_ROWS extra rows at the bottom holding the blur level."""
        canvas = Image.new("RGBA", (W, H + MASK_ROWS), (0, 0, 0, 0))
        cut = next((c for c in self.cutaways if c.start <= t < c.end), None)
        if cut is not None:
            canvas.paste(cut.frame(t), (0, 0))
        for item in self.cards:
            if item.start <= t < item.end:
                item.draw(canvas, t)
        index = self._page_at(t)
        if index is not None:
            page = self.pages[index]
            _composite(canvas, page.image, *page.xy)
            if page.marks:
                mark, (dx, dy) = page.marks[page.word_at(t)]
                _composite(canvas, mark, page.xy[0] + dx, page.xy[1] + dy)
        if self.mark is not None:
            _composite(canvas, self.mark[0], *self.mark[1])
        level = round(255 * self.blur_level(t))
        canvas.paste((0, 0, 0, level), (0, H, W, H + MASK_ROWS))  # after the sprites: nothing spills
        return canvas

    def _key(self, t: float) -> tuple | None:
        """Identifies what is on screen; None while something is moving."""
        if any(c.start <= t < c.end for c in self.cutaways):
            return None
        level = self.blur_level(t)
        if 0.0 < level < 1.0:
            return None
        cards = []
        for item in self.cards:
            if item.start <= t < item.end:
                if item.animating(t):
                    return None
                cards.append(item.ident)
        index = self._page_at(t)
        word = self.pages[index].word_at(t) if index is not None else None
        return index, word, tuple(cards), level

    def frames(self) -> Iterator[bytes]:
        last_key: tuple | None = None
        last: bytes = b""
        for i in range(self.frame_count):
            t = i / self.overlay_fps
            key = self._key(t)
            if key is not None and key == last_key:
                yield last
                continue
            data = self.frame(t).tobytes()
            last_key, last = key, data
            yield data


def _rate_args(fit_mb: int | None, duration: float, factor: float) -> tuple[list[str], str]:
    if fit_mb is None:
        return ["-crf", "20", "-maxrate", "14M", "-bufsize", "28M"], "160k"
    audio_kbps = 128
    total_kbit = fit_mb * 8000 * 0.94 * factor  # MB = 10^6 bytes; keep 6% for the container
    video_kbps = int(min(12000, max(300, total_kbit / max(1.0, duration) - audio_kbps)))
    return [
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{int(video_kbps * 1.35)}k",
        "-bufsize",
        f"{video_kbps * 2}k",
    ], f"{audio_kbps}k"


def encode(
    ctx: JobContext,
    compositor: Compositor,
    master: Path,
    out: Path,
    *,
    audio_filter: str | None,
    fit_mb: int | None = None,
    factor: float = 1.0,
) -> None:
    rate, audio_bitrate = _rate_args(fit_mb, compositor.duration, factor)
    fades = [
        "afade=t=in:d=0.04",
        f"afade=t=out:st={max(0.0, compositor.duration - 0.08):.3f}:d=0.08",
    ]
    audio = ",".join([audio_filter, *fades] if audio_filter else fades)
    layer_in = f"[1:v]split=2[lraw][mraw];[lraw]crop={W}:{H}:0:0,"
    layer = layer_in + "scale=out_color_matrix=bt709:out_range=tv,format=yuva420p[layer]"
    finish = f"overlay=x=0:y=0:format=yuv420:eof_action=repeat,format=yuv420p,{ff.TAG_BT709}[v]"
    if compositor.blurs:
        # The blurred, dimmed copy is made at quarter size (cheap) and blended in by the level
        # carried in the layer's extra rows.
        dim = BLUR_DIM
        blur = (
            f"[0:v]split=2[sharp][soft];[soft]scale={W // 4}:{H // 4},gblur=sigma={BLUR_SIGMA},"
            f"lutyuv=y='16+(val-16)*{dim}':u='128+(val-128)*{dim}':v='128+(val-128)*{dim}',"
            f"scale={W}:{H}[blurred];"
            f"[mraw]crop={W}:{MASK_ROWS}:0:{H},alphaextract,scale={W}:{H}[mask];"
            "[blurred][mask]alphamerge[veil];"
            "[sharp][veil]overlay=x=0:y=0:format=yuv420:eof_action=repeat[base]"
        )
        graph = f"{layer};{blur};[base][layer]{finish}"
    else:
        graph = f"{layer};[mraw]nullsink;[0:v][layer]{finish}"
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(master)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{H + MASK_ROWS}"]
    cmd += ["-framerate", str(compositor.overlay_fps), "-i", "pipe:0"]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a:0"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-profile:v", "high", *rate]
    cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    cmd += ["-af", audio, "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2"]
    cmd += ["-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    errors: deque[str] = deque(maxlen=50)

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            errors.append(line.decode(errors="replace").rstrip())

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    total = compositor.frame_count
    started = time.monotonic()
    assert proc.stdin is not None
    try:
        for index, frame in enumerate(compositor.frames()):
            if index % 10 == 0:
                if ctx.cancelled():
                    raise Cancelled
                ctx.progress(index / total)
            proc.stdin.write(frame)
        proc.stdin.close()
    except BrokenPipeError:
        pass  # ffmpeg stopped reading: its exit code says whether that was an error
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    code = proc.wait()
    reader.join(timeout=5)
    if code != 0:
        raise ff.FFmpegError("encoding the reel failed: " + (" | ".join(list(errors)[-5:]) or f"exit {code}"))
    ctx.log(f"encoded {total} overlay frames in {time.monotonic() - started:.1f}s")


def compose(
    ctx: JobContext, project: Project, fit_mb: int | None = None, compositor: Compositor | None = None
) -> Render:
    files = ctx.files
    if project.source is None:
        raise PipelineError("process the clips before rendering")
    master = files.path(project.source.key)
    compositor = compositor or Compositor(project, files)
    ctx.log(
        f"compose: {compositor.duration:.1f}s at {project.source.fps} fps,"
        f" {len(compositor.pages)} caption pages, {len(compositor.cutaways)} full-screen pictures,"
        f" {len(compositor.cards)} cards and cut-outs, speaker blurred in {len(compositor.blurs)}"
        f" stretch(es) ({project.style.speaker_behind})"
    )
    if compositor.unchecked_faces:
        ctx.log(
            f"{compositor.unchecked_faces} picture(s) have no face check yet, so the speaker is blurred"
            " behind them; update the pictures to check"
        )
    stats = ff.measure_loudness(master, cancel=ctx.cancelled)
    audio_filter = ff.loudnorm_filter(stats)
    if stats is not None:
        ctx.log(f"loudness {stats['input_i']} LUFS -> -14 LUFS")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    key = f"renders/reel-{stamp}.mp4"
    out = files.prepare(key)
    tmp = out.with_name(f".{out.stem}.tmp.mp4")
    factor = 1.0
    try:
        for attempt in range(2):
            encode(ctx, compositor, master, tmp, audio_filter=audio_filter, fit_mb=fit_mb, factor=factor)
            size = tmp.stat().st_size
            if fit_mb is None or size <= fit_mb * 1_000_000 or attempt == 1:
                break
            factor *= 0.9 * fit_mb * 1_000_000 / size
            ctx.log(f"{size / 1e6:.1f} MB is over {fit_mb} MB; encoding again at a lower bitrate")
        info = ff.probe(tmp)
        if abs(info.duration - compositor.duration) > 0.35 or (info.width, info.height) != (W, H):
            raise ff.FFmpegError(
                f"the rendered file looks wrong ({info.width}x{info.height}, {info.duration:.2f}s"
                f" instead of {compositor.duration:.2f}s)"
            )
        if fit_mb is not None and tmp.stat().st_size > fit_mb * 1_000_000:
            ctx.log(f"still {tmp.stat().st_size / 1e6:.1f} MB, over the {fit_mb} MB target")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    render = Render(
        id=stamp,
        key=key,
        created_at=now_iso(),
        duration=round(info.duration, 3),
        size=out.stat().st_size,
        fit_mb=fit_mb,
    )

    def add(p: Project) -> list[str]:
        p.renders.append(render)
        dropped = p.renders[:-KEEP_RENDERS]
        p.renders = p.renders[-KEEP_RENDERS:]
        return [r.key for r in dropped]

    _, dropped = ctx.update(add)
    for old in dropped:
        files.delete(old)
    ctx.log(f"render: {key} ({render.size / 1e6:.1f} MB, {render.duration:.1f}s)")
    return render
