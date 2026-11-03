"""Motion graphics rendered by HyperFrames, run here as a local renderer.

Pillow draws every layer of the reel. At three moments the layers move in ways CSS writes
well, so those moments go through HyperFrames (Apache-2.0, github.com/heygen-com/hyperframes),
which renders an HTML page frame by frame in headless Chrome:

- the title's letters rise in one by one (`title_page`);
- photo cards swing in through 3D, catching the light (`swing_page`: all of a reel's cards
  on one sheet, one after another, so Chrome starts once);
- a novel part's end screen comes in piece by piece (`stage_page`).

The pages come from the fixed templates below. Words and pictures go in as data (escaped
text, PNG files), never as code, and the fonts are the studio's own files, so a render fetches
nothing. HyperFrames writes transparent PNG frames; the compositor draws them in place of the
layer's plain entrance. Renders are cached in the project's files by what went into them, so
rendering a reel again costs nothing. When HyperFrames is not installed, is switched off
(STOREEL_HYPERFRAMES=off) or fails, the layers come in the plain way: no reel depends on it.
Its telemetry, update checks and skill installs are switched off for every run.
"""

from __future__ import annotations

import html
import io
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ..common import Cancelled, digest
from ..files import ProjectFiles
from .render import FONT_FILE, TitleSprite

VERSION = 1  # bump when a template changes: cached renders are made again
TIMEOUT = 240.0  # seconds a page may take
ROOT = Path(__file__).resolve().parents[3]  # the repository (motion/ holds the npm install)
ENV = {
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "HYPERFRAMES_AGENT": "1",  # unattended: never prompts
}

# The entrances' lengths, in seconds.
TITLE_SECONDS = 0.9
SWING_SECONDS = 0.9
STAGE_SECONDS = 1.7
HOLD = 0.1  # the title's letters have settled this long before its last frame
SWING_MARGIN = (0.12, 0.16)  # room around a card for its 3D swing, of its width and height


@lru_cache(maxsize=1)
def cli() -> str | None:
    """The HyperFrames command, or None when it is not there (or switched off)."""
    wanted = os.environ.get("STOREEL_HYPERFRAMES", "").strip()
    if wanted.lower() in ("off", "0", "no", "false"):
        return None
    path = Path(wanted) if wanted else ROOT / "motion" / "node_modules" / ".bin" / "hyperframes"
    if not path.is_file() or not os.access(path, os.X_OK) or shutil.which("node") is None:
        return None
    return str(path)


# ---- the rendered frames --------------------------------------------------------------------


@dataclass
class Motion:
    """An entrance: transparent frames at `fps`, drawn with their top-left at `xy`."""

    frames: list[Path]
    fps: float
    xy: tuple[int, int]
    _loaded: dict[int, Image.Image] = field(default_factory=dict, repr=False)

    @property
    def duration(self) -> float:
        return len(self.frames) / self.fps

    def at(self, since: float) -> Image.Image:
        """The frame `since` seconds into the entrance (the last one after it)."""
        k = min(len(self.frames) - 1, max(0, int(since * self.fps + 1e-6)))
        image = self._loaded.get(k)
        if image is None:
            with Image.open(self.frames[k]) as opened:
                image = opened.convert("RGBA")
            if len(self._loaded) >= 3:  # frames are read in order: keep only the latest few
                self._loaded.pop(min(self._loaded))
            self._loaded[k] = image
        return image


# ---- pages ----------------------------------------------------------------------------------


@dataclass
class Page:
    """One HyperFrames composition: its HTML, the files it uses, its size and length."""

    name: str
    body: str  # the elements inside the root
    style: str  # its CSS
    width: int
    height: int
    seconds: float
    files: dict[str, bytes] = field(default_factory=dict)  # PNGs, by file name

    def html(self) -> str:
        w, h, d = self.width, self.height, f"{self.seconds:.3f}"
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={w}, height={h}">
<style>
@font-face {{ font-family: "Storeel Sans"; src: url("sans.ttf") format("truetype"); font-weight: 200 800; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: transparent; }}
#root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; }}
img {{ position: absolute; display: block; }}
{self.style}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{d}"
  data-width="{w}" data-height="{h}">
{self.body}
</div>
</body>
</html>
"""


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", compress_level=1)
    return out.getvalue()


def title_page(title: TitleSprite) -> Page:
    """The title's letters rising in one after another, each from a little lower, smaller and
    blurred, on a page the size of the still title, its lines where the still title has them."""
    size, line_h = title.size, title.line_height
    ascent, descent = title.metrics
    letters = sum(len(r) for r in title.rows)
    stagger = min(0.035, 0.42 / max(1, letters))
    rise = 0.5
    spans, k = [], 0
    for row in title.rows:
        cells = []
        for char in row:
            text = "&nbsp;" if char == " " else html.escape(char)
            cells.append(f'<span class="l" style="animation-delay:{k * stagger:.3f}s">{text}</span>')
            k += 1
        spans.append(f'<div class="row">{"".join(cells)}</div>')
    seconds = max(TITLE_SECONDS, round(k * stagger + rise + HOLD, 2))
    # A line box of line_h puts its baseline at line_h / 2 + (ascent - descent) / 2.
    top = round(title.baseline - line_h / 2 - (ascent - descent) / 2)
    shadow = f"0 {round(size * 0.04)}px {round(size * 0.16)}px rgba(0, 0, 0, 0.55)"
    start = f"translateY({round(size * 0.42)}px) scale(.86)"
    style = f"""
.title {{ position: absolute; left: 0; right: 0; top: {top}px; text-align: center;
  font-family: "Storeel Sans"; font-weight: 800; font-size: {size}px; line-height: {line_h}px;
  color: #fff; white-space: pre; text-shadow: {shadow}; }}
.row {{ display: block; height: {line_h}px; }}
.l {{ display: inline-block; opacity: 0; animation: rise {rise}s cubic-bezier(.2, .85, .25, 1) both; }}
@keyframes rise {{
  0% {{ opacity: 0; transform: {start}; filter: blur({round(size * 0.06)}px); }}
  55% {{ opacity: 1; }}
  100% {{ opacity: 1; transform: none; filter: none; }}
}}"""
    body = (
        f'<div class="clip" data-start="0" data-duration="{seconds:.3f}" data-track-index="0">'
        f'<div class="title">{"".join(spans)}</div></div>'
    )
    width, height = title.image.size
    return Page("title", body, style, width, height, seconds, {"sans.ttf": FONT_FILE.read_bytes()})


SWING = """
@keyframes swing {
  0% { opacity: 0; transform: translate3d(0, 10%, -420px) rotateX(26deg) rotateY(-32deg) rotateZ(-3deg); }
  25% { opacity: 1; }
  100% { opacity: 1; transform: none; }
}
@keyframes shine { 0% { transform: translateX(-120%); opacity: 0; } 15% { opacity: 1; }
  85% { opacity: 1; } 100% { transform: translateX(120%); opacity: 0; } }
.stage { position: absolute; inset: 0; perspective: 1800px; perspective-origin: 50% 35%; }
.card { position: absolute; transform-origin: 50% 70%; backface-visibility: hidden; }
.card img { position: absolute; left: 0; top: 0; }
.gloss { position: absolute; overflow: hidden; }
.beam { position: absolute; inset: -10% -40%; opacity: 0;
  background: linear-gradient(105deg, transparent 38%, rgba(255, 255, 255, 0.3) 50%, transparent 62%); }
"""


def _swing(image: Image.Image, name: str, x: int, y: int, delay: float, seconds: float) -> str:
    """A card swinging in: its sprite at (x, y), and a beam of light crossing its opaque part."""
    gx0, gy0, gx1, gy1 = _opaque(image)
    radius = round(min(gx1 - gx0, gy1 - gy0) * 0.04)
    return (
        f'<div class="card" style="left:{x}px;top:{y}px;width:{image.width}px;height:{image.height}px;'
        f'animation: swing {seconds:.3f}s cubic-bezier(.22, .7, .2, 1) {delay:.3f}s both">'
        f'<img src="{name}" width="{image.width}" height="{image.height}" alt="">'
        f'<div class="gloss" style="left:{gx0}px;top:{gy0}px;width:{gx1 - gx0}px;height:{gy1 - gy0}px;'
        f'border-radius:{radius}px"><div class="beam" style="animation: shine {seconds * 0.7:.3f}s '
        f'ease-in-out {delay + seconds * 0.3:.3f}s both"></div></div></div>'
    )


def _opaque(image: Image.Image) -> tuple[int, int, int, int]:
    box = image.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    return box or (0, 0, image.width, image.height)


def swing_page(cards: list[Image.Image], fps: float) -> tuple[Page, int]:
    """All the cards' 3D entrances, one after another on one sheet, each in its own slot of
    `slot` frames, centred on the sheet. Returns the page and the slot length in frames."""
    width = max(round(c.width * (1 + 2 * SWING_MARGIN[0])) for c in cards)
    height = max(round(c.height * (1 + 2 * SWING_MARGIN[1])) for c in cards)
    slot = max(4, round(SWING_SECONDS * fps))
    seconds = slot / fps
    moving = seconds - 2 / fps  # it has settled for the slot's last frames
    parts, files = [], {}
    for k, image in enumerate(cards):
        name = f"c{k}.png"
        files[name] = _png(image)
        x, y = (width - image.width) // 2, (height - image.height) // 2
        parts.append(
            f'<div class="clip" data-start="{k * seconds:.4f}" data-duration="{seconds:.4f}" '
            f'data-track-index="0"><div class="stage">{_swing(image, name, x, y, 0.0, moving)}</div></div>'
        )
    return Page("cards", "\n".join(parts), SWING, width, height, seconds * len(cards), files), slot


def stage_page(
    layers: list[tuple[Image.Image, tuple[int, int]]], kinds: list[str]
) -> tuple[Page, tuple[int, int]]:
    """A novel part's end screen coming in piece by piece: the titles wipe down, the picture
    swings in, the call to action pops and catches the light. `layers` are (sprite, top-left
    on the frame); `kinds` say which is which ("titles", "picture", "pill"). Returns the page
    and where its top-left goes on the frame."""
    x0 = min(xy[0] for _, xy in layers)
    y0 = min(xy[1] for _, xy in layers)
    x1 = max(xy[0] + im.width for im, xy in layers)
    y1 = max(xy[1] + im.height for im, xy in layers)
    pad_x, pad_y = 40, 60
    left, top = max(0, x0 - pad_x), max(0, y0 - pad_y)
    width, height = x1 + pad_x - left, y1 + pad_y - top
    parts, files = [], {}
    for k, ((image, (x, y)), kind) in enumerate(zip(layers, kinds, strict=True)):
        name = f"s{k}.png"
        files[name] = _png(image)
        x, y = x - left, y - top
        box = f"left:{x}px;top:{y}px;width:{image.width}px;height:{image.height}px"
        picture = f'<img src="{name}" width="{image.width}" height="{image.height}" alt="">'
        if kind == "picture":
            parts.append(f'<div class="stage">{_swing(image, name, x, y, 0.3, 0.85)}</div>')
        elif kind == "pill":
            parts.append(f'<div class="pop" style="{box}">{picture}</div>')
        else:
            parts.append(f'<div class="wipe" style="{box};animation-delay:{0.12 * k:.2f}s">{picture}</div>')
    style = (
        SWING
        + """
.wipe { position: absolute; animation: wipe .6s cubic-bezier(.2, .8, .25, 1) both; }
.wipe img, .pop img { position: absolute; left: 0; top: 0; }
@keyframes wipe { 0% { clip-path: inset(0 0 100% 0); transform: translateY(-26px); opacity: 0; }
  100% { clip-path: inset(0 0 0 0); transform: none; opacity: 1; } }
.pop { position: absolute; transform-origin: 50% 50%;
  animation: pop .55s cubic-bezier(.3, 1.5, .5, 1) .95s both; }
@keyframes pop { 0% { transform: scale(.6); opacity: 0; } 40% { opacity: 1; }
  100% { transform: none; opacity: 1; } }
"""
    )
    body = (
        f'<div class="clip" data-start="0" data-duration="{STAGE_SECONDS}" data-track-index="0">'
        f"{''.join(parts)}</div>"
    )
    return Page("end", body, style, width, height, STAGE_SECONDS, files), (left, top)


# ---- rendering ------------------------------------------------------------------------------


class MotionError(RuntimeError):
    pass


class Renderer:
    """Renders pages for one project, caching the frames under work/motion/<digest>/."""

    def __init__(
        self,
        files: ProjectFiles,
        log: Callable[[str], None] = lambda _: None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.files = files
        self.log = log
        self.cancelled = cancelled
        self.command = cli()

    @property
    def available(self) -> bool:
        return self.command is not None

    @staticmethod
    def _key(page: Page, fps: int) -> str:
        assets = sorted((name, digest(content)) for name, content in page.files.items())
        return digest(VERSION, page.html(), assets, fps)

    def render(self, pages: list[Page], fps: float) -> dict[str, list[Path] | None]:
        """Each page's frames at `fps` (None where it failed), the uncached ones rendered side
        by side. Cached frames of other pages (an earlier version of the reel) are deleted."""
        rate = max(1, round(fps))
        if not self.available or not pages:
            return {p.name: None for p in pages}
        out: dict[str, list[Path] | None] = {}
        todo = []
        for page in pages:
            folder = self.files.path(f"work/motion/{self._key(page, rate)}")
            frames = sorted(folder.glob("frame_*.png")) if folder.is_dir() else []
            if frames:
                out[page.name] = frames
            else:
                todo.append(page)
        if todo:
            began = time.monotonic()
            with ThreadPoolExecutor(max_workers=min(3, len(todo))) as pool:
                done = list(pool.map(lambda p: self._render_one(p, rate), todo))
            for page, frames in zip(todo, done, strict=True):
                out[page.name] = frames
            made = [p.name for p in todo if out.get(p.name)]
            if made:
                self.log(f"HyperFrames: rendered the {', '.join(made)} in {time.monotonic() - began:.0f}s")
        keep = {self._key(p, rate) for p in pages}
        root = self.files.path("work/motion")
        for old in root.iterdir() if root.is_dir() else []:
            if old.is_dir() and old.name not in keep and not old.name.endswith(".build"):
                shutil.rmtree(old, ignore_errors=True)
        return out

    def _render_one(self, page: Page, fps: int) -> list[Path] | None:
        key = self._key(page, fps)
        target = self.files.path(f"work/motion/{key}")
        build = self.files.prepare(f"work/motion/{key}.build/index.html").parent
        shutil.rmtree(build, ignore_errors=True)
        build.mkdir(parents=True)
        try:
            (build / "index.html").write_text(page.html(), encoding="utf-8")
            for name, content in page.files.items():
                (build / name).write_bytes(content)
            frames_dir = build / "frames"
            self._run(build, frames_dir, fps)
            frames = sorted(frames_dir.glob("frame_*.png"))
            expected = round(page.seconds * fps)
            if abs(len(frames) - expected) > 2:
                raise MotionError(f"{len(frames)} frames instead of {expected}")
            shutil.rmtree(target, ignore_errors=True)
            frames_dir.rename(target)
            return sorted(target.glob("frame_*.png"))
        except (MotionError, OSError) as exc:
            self.log(f"HyperFrames: the {page.name} did not render ({exc}); it comes in the plain way")
            return None
        finally:
            shutil.rmtree(build, ignore_errors=True)

    def _run(self, build: Path, frames_dir: Path, fps: int) -> None:
        assert self.command is not None
        cmd = [self.command, "render", str(build), "--format", "png-sequence", "--fps", str(fps)]
        cmd += ["--output", str(frames_dir), "--quiet", "--workers", "1"]
        errors = build / "stderr.txt"
        with errors.open("wb") as sink:
            proc = subprocess.Popen(
                cmd, cwd=build, env={**os.environ, **ENV}, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=sink,
            )  # fmt: skip
            started = time.monotonic()
            try:
                while proc.poll() is None:
                    if self.cancelled():
                        raise Cancelled
                    if time.monotonic() - started > TIMEOUT:
                        raise MotionError(f"took over {TIMEOUT:.0f}s")
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if proc.returncode != 0:
            tail = errors.read_text(errors="replace").strip()[-300:]
            raise MotionError(tail or f"exit {proc.returncode}")
