"""Genre themes: a reel dressed for the kind of story it tells.

The look (dalang, scene or studio) says what is behind the speaker, and it is the one choice
that costs something (SAM cuts them out). A theme dresses whichever look it is, for free and
without a SAM call:

- a colour grade on the speaker's video (an ffmpeg filter chain, before the move and the blur);
- the caption style and highlight, only where the user kept the defaults ("pill", #E50914);
- the photo cards' frame (see render.Frame);
- the title's ink and typeface (the studio's own sans or serif: no new font files);
- the studio backdrop, drawn at a quarter of the frame like compose.studio_backdrop;
- an effect on the stressed words of the word-by-word captions (see compose._Kinetic);
- a touch of its own (its `extras`): horror's photo cards glitch in instead of swinging, all of
  mystery's pictures lose their colour, drama has letterbox bars, legend's characters come in
  as shadow puppets that fill with colour.

A reel's Style.theme picks one. "auto" follows a novel part's genre (Muse Spark picks it from
the synopsis and the chapter when the first part is written, see genre.py); a novel whose genre
is still "auto" or is "other", and every reel that is not a novel part, then has no theme.
"none" keeps the plain look exactly as it was.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

from ..media import ffmpeg as ff
from ..models import Project, Style
from .render import Frame, hex_rgb

W, H = ff.WIDTH, ff.HEIGHT
QW, QH = W // 4, H // 4  # the backdrops are drawn this size and scaled up (they are all soft)
ASPECT = H / W
DEFAULT_CAPTIONS = Style.model_fields["captions"].default
DEFAULT_COLOR = Style.model_fields["caption_color"].default

_YY, _XX = np.mgrid[0:QH, 0:QW].astype(np.float32)
_U, _V = _XX / QW, _YY / QH  # across and down the frame, 0 to 1

Backdrop = Callable[[float, np.ndarray], np.ndarray]


@dataclass(frozen=True)
class Theme:
    name: str  # its genre
    label: str  # what it is called
    accent: str  # the caption highlight (#RRGGBB) while the user keeps the default
    captions: str  # the caption style while the user keeps "pill"
    frame: Frame  # the photo cards'
    title_ink: tuple[int, int, int]
    title_face: str  # "sans" or "serif"
    grade: str  # an ffmpeg filter chain for the speaker's video (YUV filters: no colour matrix)
    word: str  # the stressed words' effect: "pulse", "shake", "stamp", "flash" or "glow"
    summary: str  # what it does, for the compose log
    title_glow: tuple[int, int, int] | None = None
    extras: frozenset[str] = frozenset()  # "glitch", "desaturate", "letterbox", "silhouette"
    draw: Backdrop | None = field(default=None, repr=False, compare=False)

    @property
    def title(self) -> dict[str, object]:
        """How the title is set: render.title_sprite's ink, face and glow."""
        return {"ink": self.title_ink, "face": self.title_face, "glow": self.title_glow}

    def dress(self, style: Style) -> Style:
        """`style` with this theme's caption style and highlight where the user kept the
        defaults: any other value they chose wins."""
        update: dict[str, str] = {}
        if style.captions == DEFAULT_CAPTIONS:
            update["captions"] = self.captions
        if style.caption_color.upper() == DEFAULT_COLOR.upper():
            update["caption_color"] = self.accent
        return style.model_copy(update=update) if update else style

    def backdrop(self, t: float, accent: str) -> Image.Image:
        """The backdrop behind the cut-out speaker at `t` seconds, in place of the studio glow."""
        assert self.draw is not None
        out = self.draw(t, np.array(hex_rgb(accent), dtype=np.float32))
        small = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
        return small.resize((W, H), Image.BILINEAR)


def resolve(project: Project, novel_genre: str | None = None) -> Theme | None:
    """The theme a reel renders in: its style's, or on "auto" its novel's genre (a novel part
    only). None is the plain look: "none", a genre that is "other" or not chosen yet, or "auto"
    on a reel that is not a novel part."""
    name = project.style.theme
    if name == "auto":
        name = (novel_genre or "") if project.path == "novel" else ""
    return THEMES.get(name)


def describe(theme: Theme | None, project: Project, novel_genre: str | None = None) -> str:
    """The theme for the compose log: which one, why, and what it does."""
    if theme is not None:
        why = "the novel's genre" if project.style.theme == "auto" else "chosen in the style"
        return f"{theme.name} ({theme.label}, {why}): {theme.summary}"
    if project.style.theme == "none":
        return "none (chosen in the style)"
    if project.path != "novel":
        return "none"
    if novel_genre in (None, "auto"):
        return "none (the novel's genre is not chosen yet)"
    return f"none (the novel's genre is {novel_genre})"


def desaturate(image: Image.Image) -> Image.Image:
    """A picture in black and white, its transparency kept (mystery's pictures)."""
    grey = ImageOps.grayscale(image.convert("RGB")).convert("RGB")
    if image.mode == "RGBA":
        grey.putalpha(image.getchannel("A"))
    return grey


# ---- the backdrops ----------------------------------------------------------------------------
#
# Each draws one frame at quarter size as floats (QH x QW x 3), from `t` and the highlight
# colour. They move slowly, so nothing pulls the eye from the speaker in front of them.


def _glow(x: float, y: float, radius: float) -> np.ndarray:
    """A soft round light at (x, y) (fractions of the frame), `radius` of the width wide."""
    d2 = (_U - x) ** 2 + ((_V - y) * ASPECT) ** 2
    return np.exp(-2.2 * d2 / radius**2)[..., None]


def _mix(out: np.ndarray, color: np.ndarray | tuple[float, ...], amount: np.ndarray) -> np.ndarray:
    return out * (1 - amount) + np.asarray(color, dtype=np.float32) * amount


def _vignette(out: np.ndarray, strength: float, start: float = 0.45) -> np.ndarray:
    r = np.sqrt((_U - 0.5) ** 2 + ((_V - 0.5) * ASPECT * 0.62) ** 2) / 0.72
    fall = np.clip((r - start) / (1.05 - start), 0, 1)
    return out * (1 - strength * fall * fall * (3 - 2 * fall))[..., None]


def _grain(amount: float) -> np.ndarray:
    """A wall's grain: the same every frame (grain that changes every frame takes the video
    several times the bits to keep, and the platforms smooth it away)."""
    return amount * _GRAIN


_GRAIN = np.random.default_rng(11).normal(0.0, 1.0, (QH, QW, 1)).astype(np.float32)


_BOKEH_RNG = np.random.default_rng(7)
# x, start height, rise per second, radius (of the width), opacity, sway period, warmth
_BOKEH = [
    (
        float(_BOKEH_RNG.uniform(0.04, 0.96)),
        float(_BOKEH_RNG.uniform(0.0, 1.3)),
        float(_BOKEH_RNG.uniform(0.012, 0.03)),
        float(_BOKEH_RNG.uniform(0.025, 0.07)),
        float(_BOKEH_RNG.uniform(0.12, 0.3)),
        float(_BOKEH_RNG.uniform(7.0, 15.0)),
        float(_BOKEH_RNG.uniform(0.0, 1.0)),
    )
    for _ in range(16)
]


def _dusk(t: float, accent: np.ndarray) -> np.ndarray:
    """Romance: a dusk sky (violet above, rose, a warm light low down) with soft out-of-focus
    lights drifting up through it."""
    top, middle, low = (np.array(c, dtype=np.float32) for c in ((36, 18, 60), (118, 40, 92), (214, 104, 92)))
    v = np.clip(_V + 0.015 * math.sin(2 * math.pi * t / 23), 0, 1)[..., None]
    upper = top + (middle - top) * np.clip(v / 0.55, 0, 1)
    out = np.where(v < 0.55, upper, middle + (low - middle) * np.clip((v - 0.55) / 0.45, 0, 1))
    out = _mix(out, (255, 190, 140), 0.32 * _glow(0.5, 0.9, 0.55))
    warm = np.array((255, 228, 200), dtype=np.float32)
    for x0, y0, speed, radius, opacity, sway, warmth in _BOKEH:
        y = (y0 - speed * t) % 1.3 - 0.15
        x = x0 + 0.03 * math.sin(2 * math.pi * (t / sway + warmth))
        # only the box around the disc (in quarter-size pixels) is touched
        left, right = max(0, int((x - radius) * QW) - 1), min(QW, int((x + radius) * QW) + 2)
        top, bottom = (
            max(0, int((y - radius / ASPECT) * QH) - 1),
            min(QH, int((y + radius / ASPECT) * QH) + 2),
        )
        if left >= right or top >= bottom:
            continue
        u, v = _U[top:bottom, left:right], _V[top:bottom, left:right]
        d = np.sqrt((u - x) ** 2 + ((v - y) * ASPECT) ** 2)
        disc = np.clip((radius - d) / (radius * 0.4), 0, 1)[..., None]
        twinkle = 0.75 + 0.25 * math.sin(2 * math.pi * t / sway * 2 + x0 * 9)
        patch = out[top:bottom, left:right]
        out[top:bottom, left:right] = _mix(patch, accent + (warm - accent) * warmth, opacity * twinkle * disc)
    return out


def _flicker(t: float) -> float:
    """A failing light: a slow unsteady glow that now and then stutters."""
    level = 0.82 + 0.1 * math.sin(2 * math.pi * t * 0.53) + 0.06 * math.sin(2 * math.pi * t * 2.9 + 1.7)
    if (t * 0.41) % 1.0 < 0.06:
        level *= 0.4 + 0.4 * abs(math.sin(2 * math.pi * t * 11))
    return level


def _crypt(t: float, accent: np.ndarray) -> np.ndarray:
    """Horror: near black, with a dark glow of the highlight (green) that flickers, and a heavy
    vignette closing in."""
    out = np.broadcast_to(np.array((5, 8, 6), dtype=np.float32), (QH, QW, 3)).copy()
    dark = accent * 0.42
    level = _flicker(t)
    out = _mix(out, dark, 0.85 * level * _glow(0.5 + 0.04 * math.sin(2 * math.pi * t / 17), 0.36, 0.62))
    out = _mix(out, dark * 0.7, 0.4 * _glow(0.22 + 0.1 * math.sin(2 * math.pi * t / 29), 0.8, 0.45))
    return _vignette(out, 0.85)


def _spotlight(t: float, accent: np.ndarray) -> np.ndarray:
    """Mystery: a dark room, a cool spotlight swaying a little behind the speaker, its beam from
    above, on a grainy wall."""
    out = np.broadcast_to(np.array((10, 10, 12), dtype=np.float32), (QH, QW, 3)).copy()
    x = 0.5 + 0.035 * math.sin(2 * math.pi * t / 9)
    d2 = (_U - x) ** 2 + ((_V - 0.46) * ASPECT * 0.75) ** 2
    pool = 0.85 * np.exp(-d2 / 0.07)
    centre = 0.5 + (x - 0.5) * _V  # the beam leans from the lamp above to the pool
    half = 0.05 + 0.32 * _V
    beam = 0.22 * np.clip(1 - np.abs(_U - centre) / half, 0, 1) ** 2 * (1 - 0.5 * _V)
    light = np.array((198, 200, 210), dtype=np.float32)
    out = out + light * (pool + beam)[..., None]
    return _vignette(out, 0.6) + _grain(7.0)


def _curtain(t: float, accent: np.ndarray) -> np.ndarray:
    """Drama: a dark stage with a red glow and a gold one (the highlight) drifting across a
    curtain's folds."""
    out = np.broadcast_to(np.array((16, 5, 8), dtype=np.float32), (QH, QW, 3)).copy()
    red = np.array((190, 18, 40), dtype=np.float32)
    out = _mix(out, red, 0.72 * _glow(0.3 + 0.12 * math.sin(2 * math.pi * t / 14), 0.3, 0.75))
    out = _mix(out, accent, 0.48 * _glow(0.72 + 0.1 * math.cos(2 * math.pi * t / 11), 0.78, 0.55))
    folds = 0.86 + 0.14 * np.cos(2 * math.pi * (_U * 7 + 0.05 * math.sin(2 * math.pi * t / 7)))
    return out * folds[..., None]


def _kelir(t: float, accent: np.ndarray) -> np.ndarray:
    """Legend: the shadow-puppet screen (kelir), a cloth lit warm from behind by the lamp above,
    its light flickering gently, dark at its edges, with its top border and the banana trunk the
    puppets stand in along the bottom."""
    lamp = 0.9 + 0.05 * math.sin(2 * math.pi * t * 1.3) + 0.03 * math.sin(2 * math.pi * t * 3.7 + 0.5)
    lamp += 0.02 * math.sin(2 * math.pi * t * 7.9 + 2.0)
    cloth = np.array((226, 178, 112), dtype=np.float32) * 0.7 + accent * 0.3
    edge = np.array((34, 19, 10), dtype=np.float32)
    d2 = (_U - 0.5) ** 2 + ((_V - 0.3) * ASPECT * 0.7) ** 2
    light = (0.78 * lamp * np.exp(-d2 / 0.16))[..., None]
    out = edge + (cloth - edge) * light
    out *= (0.97 + 0.03 * np.sin(_V * QH * 1.7))[..., None]  # the cloth's weave
    wood = np.array((44, 24, 12), dtype=np.float32)
    out = _mix(out, wood, np.clip((0.03 - _V) / 0.008, 0, 1)[..., None])
    trunk = np.array((58, 38, 20), dtype=np.float32)
    return _mix(out, trunk, np.clip((_V - 0.93) / 0.01, 0, 1)[..., None])


# ---- the themes -----------------------------------------------------------------------------

THEMES: dict[str, Theme] = {
    "romance": Theme(
        name="romance",
        label="senja",
        accent="#FF8FAB",
        captions="serif",
        frame=Frame(
            fill=(251, 243, 232, 250),
            border=(226, 128, 156, 255),
            line=0.007,
            pad=0.024,
            radius=0.05,
            ink=(104, 54, 68, 255),
        ),
        title_ink=(255, 238, 218),
        title_face="serif",
        grade=("eq=saturation=1.08:gamma=1.03,lutyuv=u='clip(val-8,16,240)':v='clip(val+9,16,240)'"),
        word="pulse",
        summary="a warm grade, cream cards with a rose border, a serif cream title, a dusk backdrop"
        " with drifting lights, stressed words beating like a heart",
        draw=_dusk,
    ),
    "horror": Theme(
        name="horror",
        label="horror",
        accent="#A7F070",
        captions="bold",
        frame=Frame(
            fill=(8, 8, 10, 250),
            border=(168, 18, 24, 255),
            line=0.0035,
            pad=0.014,
            radius=0.012,
            ink=(214, 218, 210, 255),
        ),
        title_ink=(232, 236, 226),
        title_face="sans",
        title_glow=(196, 18, 30),
        grade=(
            "eq=saturation=0.5:contrast=1.06:brightness=-0.015,"
            "lutyuv=u='clip(val+7,16,240)':v='clip(val-4,16,240)',vignette=angle=0.62"
        ),
        word="shake",
        summary="a cold, desaturated grade with a vignette, black cards with a red edge that glitch in,"
        " a pale title glowing red, a flickering green backdrop, stressed words shaking",
        extras=frozenset({"glitch"}),
        draw=_crypt,
    ),
    "mystery": Theme(
        name="mystery",
        label="noir",
        accent="#EF233C",
        captions="bold",
        frame=Frame(fill=(240, 235, 222, 255), pad=0.032, radius=0.0, tilt=-2.4, ink=(48, 42, 36, 255)),
        title_ink=(255, 255, 255),
        title_face="sans",
        grade="hue=s=0,eq=contrast=1.14:brightness=-0.01",
        word="stamp",
        summary="high-contrast black and white, every picture in black and white on tilted paper"
        " prints, a grainy spotlight backdrop, stressed words stamped down",
        extras=frozenset({"desaturate"}),
        draw=_spotlight,
    ),
    "drama": Theme(
        name="drama",
        label="sinetron",
        accent="#F2C14E",
        captions="bold",
        frame=Frame(
            fill=(24, 16, 14, 248),
            border=(214, 170, 74, 255),
            line=0.006,
            pad=0.02,
            radius=0.03,
            ink=(244, 214, 146, 255),
        ),
        title_ink=(242, 193, 78),
        title_face="sans",
        grade="eq=contrast=1.16:saturation=1.25:gamma=0.97",
        word="flash",
        summary="a punchy grade, dark cards with a gold border, a gold title, red and gold glows,"
        " letterbox bars, stressed words zooming in with a flash",
        extras=frozenset({"letterbox"}),
        draw=_curtain,
    ),
    "legend": Theme(
        name="legend",
        label="wayang",
        accent="#F4A261",
        captions="serif",
        frame=Frame(
            fill=(70, 40, 22, 252),
            border=(206, 158, 66, 255),
            line=0.006,
            pad=0.026,
            radius=0.02,
            ink=(242, 214, 160, 255),
        ),
        title_ink=(236, 182, 92),
        title_face="serif",
        grade=(
            "eq=saturation=0.9:contrast=1.04:gamma=1.02,lutyuv=u='clip(val-12,16,240)':v='clip(val+8,16,240)'"
        ),
        word="glow",
        summary="a warm amber grade, dark-wood cards with a gold border, a serif gold title, a lamp-lit"
        " shadow-puppet screen, characters coming in as shadow puppets, stressed words glowing",
        extras=frozenset({"silhouette"}),
        draw=_kelir,
    ),
}
