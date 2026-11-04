"""Effects on the speaker and the pictures, drawn on the overlay layer at render time (free, no
model call): the character the storyteller voices moving with their voice and glowing (a puppet
that talks), photo cards that slowly grow and characters that breathe (living stills),
characters sliding in from their side, a rim of light round the speaker while they step back,
the room going dark round them at the cliffhanger (a spotlight), and a theme's particles:
romance's bokeh, horror's mist, mystery's rain, drama's sparkle and legend's embers. The same
seed draws the same particles every render.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..media.speech import FRAME, Envelope

PARTICLES = {"romance": "bokeh", "horror": "mist", "mystery": "rain", "drama": "sparkle", "legend": "embers"}
SLIDE = 0.45  # seconds a character takes to slide in from their side
SLIDE_FAR = 0.3  # of the width: how far off they start
GROW = 0.04  # a photo card grows this much over its time on screen
BREATH, BREATH_SECONDS = 0.008, 3.4  # a standing character's breath: of its height, and its period
BOB = 0.014  # of the height: how far the voiced character rises on a loud syllable
TALK_GLOW = 0.55  # the opacity of the glow round the voiced character
TALK_EASE = 0.25  # seconds the glow takes to come and go
RIM = (5.0, 3.0, 200)  # the rim of light round a stepped-back speaker: blur (half-size px), gain, opacity
SPOT_DARK = 0.6  # how dark the room goes round the speaker at the cliffhanger
SPOT_EASE = 0.5  # seconds it takes to go dark, and light again
PUNCH = 1.12  # the punch-in: the shot cuts in this much on the face (hook's end, the cliffhanger)
PUNCH_SHARE = 0.4  # the share of the hook, at its end, that is punched in
PUNCH_SHORTEST = 1.0  # seconds: a shorter punch-in is left out
ECHO_FRAMES = 6  # horror's echo: the frames the ghost trails over, on a stressed word
ECHO_SECONDS = 0.6


def _soft_dot(radius: int, rgb: tuple[int, int, int], blur: float) -> Image.Image:
    size = 2 * radius + int(4 * blur) + 4
    alpha = Image.new("L", (size, size), 0)
    ImageDraw.Draw(alpha).ellipse(
        (size / 2 - radius, size / 2 - radius, size / 2 + radius, size / 2 + radius), fill=255
    )
    if blur:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    dot = Image.new("RGBA", (size, size), (*rgb, 255))
    dot.putalpha(alpha)
    return dot


def _star(size: int, rgb: tuple[int, int, int]) -> Image.Image:
    """A four-pointed twinkle."""
    alpha = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(alpha)
    c, w = size / 2, max(1.0, size / 9)
    draw.polygon(
        [
            (c, 0),
            (c + w, c - w),
            (size, c),
            (c + w, c + w),
            (c, size),
            (c - w, c + w),
            (0, c),
            (c - w, c - w),
        ],
        fill=255,
    )
    alpha = alpha.filter(ImageFilter.GaussianBlur(size / 18))
    star = Image.new("RGBA", (size, size), (*rgb, 255))
    star.putalpha(alpha)
    return star


def _with_alpha(image: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return image
    out = image.copy()
    out.putalpha(image.getchannel("A").point(lambda v, a=alpha: round(v * a)))
    return out


class Particles:
    """A theme's particles over the whole reel, `kind` one of PARTICLES' values."""

    def __init__(self, kind: str, width: int, height: int, seed: int = 7) -> None:
        self.kind, self.w, self.h = kind, width, height
        rng = np.random.default_rng(seed)
        self.items: list[tuple[float, ...]] = []
        self.sprites: list[Image.Image] = []

        def add(*item: float) -> None:  # x, y, speed, opacity, phase, period
            self.items.append(tuple(float(v) for v in item))

        u = rng.uniform
        if kind == "bokeh":
            for _ in range(16):
                r = int(rng.integers(16, 58))
                warm = (255, int(rng.integers(150, 205)), int(rng.integers(170, 215)))
                self.sprites.append(_soft_dot(r, warm, r * 0.45))
                add(u(0, width), u(0, height), u(-42, -18), u(0.10, 0.26), u(0, 6.28), u(5, 9))
        elif kind == "mist":
            for _ in range(6):
                mw, mh = int(rng.integers(520, 820)), int(rng.integers(180, 300))
                alpha = Image.new("L", (mw + 160, mh + 160), 0)
                ImageDraw.Draw(alpha).ellipse((80, 80, 80 + mw, 80 + mh), fill=255)
                alpha = alpha.filter(ImageFilter.GaussianBlur(55))
                blob = Image.new("RGBA", alpha.size, (196, 214, 204, 255))
                blob.putalpha(alpha)
                self.sprites.append(blob)
                drift = rng.choice([-1, 1]) * u(14, 30)
                add(
                    u(-200, width),
                    u(height * 0.35, height * 0.95),
                    drift,
                    u(0.24, 0.36),
                    u(0, 6.28),
                    u(7, 12),
                )
        elif kind == "rain":
            for _ in range(90):
                add(u(0, width + 300), u(0, height), u(1500, 2000), u(0.18, 0.36), u(38, 80), 0.0)
        elif kind == "sparkle":
            gold = (255, 214, 120)
            for _ in range(24):
                size = int(rng.integers(14, 34))
                self.sprites.append(_star(size, gold))
                add(u(0, width), u(0, height), u(6, 18), u(0.55, 0.95), u(0, 1), u(1.6, 3.2))
        elif kind == "embers":
            for _ in range(34):
                r = int(rng.integers(2, 6))
                tone = (255, int(rng.integers(120, 190)), int(rng.integers(30, 80)))
                self.sprites.append(_soft_dot(r, tone, r * 0.9))
                add(u(0, width), u(0, height), u(-150, -60), u(0.45, 0.95), u(0, 6.28), u(0.6, 1.6))

    def draw(self, canvas: Image.Image, t: float, composite) -> None:
        w, h = self.w, self.h
        if self.kind == "rain":
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            for x0, y0, speed, alpha, length, _ in self.items:
                y = (y0 + speed * t) % (h + 200) - 100
                x = (x0 - 0.16 * speed * t) % (w + 300) - 150
                draw.line(
                    (x, y, x + 0.16 * length, y - length), fill=(225, 232, 240, round(255 * alpha)), width=2
                )
            canvas.alpha_composite(layer)
            return
        for sprite, (x0, y0, speed, alpha, phase, period) in zip(self.sprites, self.items, strict=True):
            if self.kind == "mist":
                x = (x0 + speed * t) % (w + sprite.width) - sprite.width
                y = y0 + 18 * math.sin(2 * math.pi * t / period + phase) - sprite.height / 2
                a = alpha * (0.75 + 0.25 * math.sin(2 * math.pi * t / (period * 1.7) + phase))
            elif self.kind == "sparkle":
                x = x0
                y = (y0 + speed * t) % (h + 40) - 20
                a = alpha * max(0.0, math.sin(2 * math.pi * (t / period + phase))) ** 3
            else:  # bokeh and embers rise
                span = h + 2 * sprite.height
                y = (y0 + speed * t) % span - sprite.height
                sway = 24 if self.kind == "bokeh" else 16
                x = x0 + sway * math.sin(2 * math.pi * t / period + phase)
                flicker = (
                    1.0 if self.kind == "bokeh" else 0.65 + 0.35 * math.sin(2 * math.pi * t * 3.1 + phase * 5)
                )
                a = alpha * flicker * (0.8 + 0.2 * math.sin(2 * math.pi * t / (period * 1.3) + phase))
            if a > 0.02:
                composite(canvas, _with_alpha(sprite, a), round(x - sprite.width / 2), round(y))


class Voice:
    """How loud the voice is at a moment (0 quiet to 1 the loudest syllables), from its envelope."""

    def __init__(self, envelope: Envelope) -> None:
        level = envelope.level
        top = float(np.percentile(level, 98)) if len(level) else envelope.floor + 1
        self.loud = np.clip((level - envelope.floor - 6) / max(1.0, top - envelope.floor - 6), 0, 1)

    def at(self, t: float) -> float:
        k = int(t / FRAME)
        window = self.loud[max(0, k - 3) : k + 3]
        return float(window.max()) if len(window) else 0.0


def glow_of(sprite: Image.Image, rgb: tuple[int, int, int], radius: float = 16.0) -> tuple[Image.Image, int]:
    """A soft glow in `rgb` round a sprite's shape, and how far it reaches past it (pixels)."""
    pad = int(radius * 2)
    alpha = Image.new("L", (sprite.width + 2 * pad, sprite.height + 2 * pad), 0)
    alpha.paste(sprite.getchannel("A"), (pad, pad))
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, v * 2))
    glow = Image.new("RGBA", alpha.size, (*rgb, 255))
    glow.putalpha(alpha)
    return glow, pad


def rim(
    person_half: Image.Image, rgb: tuple[int, int, int], strength: float, size: tuple[int, int]
) -> Image.Image:
    """A rim of light just outside the speaker (from their half-size mask), at full size."""
    blur, gain, opacity = RIM
    grown = np.asarray(person_half.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) * gain
    ring = np.clip(grown - np.asarray(person_half, dtype=np.float32) * gain, 0, 255) * (
        opacity * strength / 255
    )
    line = Image.fromarray(ring.astype(np.uint8)).resize(size, Image.BILINEAR)
    light = Image.new("RGBA", size, (*rgb, 255))
    light.putalpha(line)
    return light


def veil(person_half: Image.Image, strength: float, size: tuple[int, int]) -> Image.Image:
    """The dark round the speaker at the cliffhanger: black, everywhere but where they are."""
    soft = person_half.filter(ImageFilter.GaussianBlur(3)).resize(size, Image.BILINEAR)
    dark = Image.new("L", size, round(255 * SPOT_DARK * strength))
    alpha = Image.composite(Image.new("L", size, 0), dark, soft)
    shade = Image.new("RGBA", size, (0, 0, 0, 255))
    shade.putalpha(alpha)
    return shade
