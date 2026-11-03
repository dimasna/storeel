"""Compile the reel: the user's video with the generated pictures, captions and watermark.

In the layout, the speaker's video fills the frame, and pictures
float over it as photo cards in the upper part, cut-out characters standing at the bottom,
or cut-out objects in the upper middle. A picture can also fill the screen (a cutaway with a
slow Ken Burns zoom). While a card or cut-out is up, the speaker can be blurred and dimmed
behind it (style "speaker_behind"), fading in and out over half a second. Over the first
seconds a big title can stand behind the speaker: their SAM 3.1 masks (see depth.py) choose
where it stays readable and take its letters out where they are. The word-by-word caption
styles bring each word in as it is said, with the stressed words set apart. A genre theme
(see themes.py) can dress any of it: a grade on the video, the cards' frame, the title, the
studio backdrop, an effect on the stressed words and one touch of its own.

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
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..common import Cancelled, now_iso
from ..files import ProjectFiles
from ..jobs import JobContext, PipelineError
from ..media import ffmpeg as ff
from ..models import Moment, Project, Region, Render, SpeakerMasks, Style
from . import themes
from .captions import build_pages, stressed
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
from .motion import Motion, Renderer, stage_page, swing_page, title_page
from .render import (
    PLAIN_FRAME,
    Frame,
    TitleSprite,
    WordSprite,
    caption_page,
    card,
    cutout_sprite,
    hex_rgb,
    kinetic_page,
    title_sprite,
    watermark,
)
from .title import title_window, title_words

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
# The word-by-word caption styles: text size (of the height), page width (of the width), the words
# and characters a page holds, how long a word takes to come in and how far it rises (of its size).
KINETIC = {
    "bold": {"size": 0.056, "width": 0.84, "words": 4, "chars": 18, "reveal": 0.14, "rise": 0.32},
    "serif": {"size": 0.046, "width": 0.80, "words": 6, "chars": 30, "reveal": 0.2, "rise": 0.12},
}
WORD_LEAD = 0.04  # a word comes in this much before it is said
TITLE_Y = 0.3  # behind the speaker, the title is fitted to them; among equals, nearest this height
TITLE_FRONT_Y = 0.2  # its centre in front of them (or not tracked): above the eyes in most framings
# Where a title behind the speaker may go (top and bottom, of the height): under the platforms'
# top bar and clear of the captions. It is tried on two lines and on one, at every height there.
TITLE_BAND = {"lower": (0.06, 0.5), "middle": (0.06, 0.41)}
TITLE_STEP = 0.005  # of the height
READABLE = 0.7  # the share of the title's letters that must show past the speaker
TITLE_TARGET = 0.85  # the share it aims for: the speaker covers a little of it, not more
TITLE_SMALLEST = 0.035  # of the height: a title this small on one line is not tried
TITLE_SHRINK = (0.75, 0.56)  # then smaller sizes of the one-line title, before it goes in front
TITLE_IN, TITLE_OUT = 0.35, 0.3
TITLE_UNDER = 0.15  # seconds a picture coming in over the title takes to cover it: then it is gone
TITLE_SHORTEST = 1.0  # seconds: a title cut shorter than this by a picture is left out
TITLE_FEATHER = 1.6  # pixels: the soft edge where the speaker covers the title
SWING_MIN = 1.4  # seconds a photo card must be up to swing in through 3D (see motion.py)
CUTOUT_FEATHER = 1.2  # pixels at half size: the soft edge of the cut-out speaker
OUTLINE = (4.0, 3.2, 230)  # the "studio" outline: blur (half-size px), gain, opacity
BEHIND_SEEN = 0.6  # in "studio", a photo card goes behind the speaker when this much of it still shows
# A theme's effect on the stressed words (see themes.py): how long each moves after the word
# comes in, in seconds (its frames are drawn anew meanwhile), and what it leaves behind.
EFFECT_SECONDS = {"pulse": 1.75, "shake": 0.6, "stamp": 0.4, "flash": 0.5, "glow": 0.9}
BEAT = 0.8  # "pulse": a heartbeat's length; there are two
STAMP_TILT = -3.0  # degrees a stamped word stays turned
GLOW = 0.9  # the opacity of the glow a "glow" word keeps
WORD_EDGE = 0.015  # of the width: how close to the frame's sides a word may grow
# A theme's entrance for a card instead of its pop, in seconds: horror's photo cards glitch in,
# legend's characters come in as shadow puppets that fill with colour.
ENTRY_SECONDS = {"glitch": 0.5, "silhouette": 1.2}
PUPPET = (26, 16, 10)  # the shadow puppet's colour
LETTERBOX = 0.05  # drama's bars, top and bottom, of the height


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


def _bump(p: float) -> float:
    """0, up to 1 halfway and back to 0, as `p` goes from 0 to 1 (0 outside)."""
    return math.sin(math.pi * p) if 0.0 <= p <= 1.0 else 0.0


def _ease_back(p: float) -> float:
    """0 to 1, overshooting a little before it settles."""
    p = min(1.0, max(0.0, p)) - 1
    return 1 + 2.7 * p**3 + 1.7 * p**2


def _heartbeat(u: float) -> float:
    """How much bigger a "pulse" word is `u` seconds into its heartbeat: a swell and a smaller
    one (lub-dub), twice."""
    if not 0.0 <= u < 2 * BEAT:
        return 0.0
    u %= BEAT
    return 0.17 * _bump(u / 0.16) + 0.09 * _bump((u - 0.22) / 0.16)


def _transformed(image: Image.Image, scale: float, angle: float = 0.0) -> tuple[Image.Image, int, int]:
    """`image` scaled and turned about its centre, and where its top-left moves to keep it there."""
    out = image
    if abs(scale - 1) > 0.002:
        out = out.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.BILINEAR
        )
    if angle:
        out = out.rotate(angle, resample=Image.BICUBIC, expand=True)
    return out, round((image.width - out.width) / 2), round((image.height - out.height) / 2)


def _room(size: tuple[int, int], left: int, angle: float) -> float:
    """The most an image `size` big, its left edge at `left` on the frame, may be scaled about
    its centre while turned by `angle` degrees and stay WORD_EDGE inside the frame's sides (under
    1 when turning alone would take it out)."""
    width, height = size
    turn = math.radians(abs(angle))
    turned = width * math.cos(turn) + height * math.sin(turn)
    centre = left + width / 2
    half = min(centre, W - centre) - WORD_EDGE * W
    return max(0.5, 2 * half / max(1.0, turned))


@dataclass
class Placed:
    """Where a card or cut-out goes: the sprite (RGBA, shadow included), its centre, and the
    box the picture itself covers (for checking the face)."""

    image: Image.Image
    center: tuple[int, int]
    box: Region


def is_cutout(moment: Moment) -> bool:
    """Whether a moment's picture shows cut out (a cut-out SAM missed shows as a framed card)."""
    return moment.display == "cutout" and moment.asset is not None and moment.asset.cutout


def is_standing(moment: Moment, picture: Image.Image) -> bool:
    """Whether a moment shows as a character standing at the bottom: a tall cut-out. Everything
    else (a card, a cut-out object) goes in the upper part of the frame."""
    return is_cutout(moment) and picture.height >= picture.width * 1.15


def place(moment: Moment, picture: Image.Image, style: Style, frame: Frame = PLAIN_FRAME) -> Placed:
    """A card (in `frame`) or cut-out sprite for `moment`, placed where the layout puts it."""
    position = style.caption_position
    if is_cutout(moment):
        if is_standing(moment, picture):
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
    sprite = card(picture, max_w, max_h, frame)
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


def _minus(spans: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """`spans` with the stretches in `cut` taken out (pieces shorter than BLUR_FADE dropped)."""
    out = list(spans)
    for c0, c1 in cut:
        pieces = []
        for a, b in out:
            pieces += [(a, min(b, c0)), (max(a, c1), b)] if a < c1 and c0 < b else [(a, b)]
        out = [(a, b) for a, b in pieces if b - a >= BLUR_FADE]
    return out


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
class _Kinetic:
    """A caption page of the word-by-word styles: each word comes in (a fade and a small rise)
    as it is said, and stays until the page ends. A theme's `effect` moves the stressed words:
    "pulse" (a heartbeat), "shake", "stamp" (slammed down, left a little turned), "flash" (a
    zoom with a flash of light) or "glow" (a glow of the highlight swells round them)."""

    start: float
    end: float
    xy: tuple[int, int]
    words: list[WordSprite]
    starts: list[float]
    reveal: float
    rise: int
    effect: str = ""
    size: int = 0  # the text size, in pixels: how far an effect moves a word
    accent: tuple[int, int, int] = (255, 255, 255)  # the colour of a "glow"
    _halos: dict[int, Image.Image] = field(default_factory=dict, repr=False)

    def _moving(self, word: WordSprite) -> float:
        """How long a word moves after it comes in: its reveal, or its effect's time."""
        if self.effect and word.stressed:
            return max(self.reveal, EFFECT_SECONDS[self.effect])
        return self.reveal

    def shown(self, t: float) -> int:
        return sum(1 for s in self.starts if s - WORD_LEAD <= t)

    def animating(self, t: float) -> bool:
        return any(
            0.0 <= t - (s - WORD_LEAD) < self._moving(w) for w, s in zip(self.words, self.starts, strict=True)
        )

    def draw(self, canvas: Image.Image, t: float) -> None:
        x, y = self.xy
        for word, start in zip(self.words, self.starts, strict=True):
            since = t - (start - WORD_LEAD)
            if since < 0:
                break
            if self.effect and word.stressed:
                image, dx, dy = self._stressed(word, since, x + word.xy[0])
                _composite(canvas, image, x + word.xy[0] + dx, y + word.xy[1] + dy)
                continue
            alpha = _ease_out(since / self.reveal)
            dy = round((1 - alpha) * self.rise)
            _composite(canvas, _faded(word.image, alpha), x + word.xy[0], y + word.xy[1] + dy)

    def _stressed(self, word: WordSprite, since: float, left: int) -> tuple[Image.Image, int, int]:
        """A stressed word `since` seconds after it comes in, moved by the effect: its image and
        how far that is from the word's place (`left` is its left edge on the frame). Once the
        effect is over, it stays as it ends."""
        alpha = _ease_out(since / self.reveal)
        dx, dy = 0, round((1 - alpha) * self.rise)
        scale, angle, halo = 1.0, 0.0, 0.0
        size = max(1, self.size)
        if self.effect == "pulse":  # in as usual, then its heart beats
            scale = 1 + _heartbeat(since - 0.6 * self.reveal)
        elif self.effect == "shake":  # it comes in trembling, the shake dying away
            fade = max(0.0, 1 - since / EFFECT_SECONDS["shake"])
            dx = round(0.07 * size * fade * math.sin(since * 97))
            dy += round(0.04 * size * fade * math.sin(since * 71 + 1.3))
        elif self.effect == "stamp":  # dropped from above the page, landing with a thud
            p = min(1.0, since / 0.24)
            alpha, dy = min(1.0, since / 0.08), 0
            scale = 1.85 - 0.85 * p * p if p < 1 else 1 - 0.06 * _bump((since - 0.24) / 0.14)
            angle = STAMP_TILT - 9 * (1 - p)
        elif self.effect == "flash":  # it zooms in white-hot, a flash of light round it
            alpha, dy = min(1.0, since / 0.1), 0
            scale = 0.6 + 0.4 * _ease_back(since / 0.3)
            halo = max(0.0, 1 - since / EFFECT_SECONDS["flash"]) ** 1.5
        elif self.effect == "glow":  # a glow of the highlight swells round it and stays
            halo = GLOW * _smooth(since / EFFECT_SECONDS["glow"])
        if scale > 1 or angle:  # a word growing or turned about its centre stays inside the frame
            scale = min(scale, _room(word.image.size, left, angle))
        image = self._halo(word, halo) if halo > 0.004 else word.image
        image = _faded(image, alpha)
        if abs(scale - 1) > 0.002 or angle:
            image, ox, oy = _transformed(image, scale, angle)
            dx, dy = dx + ox, dy + oy
        return image, dx, dy

    def _halo(self, word: WordSprite, strength: float) -> Image.Image:
        """The word over a soft light of its own shape at `strength`: the highlight for a
        "glow"; white for a "flash", the word itself white-hot with it."""
        light = self._halos.get(id(word))
        if light is None:
            letters = word.image.getchannel("A").point(lambda v: max(0, v - 110) * 255 // 145)
            soft = letters.filter(ImageFilter.GaussianBlur(max(2, self.size * 0.12)))
            color = (255, 255, 255) if self.effect == "flash" else self.accent
            light = Image.new("RGBA", word.image.size, (*color, 255))
            light.putalpha(soft.point(lambda v: min(255, v * 2)))
            self._halos[id(word)] = light
        out = _faded(light, strength) if strength < 0.999 else light.copy()
        ink = word.image
        if self.effect == "flash":
            white = Image.new("RGBA", ink.size, (255, 255, 255, 255))
            white.putalpha(ink.getchannel("A"))
            ink = Image.blend(ink, white, 0.85 * strength)
        out.alpha_composite(ink)
        return out


@dataclass
class _Title:
    """The reel's title over its first seconds. With the speaker's masks (SAM 3.1, frame by
    frame) its pixels where the speaker is are taken out, so they stand in front of it. With an
    `intro` (HyperFrames: its letters rising in one by one) the title is drawn from those frames,
    the last one held."""

    start: float
    end: float
    sprite: Image.Image  # the title, cropped to its box
    box: tuple[int, int, int, int]  # where that box is on the frame
    masks: np.ndarray | None = None  # frames x h x w booleans, at `fps` from `mask_start`
    mask_start: float = 0.0
    fps: float = 24.0
    still: TitleSprite | None = None  # how it was set (for HyperFrames to set it the same way)
    intro: Motion | None = None

    def alpha(self, t: float) -> float:
        if self.intro is not None:  # its letters come in by themselves
            return max(0.0, min((self.end - t) / TITLE_OUT, 1.0))
        return max(0.0, min(_ease_out((t - self.start) / TITLE_IN), (self.end - t) / TITLE_OUT, 1.0))

    def draw(self, canvas: Image.Image, t: float, behind: bool) -> None:
        alpha = self.alpha(t)
        if alpha <= 0.0:
            return
        x0, y0, x1, y1 = self.box
        sprite = self.sprite
        grow = _ease_out((t - self.start) / TITLE_IN)
        if self.intro is not None:
            sprite = self.intro.at(t - self.start)
        elif grow < 0.999:  # comes in a little smaller, about its centre
            scale = 0.94 + 0.06 * grow
            size = (round(sprite.width * scale), round(sprite.height * scale))
            small = sprite.resize(size, Image.BILINEAR)
            sprite = Image.new("RGBA", self.sprite.size, (0, 0, 0, 0))
            sprite.alpha_composite(small, ((sprite.width - size[0]) // 2, (sprite.height - size[1]) // 2))
        if behind and self.masks is not None and len(self.masks):
            k = min(max(round((t - self.mask_start) * self.fps), 0), len(self.masks) - 1)
            mask = self.masks[k]
            sx, sy = mask.shape[1] / W, mask.shape[0] / H
            top, left = int(y0 * sy), int(x0 * sx)
            region = mask[top : max(top + 1, round(y1 * sy)), left : max(left + 1, round(x1 * sx))]
            person = Image.fromarray(region.astype(np.uint8) * 255).resize(sprite.size, Image.BILINEAR)
            person = person.filter(ImageFilter.GaussianBlur(TITLE_FEATHER))
            keep = 255 - np.asarray(person, dtype=np.uint16)
            ink = np.asarray(sprite.getchannel("A"), dtype=np.uint16)
            sprite = sprite.copy()
            sprite.putalpha(Image.fromarray((ink * keep // 255).astype(np.uint8)))
        _composite(canvas, _faded(sprite, alpha), x0, y0)


Box = tuple[float, float, float, float]  # x0, y0, x1, y1 on the frame


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def fit_title(
    text: str, cover: np.ndarray, band: tuple[float, float], avoid: tuple[Box, ...] = (), **look: Any
) -> tuple[TitleSprite, int, float]:
    """Where the title goes behind the speaker. `cover` is how often each pixel is the speaker
    over the title's time (the masks' mean, at their size). The title is tried on two lines, on
    one, and smaller on one, at every height in `band` where it meets none of the `avoid` boxes;
    the biggest that stays readable (READABLE of its letters showing) wins, at the height where
    the share showing is nearest TITLE_TARGET (then nearest TITLE_Y). Returns the title, its top
    and the share showing; when no height is readable, its place in front (see below). `look`
    sets its ink, face and glow (see render.title_sprite)."""
    sy, sx = cover.shape[0] / H, cover.shape[1] / W
    two = title_sprite(text, W, H, 2, **look)
    layouts = [two]
    one = title_sprite(text, W, H, 1, **look) if two.lines == 2 else two
    if one is not two and one.size >= TITLE_SMALLEST * H:
        layouts.append(one)
    for shrink in TITLE_SHRINK:
        size = round(one.size * shrink)
        if size >= TITLE_SMALLEST * H:
            layouts.append(title_sprite(text, W, H, 1, max_size=size, **look))
    tried: list[tuple[int, float, int, TitleSprite]] = []
    for rank, sprite in enumerate(layouts):
        w, h = max(1, round(sprite.image.width * sx)), max(1, round(sprite.image.height * sy))
        ink = np.asarray(sprite.letters.resize((w, h), Image.BILINEAR), dtype=np.float32) / 255
        x0 = round(sprite.x * sx)
        top, bottom = round(band[0] * H), round(band[1] * H) - sprite.image.height
        for y in range(top, max(top, bottom) + 1, max(1, round(TITLE_STEP * H))):
            box = (sprite.x, y, sprite.x + sprite.image.width, y + sprite.image.height)
            if any(_overlap(box, other) for other in avoid):
                continue
            region = cover[round(y * sy) : round(y * sy) + h, x0 : x0 + w]
            part = ink[: region.shape[0], : region.shape[1]]
            showing = float((part * (1 - region)).sum()) / max(1e-6, float(part.sum()))
            tried.append((rank, showing, y, sprite))
    if not tried:  # the badge, a card or the watermark is everywhere it could go: go under them
        return fit_title(text, cover, band, **look)
    readable = [t for t in tried if t[1] >= READABLE]
    if not readable:
        # Nowhere readable: the title goes in front of the speaker, as high as it can (over
        # their hair rather than their eyes), on one line when it has one. The share returned
        # is the most that would have shown behind them.
        sprite = layouts[1] if len(layouts) > 1 else layouts[0]
        top = min(t[2] for t in tried if t[3] is sprite)
        return sprite, top, max(t[1] for t in tried)
    rank = min(t[0] for t in readable)
    best = min(
        (t for t in readable if t[0] == rank),
        key=lambda t: (
            round(abs(t[1] - TITLE_TARGET), 2),
            abs(t[2] + t[3].image.height / 2 - TITLE_Y * H),
        ),
    )
    return best[3], best[2], best[1]


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
class _Pan:
    """A wide picture filling the screen behind the cut-out speaker, panning slowly across it so
    its whole width is seen (a full-screen picture of a card, in the "scene" background)."""

    start: float
    end: float
    source: Image.Image  # RGB, the frame's height (and a little more), wider than the frame
    rightward: bool

    def frame(self, t: float) -> Image.Image:
        progress = _smooth((t - self.start) / max(0.01, self.end - self.start))
        travel = self.source.width - W
        x = round(travel * (progress if self.rightward else 1 - progress))
        y = (self.source.height - H) // 2
        frame = self.source.crop((x, y, x + W, y + H)).convert("RGBA")
        alpha = min(1.0, (t - self.start) / CUT_FADE, (self.end - t) / CUT_FADE)
        return _faded(frame, max(0.0, alpha))


def scene_of(picture: Image.Image, start: float, end: float, index: int) -> _Cutaway | _Pan:
    """A picture as the backdrop behind the speaker: a slow zoom when it is tall enough for the
    frame, a slow pan across it when it is wide."""
    picture = picture.convert("RGB")
    if picture.width / picture.height <= W / H * 1.15:
        size = (round(W * (1 + ZOOM)), round(H * (1 + ZOOM)))
        return _Cutaway(start, end, ImageOps.fit(picture, size, Image.LANCZOS), zoom_in=index % 2 == 0)
    height = round(H * 1.02)
    width = max(W + 2, round(picture.width * height / picture.height))
    return _Pan(start, end, picture.resize((width, height), Image.LANCZOS), rightward=index % 2 == 0)


@dataclass(frozen=True)
class Placement:
    """Where the speaker's video goes in a cut-out look (see Style.speaker_scale): scaled to
    `width` x `height` (even, for the encoder), its top-left corner at (`x`, `y`) on the frame.
    The encoder moves the video and the cut-out moves its masks by this same placement."""

    width: int = W
    height: int = H
    x: int = 0
    y: int = 0

    @property
    def identity(self) -> bool:
        return (self.width, self.height, self.x, self.y) == (W, H, 0, 0)

    @property
    def scale(self) -> float:
        return self.width / W

    def move(self, mask: np.ndarray) -> np.ndarray:
        """A mask of the whole frame as recorded (float 0..1, any size), as the video is placed."""
        if self.identity:
            return mask
        mh, mw = mask.shape
        sx, sy = mw / W, mh / H
        size = (max(1, round(self.width * sx)), max(1, round(self.height * sy)))
        image = Image.fromarray((mask * 255).astype(np.uint8)).resize(size, Image.BILINEAR)
        out = Image.new("L", (mw, mh), 0)
        out.paste(image, (round(self.x * sx), round(self.y * sy)))
        return np.asarray(out, dtype=np.float32) / 255

    def box(self, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """A box of the frame as recorded (fractions), where the placement puts it."""
        s, dx, dy = self.scale, self.x / W, self.y / H
        return (dx + box[0] * s, dy + box[1] * s, dx + box[2] * s, dy + box[3] * s)


def placement(style: Style) -> Placement:
    """The speaker's placement from the style: scaled about the bottom middle of the video."""
    s = style.speaker_scale
    width, height = 2 * round(W * s / 2), 2 * round(H * s / 2)
    return Placement(
        width, height, round(style.speaker_x * W - width / 2), round(style.speaker_y * H - height)
    )


def speaker_place(project: Project) -> Placement:
    """Where the speaker's video goes: the style's placement in a cut-out look (with the speaker
    tracked), else as recorded."""
    track = project.speaker_track
    if project.style.background == "dalang" or track is None or not track.key:
        return Placement()
    return placement(project.style)


def moved_faces(place: Placement, faces: list[Region] | None) -> list[Region] | None:
    """Face boxes found in the recording, where the placement puts them."""
    if faces is None or place.identity:
        return faces
    return [
        Region(**dict(zip(("x0", "y0", "x1", "y1"), place.box((f.x0, f.y0, f.x1, f.y1)), strict=True)))
        for f in faces
    ]


def speaker_side(project: Project) -> str | None:
    """The side of the frame a moved cut-out speaker stands on ("left" or "right"), or None
    when they are in the middle or not cut out (their own video, as recorded)."""
    if speaker_place(project).identity:
        return None
    x = project.style.speaker_x
    return "left" if x < 0.4 else "right" if x > 0.6 else None


def on_screen(place: Placement, box: tuple[float, float, float, float]) -> dict[str, float]:
    """Where the speaker is after the placement (fractions of the frame), and the share of them
    inside it, for the editing agent."""
    x0, y0, x1, y1 = place.box(box)
    inside = max(0.0, min(x1, 1.0) - max(x0, 0.0)) * max(0.0, min(y1, 1.0) - max(y0, 0.0))
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    return {
        "left": round(x0, 3),
        "top": round(y0, 3),
        "right": round(x1, 3),
        "bottom": round(y1, 3),
        "height_share": round(min(y1, 1.0) - max(y0, 0.0), 3),
        "inside_share": round(inside / area, 3),
    }


@dataclass
class _Track:
    """The speaker in every frame of the reel (SAM 3.1 masks at `fps`, packed bits at half the
    reel's size), eased from one mask to the next so the cut-out moves at the reel's rate."""

    packed: np.ndarray  # frames x bytes
    fps: float
    width: int
    height: int
    place: Placement = field(default_factory=Placement)  # where the speaker's video is put
    _half: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    def _mask(self, k: int) -> np.ndarray:
        k = min(max(k, 0), len(self.packed) - 1)
        mask = self._half.get(k)
        if mask is None:
            bits = np.unpackbits(self.packed[k])[: self.width * self.height]
            mask = self.place.move(bits.reshape(self.height, self.width).astype(np.float32))
            if len(self._half) > 6:  # frames are read in order: keep only the latest few
                self._half.pop(min(self._half))
            self._half[k] = mask
        return mask

    def half(self, t: float) -> Image.Image:
        """The speaker at `t` (L, half size, soft-edged)."""
        position = max(0.0, t * self.fps)
        k = int(position)
        f = position - k
        mask = self._mask(k) if f < 0.05 else (1 - f) * self._mask(k) + f * self._mask(k + 1)
        image = Image.fromarray((mask * 255).astype(np.uint8))
        return image.filter(ImageFilter.GaussianBlur(CUTOUT_FEATHER))

    def visible(self, start: float, end: float, box: tuple[float, float, float, float]) -> float:
        """The share of `box` (frame pixels) the speaker leaves uncovered from `start` to `end`."""
        masks, _ = self.window(start, end)
        sx, sy = self.width / W, self.height / H
        x0, y0 = max(0, int(box[0] * sx)), max(0, int(box[1] * sy))
        x1, y1 = min(self.width, int(np.ceil(box[2] * sx))), min(self.height, int(np.ceil(box[3] * sy)))
        if x1 <= x0 or y1 <= y0:
            return 1.0
        return 1.0 - float(masks[:, y0:y1, x0:x1].mean())

    def window(self, start: float, end: float) -> tuple[np.ndarray, float]:
        """The masks from `start` to `end` as booleans (for the title), and the first one's time."""
        first = int(start * self.fps)
        last = min(len(self.packed), int(np.ceil(end * self.fps)) + 1)
        masks = np.stack([self._mask(k) > 0.5 for k in range(first, max(first + 1, last))])
        return masks, first / self.fps


def studio_backdrop(t: float, color: str) -> Image.Image:
    """The "studio" background: a dark ground with two soft glows of the highlight colour that
    drift slowly, drawn at a quarter of the frame and scaled up (it is all soft)."""
    w, h = W // 4, H // 4
    accent = np.array(hex_rgb(color), dtype=np.float32)
    ground = np.array((10, 10, 16), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = np.broadcast_to(ground, (h, w, 3)).copy()
    for (cx, cy, r, strength), (ax, ay, px, py) in (
        ((0.5, 0.3, 0.75, 0.62), (0.16, 0.05, 13.0, 11.0)),
        ((0.5, 0.86, 0.6, 0.38), (0.22, 0.04, 17.0, 9.0)),
    ):
        x = (cx + ax * np.sin(2 * np.pi * t / px)) * w
        y = (cy + ay * np.cos(2 * np.pi * t / py)) * h
        d2 = ((xx - x) ** 2 + (yy - y) ** 2) / (r * w) ** 2
        glow = (strength * np.exp(-2.2 * d2))[..., None]
        out = out * (1 - glow) + accent * glow
    small = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    return small.resize((W, H), Image.BILINEAR)


@dataclass
class _Card:
    """A card or cut-out: pops in (fade and a small rise), fades out. With `animate` off it is
    simply there for its time; with `enter` off it is there from its first frame (the part badge,
    which the platforms' cover frame must show) and still fades out when it leaves. One that
    replaces another in the same place comes in without the rise (`rise` off): a dissolve.
    With an `intro` (HyperFrames frames, see motion.py) those frames are its entrance instead;
    with an `entry` a theme's: "glitch" (torn bands and split colours, settling) or "silhouette"
    (a shadow puppet that fills with colour)."""

    start: float
    end: float
    image: Image.Image  # RGBA
    center: tuple[int, int]
    ident: int = field(default=0)
    animate: bool = True
    enter: bool = True
    rise: bool = True
    fade: float = FADE_OUT  # seconds it takes to go, at the end of its time
    # "photo" for a picture card (it may swing in through 3D), "character" for one standing at
    # the bottom; a part's end screen
    kind: str = ""
    group: str = ""  # its pieces: "titles", "picture", "pill", in the group "cta"
    intro: Motion | None = None
    picture: Image.Image | None = None  # a photo card's picture itself (a "scene" backdrop)
    entry: str = ""
    _puppet: Image.Image | None = field(default=None, repr=False)

    @property
    def entrance(self) -> float:
        if self.intro is not None:
            return self.intro.duration
        return ENTRY_SECONDS.get(self.entry, POP_IN)

    def _introducing(self, t: float) -> bool:
        return self.intro is not None and t - self.start < self.intro.duration

    def animating(self, t: float) -> bool:
        if self._introducing(t):
            return True
        entering = self.enter and self.intro is None and t - self.start < self.entrance
        return self.animate and (entering or self.end - t < self.fade)

    def draw(self, canvas: Image.Image, t: float) -> None:
        if self.intro is not None and self._introducing(t):
            _composite(canvas, self.intro.at(t - self.start), *self.intro.xy)
            return
        alpha, rise, image = 1.0, 0.0, self.image
        entering = self.animate and self.enter and self.intro is None and t - self.start < self.entrance
        if entering and self.entry:
            image = self._entering(t - self.start)
        elif entering:
            alpha = _ease_out((t - self.start) / POP_IN)
            if self.rise:
                rise = (1 - alpha) * 0.02 * H
        elif self.animate and self.end - t < self.fade:
            alpha = max(0.0, (self.end - t) / self.fade)
        image = _faded(image, alpha)
        x = round(self.center[0] - image.width / 2)
        y = round(self.center[1] - image.height / 2 + rise)
        _composite(canvas, image, x, y)

    def _entering(self, since: float) -> Image.Image:
        """The sprite `since` seconds into its theme entrance (the same size as the sprite)."""
        if self.entry == "glitch":
            return _glitch(self.image, since, self.ident)
        if self._puppet is None:  # its shadow on the screen, in the shape of the sprite
            self._puppet = Image.new("RGBA", self.image.size, (*PUPPET, 255))
            self._puppet.putalpha(self.image.getchannel("A"))
        filled = _smooth((since - 0.3) / (ENTRY_SECONDS["silhouette"] - 0.3))
        image = Image.blend(self._puppet, self.image, filled) if filled > 0 else self._puppet
        return _faded(image, _ease_out(since / 0.3))


def _glitch(image: Image.Image, since: float, seed: int) -> Image.Image:
    """A card glitching in: bands of it torn sideways, its red and blue pulled apart, flickering,
    calming down as it comes in (the same frames every render)."""
    calm = max(0.0, 1 - since / ENTRY_SECONDS["glitch"])
    rng = np.random.default_rng(seed * 7919 + int(since * 30))
    pixels = np.array(image.convert("RGBA"))
    height, width = pixels.shape[:2]
    split = round(width * 0.025 * calm)
    if split:
        pixels[..., 0] = np.roll(pixels[..., 0], split, axis=1)
        pixels[..., 2] = np.roll(pixels[..., 2], -split, axis=1)
    for _ in range(int(rng.integers(2, 6))):
        top = int(rng.integers(0, height))
        band = int(rng.integers(height // 40 + 1, height // 8 + 2))
        shift = round(float(rng.uniform(-1, 1)) * width * 0.07 * calm)
        pixels[top : top + band] = np.roll(pixels[top : top + band], shift, axis=1)
    flicker = 0.35 if rng.random() < 0.4 * calm else 1.0
    return _faded(Image.fromarray(pixels, "RGBA"), min(1.0, since / 0.12) * flicker)


CUT_EPS = 0.02  # seconds: a picture ending this close to another's start is cut to it
COVERS = 0.3  # a new card over this much of an old one (of the smaller of the two) replaces it there
SOLID = 0.9  # a sprite this opaque (its share of its box) is a card; less, a cut-out with gaps


def _box(card: _Card) -> tuple[float, float, float, float]:
    w, h = card.image.width, card.image.height
    return card.center[0] - w / 2, card.center[1] - h / 2, card.center[0] + w / 2, card.center[1] + h / 2


def _top_left(card: _Card) -> tuple[int, int]:
    """Where a card's sprite goes on the frame, as _Card.draw puts it."""
    return round(card.center[0] - card.image.width / 2), round(card.center[1] - card.image.height / 2)


def _load_track(project: Project, files: ProjectFiles) -> _Track | None:
    """The speaker's masks for the whole reel, when a cut-out background has them."""
    stored = project.speaker_track
    if project.style.background == "dalang" or stored is None or not files.exists(stored.key):
        return None
    with np.load(files.path(stored.key)) as data:
        packed = data["masks"]
    return (
        _Track(packed, stored.fps, stored.width, stored.height, speaker_place(project))
        if len(packed)
        else None
    )


def _covers(a: _Card, b: _Card) -> bool:
    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    return smaller > 0 and inter >= COVERS * smaller


def _solid(image: Image.Image) -> bool:
    """Whether a sprite is a solid card (a picture in a frame) rather than a cut-out figure,
    whose gaps show what is under it."""
    if image.mode != "RGBA":
        return True
    alpha = image.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    box = alpha.getbbox()
    if box is None:
        return False
    counts = alpha.crop(box).histogram()
    return counts[255] >= SOLID * sum(counts)


def join_cuts(cards: list[_Card], cutaways: list[_Cutaway]) -> None:
    """Cuts with no empty frame between two pictures, dissolved the way an editor would.

    A card that replaces another in the same place comes in on top of it without the rise. Under
    a solid card the old picture stays whole until the new one is in, then fades out, so only
    what the new card leaves uncovered is seen to go; under a cut-out, whose gaps would show the
    old picture doubled, the two cross-fade. A full-screen picture stays until whatever follows
    it is in, the same way. A picture that nothing replaces fades out just after its time instead
    of just before it, so it never leaves while its words are still being said."""
    plan: list[tuple[_Card, list[_Card]]] = []
    for a in cards:
        if a.animate:
            nxt = [
                b
                for b in cards
                if b is not a and b.animate and abs(b.start - a.end) < CUT_EPS and _covers(a, b)
            ]
            plan.append((a, nxt))
    for a, nxt in plan:  # (only the ends change, so the plan made first stays right)
        for b in nxt:
            b.rise = False
        entrance = max((b.entrance for b in nxt), default=POP_IN)  # under the new card until it is in
        if not nxt:
            a.end += a.fade
        elif all(_solid(b.image) for b in nxt):
            a.end += entrance + a.fade
        else:
            a.end += entrance
            a.fade = entrance
    for c in cutaways:
        cut = c.end
        if any(d is not c and abs(d.start - cut) < CUT_EPS for d in cutaways):
            c.end += 2 * CUT_FADE  # the next one fades in on top: stay whole under it, then go
            continue
        after = [b for b in cards if b.animate and abs(b.start - cut) < CUT_EPS]
        for b in after:
            b.rise = False
        c.end += POP_IN + CUT_FADE if after else CUT_FADE


class Compositor:
    """Builds every overlay element up front, then yields the layer frame by frame. `genre` is a
    novel part's (its theme on "auto", see themes.py)."""

    def __init__(
        self, project: Project, files: ProjectFiles, motion: Renderer | None = None, genre: str | None = None
    ) -> None:
        if project.source is None:
            raise PipelineError("process the clips before rendering")
        self.duration = project.source.duration
        fps = project.source.fps
        self.overlay_fps = fps if fps <= OVERLAY_FPS_MAX else fps // 2
        # A genre theme dresses the look: it fills in the caption style and highlight where the
        # user kept the defaults, and the rest of what it changes is set below.
        theme = self.theme = themes.resolve(project, genre)
        style = theme.dress(project.style) if theme is not None else project.style
        self.theme_note = themes.describe(theme, project, genre)
        self.captions = style.captions
        self.card_frame = theme.frame if theme is not None else PLAIN_FRAME  # the photo cards'
        self.grade = theme.grade if theme is not None else ""  # on the speaker's video (see encode)
        self.title_look: dict[str, Any] = theme.title if theme is not None else {}
        self.extras = theme.extras if theme is not None else frozenset()
        self.pages: list[_Page] = []
        self.kinetic: list[_Kinetic] = []
        if style.captions in KINETIC and project.transcript is not None:
            spec = KINETIC[style.captions]
            size = round(H * spec["size"])
            center_y = CAPTION_CENTER[style.caption_position] * H
            pages = build_pages(
                project.transcript.turns, style.caption_case, spec["words"], spec["chars"], clauses=True
            )
            flags = stressed(pages, project.transcript.emphasis_picked)
            for page, stress in zip(pages, flags, strict=True):
                kinetic = kinetic_page(
                    [w.text for w in page.words],
                    stress,
                    style.captions,
                    size,
                    round(W * spec["width"]),
                    style.caption_color,
                )
                # The first line sits where a one-line page does; a second goes under it, so a long
                # page never climbs into what is above the captions (a part's end screen).
                xy = (round(W / 2 - kinetic.width / 2), round(center_y - kinetic.anchor))
                self.kinetic.append(
                    _Kinetic(
                        page.start,
                        page.end,
                        xy,
                        kinetic.words,
                        [w.start for w in page.words],
                        spec["reveal"],
                        round(spec["rise"] * size),
                        effect=theme.word if theme is not None else "",
                        size=size,
                        accent=hex_rgb(style.caption_color),
                    )
                )
        elif style.captions != "off" and project.transcript is not None:
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
        self.cutaways: list[_Cutaway | _Pan] = []
        self.cards: list[_Card] = []
        self.unchecked_faces = 0  # "auto" blur without face boxes: blurred to be safe
        self.blurs = blur_windows(self._build_pictures(project, files), self.duration)
        # A cut-out background, when SAM found the speaker all through (else their own video).
        self.track = _load_track(project, files)
        self.background = style.background if self.track is not None else "dalang"
        self.accent = style.caption_color
        self.background_note = ""
        if style.background != "dalang" and self.track is None:
            self.background_note = (
                "the speaker is not cut out for this reel yet (process it, or render with your key),"
                " so they keep their own background"
            )
        # Moved or resized (cut out only), the speaker always has a backdrop behind them: the
        # pictures, and between them the studio's glow (their own video is not where they are).
        self.place = self.track.place if self.track is not None else Placement()
        self.moved = not self.place.identity
        self.backdrop = self.background == "studio" or (self.background == "scene" and self.moved)
        if self.background == "scene":  # each photo card becomes the scene behind them
            keep = []
            for item in self.cards:
                if item.kind == "photo" and item.picture is not None:
                    self.cutaways.append(scene_of(item.picture, item.start, item.end, len(self.cutaways)))
                else:
                    keep.append(item)
            self.cards = keep
            self.cutaways.sort(key=lambda c: c.start)
        self.behind: set[int] = set()  # ids of the photo cards drawn behind the cut-out speaker
        if self.background == "studio" and self.track is not None:
            for item in self.cards:
                if (
                    item.kind == "photo"
                    and self.track.visible(item.start, item.end, _box(item)) >= BEHIND_SEEN
                ):
                    self.behind.add(id(item))
        if self.background != "dalang":  # no blur while a picture is behind them, only over them
            clear = [(c.start, c.end) for c in self.cutaways] if self.background == "scene" else []
            clear += [(c.start, c.end) for c in self.cards if id(c) in self.behind]
            over = [(c.start, c.end) for c in self.cards if c.kind == "photo" and id(c) not in self.behind]
            self.blurs = _minus(self.blurs, _minus(clear, over))
        for item in self.cards:  # a theme's entrances, in place of the pop (and of the 3D swing)
            if not item.animate or not item.enter or item.group:
                continue
            if item.kind == "photo" and "glitch" in self.extras:
                item.entry = "glitch"
            elif item.kind == "character" and "silhouette" in self.extras:
                item.entry = "silhouette"
        self.letterbox = "letterbox" in self.extras
        self.mark: tuple[Image.Image, tuple[int, int]] | None = None
        if style.watermark:
            image = watermark(style.watermark, round(H * WATERMARK_SIZE), round(W * 0.8))
            y = WATERMARK_Y[style.watermark_position] * H
            self.mark = (image, (round(W / 2 - image.width / 2), round(y - image.height / 2)))
        self.title_note = ""
        self.title_showing: float | None = None  # the share of the title showing past the speaker
        self.title = self._build_title(project, files)
        if style.motion == "plain":
            self.motion_note = "plain (chosen in the style)"
        elif motion is None or not motion.available:
            self.motion_note = "plain (HyperFrames is not installed)"
        else:
            self.motion_note = ""
            self._add_motion(motion)
        join_cuts(self.cards, self.cutaways)

    def _add_motion(self, motion: Renderer) -> None:
        """HyperFrames entrances (see motion.py) for the title, the photo cards and a part's end
        screen, rendered side by side; whatever does not render comes in the plain way. A card
        with a theme's entrance keeps it (horror's photo cards glitch in instead of swinging)."""
        fps = self.overlay_fps
        pages = []
        if self.title is not None and self.title.still is not None:
            pages.append(title_page(self.title.still))
        swinging = [
            c
            for c in self.cards
            if c.kind == "photo" and c.animate and c.enter and not c.entry and c.end - c.start >= SWING_MIN
        ]
        sheet: list[Image.Image] = []
        for item in swinging:
            if all(item.image is not other for other in sheet):
                sheet.append(item.image)
        slot = 0
        if sheet:
            cards_page, slot = swing_page(sheet, fps)
            pages.append(cards_page)
        end = [c for c in self.cards if c.group == "cta"]
        at = (0, 0)
        if end:
            layers = [(c.image, _top_left(c)) for c in end]
            end_page, at = stage_page(layers, [c.kind for c in end])
            pages.append(end_page)
        if not pages:
            return
        frames = motion.render(pages, fps)
        rate = max(1, round(fps))
        done = []
        if self.title is not None and frames.get("title"):
            self.title.intro = Motion(frames["title"], rate, self.title.box[:2])
            done.append("title")
        sheet_frames = frames.get("cards")
        if sheet_frames and sheet:
            with Image.open(sheet_frames[0]) as first:
                sheet_w, sheet_h = first.size
            swung = 0
            for item in swinging:
                k = next(i for i, image in enumerate(sheet) if image is item.image)
                own = sheet_frames[k * slot : (k + 1) * slot]
                if not own:
                    continue
                x, y = _top_left(item)
                xy = (x - (sheet_w - item.image.width) // 2, y - (sheet_h - item.image.height) // 2)
                item.intro = Motion(own, rate, xy)
                swung += 1
            done.append(f"{swung} card(s)")
        if frames.get("end") and end:
            stage = Motion(frames["end"], rate, at)
            start = min(c.start for c in end)
            blank = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            self.cards.append(
                _Card(start, start + stage.duration, blank, (0, 0), ident=0, animate=False, intro=stage)
            )
            for c in end:  # the still pieces take over from its last frame, exactly where it left them
                c.start, c.enter = start + stage.duration, False
            done.append("end screen")
        self.motion_note = f"HyperFrames ({', '.join(done)})" if done else "plain (HyperFrames failed)"

    def _build_title(self, project: Project, files: ProjectFiles) -> _Title | None:
        """The title over the first seconds. Behind the speaker, it goes where their masks
        leave it readable; with no masks, or no such place, it is drawn in front of them."""
        window = title_window(project)
        if window is None:
            return None
        start, end = window
        text = title_words(project)
        style = project.style
        stored = project.speaker_masks
        masks = None
        if style.title_style == "behind":
            if self.track is not None:  # the speaker is cut out all through: those masks serve
                window_masks, mask_start = self.track.window(start, end)
                masks = window_masks
                stored = SpeakerMasks(
                    key="track", start=mask_start, fps=self.track.fps, frames=len(window_masks),
                    width=self.track.width, height=self.track.height, digest="",
                )  # fmt: skip
            elif stored is not None and not stored.key and abs(stored.start - start) <= 0.01:
                self.title_note = "SAM found no speaker while the title is up, so it is drawn in front"
            elif stored is None or not files.exists(stored.key) or abs(stored.start - start) > 0.01:
                self.title_note = (
                    "the speaker is not tracked for this title yet, so it is drawn in front of them"
                )
            else:
                with np.load(files.path(stored.key)) as data:
                    masks = data["masks"]
        if stored is None or masks is None or not len(masks):
            sprite = title_sprite(text, W, H, 2, **self.title_look)
            top = round(TITLE_FRONT_Y * H - sprite.image.height / 2)
            box = (sprite.x, top, sprite.x + sprite.image.width, top + sprite.image.height)
            return self._until_covered(_Title(start, end, sprite.image, box, still=sprite))
        band = TITLE_BAND.get(style.caption_position, TITLE_BAND["lower"])
        # Out of the way of what is there from the start (a part's badge, the watermark); a
        # picture that comes in later ends the title instead (see _until_covered).
        avoid = [_box(c) for c in self.cards if c.start <= start + 0.05 and start < c.end]
        if self.mark is not None:
            image, (x, y) = self.mark
            avoid.append((x, y, x + image.width, y + image.height))
        cover = masks.mean(axis=0, dtype=np.float32)
        sprite, top, showing = fit_title(text, cover, band, tuple(avoid), **self.title_look)
        box = (sprite.x, top, sprite.x + sprite.image.width, top + sprite.image.height)
        title = _Title(start, end, sprite.image, box, still=sprite)
        self.title_showing = showing
        if showing < READABLE:
            self.title_note = (
                f"the speaker fills the frame (only {showing:.0%} of the title would show behind them),"
                " so it is drawn in front of them, as high as it goes"
            )
            return self._until_covered(title)
        title.masks, title.mask_start, title.fps = masks, stored.start, stored.fps
        return self._until_covered(title)

    def _until_covered(self, title: _Title) -> _Title | None:
        """The title, ending as the first picture that comes in over it does (or none, when that
        leaves it too short to read)."""
        later = [c for c in self.cards if title.start < c.start < title.end and _overlap(_box(c), title.box)]
        if not later:
            return title
        title.end = min(c.start for c in later) + TITLE_UNDER
        if title.end - title.start < TITLE_SHORTEST:
            self.title_note = "a picture comes in over the title too soon, so the reel has no title"
            return None
        return title

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
            if "desaturate" in self.extras:
                picture = themes.desaturate(picture)
            if moment.display == "cutaway":
                size = (round(W * (1 + ZOOM)), round(H * (1 + ZOOM)))
                source = ImageOps.fit(picture.convert("RGB"), size, Image.LANCZOS)
                self.cutaways.append(_Cutaway(start, end, source, zoom_in=len(self.cutaways) % 2 == 0))
                continue
            placed = place(moment, picture, style, self.card_frame)
            kind = "photo"  # a card; a cut-out standing at the bottom is a character
            if is_cutout(moment):
                kind = "character" if is_standing(moment, picture) else ""
            self.cards.append(
                _Card(
                    start, end, placed.image, placed.center, ident=len(self.cards) + 1, kind=kind,
                    picture=picture if kind == "photo" else None,
                )
            )  # fmt: skip
            blur = style.speaker_behind == "blur" or (
                style.speaker_behind == "top" and not is_standing(moment, picture)
            )
            if style.speaker_behind == "auto":
                hit = covered(placed.box, moved_faces(speaker_place(project), moment.faces))
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

    def _kinetic_at(self, t: float) -> int | None:
        for index, page in enumerate(self.kinetic):
            if page.start - WORD_LEAD <= t < page.end:
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
        if self.backdrop:  # a theme's own, or the studio's glow
            theme = self.theme
            ground = theme.backdrop(t, self.accent) if theme is not None else studio_backdrop(t, self.accent)
            canvas.paste(ground, (0, 0))
        cuts = sorted((c for c in self.cutaways if c.start <= t < c.end), key=lambda c: c.start)
        for k, cut in enumerate(cuts):  # two at a cut: the next one fades in over the last
            if k == 0 and not self.backdrop:
                canvas.paste(cut.frame(t), (0, 0))
            else:
                _composite(canvas, cut.frame(t), 0, 0)
        cutout = self.track is not None and (self.backdrop or bool(cuts))
        if self.title is not None and self.title.start <= t < self.title.end:
            self.title.draw(canvas, t, behind=cutout or not cuts)  # over a full-screen picture: in front
        front = self.cards
        if cutout:
            behind = [c for c in self.cards if id(c) in self.behind]
            for item in behind:  # the pictures behind the speaker
                if item.start <= t < item.end:
                    item.draw(canvas, t)
            self._cut_out(canvas, t)
            drawn = {id(c) for c in behind}
            front = [c for c in self.cards if id(c) not in drawn]
        if self.letterbox:  # over the speaker, under the pictures, the badge and the captions
            bar = round(LETTERBOX * H)
            canvas.paste((0, 0, 0, 255), (0, 0, W, bar))
            canvas.paste((0, 0, 0, 255), (0, H - bar, W, H))
        for item in front:
            if item.start <= t < item.end:
                item.draw(canvas, t)
        index = self._page_at(t)
        if index is not None:
            page = self.pages[index]
            _composite(canvas, page.image, *page.xy)
            if page.marks:
                mark, (dx, dy) = page.marks[page.word_at(t)]
                _composite(canvas, mark, page.xy[0] + dx, page.xy[1] + dy)
        kinetic = self._kinetic_at(t)
        if kinetic is not None:
            self.kinetic[kinetic].draw(canvas, t)
        if self.mark is not None:
            _composite(canvas, self.mark[0], *self.mark[1])
        level = round(255 * self.blur_level(t))
        canvas.paste((0, 0, 0, level), (0, H, W, H + MASK_ROWS))  # after the sprites: nothing spills
        return canvas

    def _cut_out(self, canvas: Image.Image, t: float) -> None:
        """Take what is drawn so far out where the speaker is, so they stand in front of it (the
        video under the layer shows through); "studio" draws an outline around them too."""
        assert self.track is not None
        half = self.track.half(t)
        person = half.resize((W, H), Image.BILINEAR)
        alpha = canvas.getchannel("A")
        top = ImageChops.multiply(alpha.crop((0, 0, W, H)), ImageChops.invert(person))
        alpha.paste(top, (0, 0))
        canvas.putalpha(alpha)
        if self.background == "studio" and (fade := 1.0 - self.blur_level(t)) > 0.01:
            blur, gain, opacity = OUTLINE  # (it goes as the speaker blurs behind a picture)
            grown = np.asarray(half.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) * gain
            ring = np.clip(grown - np.asarray(half, dtype=np.float32) * gain, 0, 255) * (opacity * fade / 255)
            line = Image.fromarray(ring.astype(np.uint8)).resize((W, H), Image.BILINEAR)
            white = Image.new("RGBA", (W, H), (255, 255, 255, 255))
            white.putalpha(line)
            canvas.alpha_composite(white, (0, 0))

    def _key(self, t: float) -> tuple | None:
        """Identifies what is on screen; None while something is moving."""
        if self.backdrop and self.track is not None:
            return None  # the speaker moves in front of the backdrop
        if any(c.start <= t < c.end for c in self.cutaways):
            return None
        if self.title is not None and self.title.start <= t < self.title.end:
            return None  # the speaker moves under it
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
        kinetic = self._kinetic_at(t)
        shown = None
        if kinetic is not None:
            if self.kinetic[kinetic].animating(t):
                return None
            shown = self.kinetic[kinetic].shown(t)
        return index, word, kinetic, shown, tuple(cards), level

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
    video, graded, moved = "[0:v]", "", ""
    if compositor.grade:
        # A theme's colour grade, on the speaker's video only (the layer keeps its colours, so the
        # captions stay as drawn), before it is moved and blurred.
        graded = f"[0:v]{compositor.grade}[graded];"
        video = "[graded]"
    place = compositor.place
    if not place.identity:
        # The speaker resized and moved (a cut-out look): their video on black, where the
        # layer's cut-out of them is; the layer covers the rest.
        moved = (
            f"{video}split=2[ground][speaker];"
            "[ground]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill[black];"
            f"[speaker]scale={place.width}:{place.height}[small];"
            f"[black][small]overlay=x={place.x}:y={place.y}:format=yuv420[moved];"
        )
        video = "[moved]"
    if compositor.blurs:
        # The blurred, dimmed copy is made at quarter size (cheap) and blended in by the level
        # carried in the layer's extra rows.
        dim = BLUR_DIM
        blur = (
            f"{video}split=2[sharp][soft];[soft]scale={W // 4}:{H // 4},gblur=sigma={BLUR_SIGMA},"
            f"lutyuv=y='16+(val-16)*{dim}':u='128+(val-128)*{dim}':v='128+(val-128)*{dim}',"
            f"scale={W}:{H}[blurred];"
            f"[mraw]crop={W}:{MASK_ROWS}:0:{H},alphaextract,scale={W}:{H}[mask];"
            "[blurred][mask]alphamerge[veil];"
            "[sharp][veil]overlay=x=0:y=0:format=yuv420:eof_action=repeat[base]"
        )
        graph = f"{graded}{moved}{layer};{blur};[base][layer]{finish}"
    else:
        graph = f"{graded}{moved}{layer};[mraw]nullsink;{video}[layer]{finish}"
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
    compositor = compositor or Compositor(project, files, Renderer(files, ctx.log, ctx.cancelled))
    pages = len(compositor.pages) or len(compositor.kinetic)
    title = "no title"
    if compositor.title is not None:
        where = "in front"
        if compositor.title.masks is not None:
            where = f"behind the speaker ({compositor.title_showing:.0%} of it showing)"
        title = f"title {title_words(project)!r} {where}"
    ctx.log(
        f"compose: {compositor.duration:.1f}s at {project.source.fps} fps,"
        f" {pages} caption pages ({compositor.captions}), {title},"
        f" {len(compositor.cutaways)} full-screen pictures,"
        f" {len(compositor.cards)} cards and cut-outs, speaker blurred in {len(compositor.blurs)}"
        f" stretch(es) ({project.style.speaker_behind}), motion: {compositor.motion_note}"
    )
    ctx.log(f"theme: {compositor.theme_note}")
    if compositor.title_note:
        ctx.log(compositor.title_note)
    if compositor.background != "dalang":
        behind = (
            f", {len(compositor.behind)} picture(s) behind them" if compositor.background == "studio" else ""
        )
        ctx.log(f"background: {compositor.background}, the speaker cut out by SAM 3.1 in front of it{behind}")
        if compositor.moved:
            style = project.style
            ctx.log(
                f"the speaker at {style.speaker_scale:.0%} of their size, their middle {style.speaker_x:.0%}"
                f" across and their bottom {style.speaker_y:.0%} down the frame"
            )
    if compositor.background_note:
        ctx.log(compositor.background_note)
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
