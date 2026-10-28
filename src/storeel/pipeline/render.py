"""Drawing with Pillow: caption pages, picture cards and the watermark."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT_FILE = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "PlusJakartaSans-VariableFont_wght.ttf"
_local = threading.local()  # FreeType faces are not safe to share between threads


def font(size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    cache: dict[tuple[int, int], ImageFont.FreeTypeFont] | None = getattr(_local, "fonts", None)
    if cache is None:
        cache = _local.fonts = {}
    key = (size, weight)
    if key not in cache:
        face = ImageFont.truetype(str(FONT_FILE), size)
        face.set_variation_by_axes([weight])
        cache[key] = face
    return cache[key]


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def is_light(rgb: tuple[int, int, int]) -> bool:
    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4


@dataclass(frozen=True)
class CaptionLayout:
    image: Image.Image  # the page: every word white with a dark outline and a soft shadow
    marks: list[tuple[Image.Image, tuple[int, int]]]  # per word: its highlighted look and offset


def caption_page(words: list[str], size: int, max_width: int, mode: str, color: str) -> CaptionLayout:
    """Lay out one page of words, centred, wrapped to `max_width`.

    `mode` "pill" puts the spoken word on a rounded `color` pill, "karaoke" draws it in
    `color`, "clean" has no highlight. The highlight images line up exactly with the page
    because both come from one layout.
    """
    fnt = font(size)
    ascent, descent = fnt.getmetrics()
    stroke = max(2, round(size * 0.075))
    space = fnt.getlength(" ") * (1.55 if mode == "pill" else 1.0)
    lines: list[list[int]] = [[]]
    for index in range(len(words)):
        trial = [*lines[-1], index]
        width = sum(fnt.getlength(words[k]) for k in trial) + space * (len(trial) - 1)
        if lines[-1] and width > max_width:
            lines.append([index])
        else:
            lines[-1] = trial
    line_height = ascent + descent + round(size * (0.3 if mode == "pill" else 0.12))
    pad = stroke + round(size * 0.3)
    widths = [sum(fnt.getlength(words[k]) for k in line) + space * (len(line) - 1) for line in lines]
    width, height = int(max(widths)) + 2 * pad, line_height * len(lines) + 2 * pad
    base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw, draw_shadow = ImageDraw.Draw(base), ImageDraw.Draw(shadow)
    origins: dict[int, tuple[float, float]] = {}
    for row, line in enumerate(lines):
        x = (width - widths[row]) / 2
        baseline = pad + row * line_height + (line_height - ascent - descent) / 2 + ascent
        for k in line:
            origins[k] = (x, baseline)
            draw_shadow.text(
                (x + size * 0.03, baseline + size * 0.06),
                words[k],
                font=fnt,
                anchor="ls",
                fill=(0, 0, 0, 150),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 150),
            )
            draw.text(
                (x, baseline),
                words[k],
                font=fnt,
                anchor="ls",
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 255),
            )
            x += fnt.getlength(words[k]) + space
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.06)))
    shadow.alpha_composite(base)

    marks: list[tuple[Image.Image, tuple[int, int]]] = []
    rgb = hex_rgb(color)
    if mode == "pill":
        ink = (0, 0, 0, 255) if is_light(rgb) else (255, 255, 255, 255)
        pad_x, pad_y = round(size * 0.22), round(size * 0.08)
        for k, word in enumerate(words):
            x, baseline = origins[k]
            pill_w = int(fnt.getlength(word)) + 2 * pad_x
            pill_h = ascent + descent + 2 * pad_y
            pill = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
            pill_draw = ImageDraw.Draw(pill)
            pill_draw.rounded_rectangle(
                (0, 0, pill_w - 1, pill_h - 1), radius=round(pill_h * 0.28), fill=(*rgb, 255)
            )
            pill_draw.text((pad_x, pad_y + ascent), word, font=fnt, anchor="ls", fill=ink)
            marks.append((pill, (round(x - pad_x), round(baseline - ascent - pad_y))))
    elif mode == "karaoke":
        for k, word in enumerate(words):
            x, baseline = origins[k]
            glyph_w = int(fnt.getlength(word)) + 2 * stroke + 2
            glyph_h = ascent + descent + 2 * stroke + 2
            glyph = Image.new("RGBA", (glyph_w, glyph_h), (0, 0, 0, 0))
            ImageDraw.Draw(glyph).text(
                (stroke + 1, stroke + 1 + ascent),
                word,
                font=fnt,
                anchor="ls",
                fill=(*rgb, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 255),
            )
            marks.append((glyph, (round(x - stroke - 1), round(baseline - ascent - stroke - 1))))
    return CaptionLayout(shadow, marks)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _shadowed(image: Image.Image, blur: int, offset: int, opacity: float) -> Image.Image:
    """`image` (RGBA) on a soft drop shadow of its own shape, with room around it."""
    pad = blur * 2 + offset
    out = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow.putalpha(image.getchannel("A").point(lambda v: round(v * opacity)))
    out.alpha_composite(shadow, (pad, pad + offset))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(image, (pad, pad))
    return out


def card(picture: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """The photo card: the whole picture (no crop) in a dark rounded
    frame with a soft drop shadow, as wide as `max_width` allows within `max_height`."""
    unit = max(1, max_width)
    pad = max(6, round(unit * 0.0165))  # the frame around the photo
    radius = max(10, round(unit * 0.036))
    inner = (max(16, max_width - 2 * pad), max(16, max_height - 2 * pad))
    photo = ImageOps.contain(picture.convert("RGB"), inner, Image.LANCZOS)
    size = (photo.width + 2 * pad, photo.height + 2 * pad)
    framed = Image.new("RGBA", size, (0, 0, 0, 0))
    framed.paste((32, 33, 36, 245), (0, 0, *size), _rounded_mask(size, radius))
    framed.paste(photo, (pad, pad), _rounded_mask(photo.size, max(4, radius - round(pad * 0.8))))
    return _shadowed(framed, blur=max(6, round(unit * 0.02)), offset=max(4, round(unit * 0.015)), opacity=0.3)


def cutout_sprite(picture: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """A cut-out (RGBA) scaled to fit the box, with a faint shadow so it reads on any background."""
    image = ImageOps.contain(
        picture.convert("RGBA"), (max(16, max_width), max(16, max_height)), Image.LANCZOS
    )
    unit = max(image.size)
    return _shadowed(
        image, blur=max(4, round(unit * 0.012)), offset=max(2, round(unit * 0.006)), opacity=0.35
    )


def watermark(text: str, size: int, max_width: int, opacity: float = 0.45) -> Image.Image:
    """Plain white bold text, see-through, with a faint shadow so it reads on white too."""
    fnt = font(size)
    words, lines = text.split(), [""]
    for word in words:
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and fnt.getlength(trial) > max_width:
            lines.append(word)
        else:
            lines[-1] = trial
    ascent, descent = fnt.getmetrics()
    line_height = round(size * 1.2)
    pad = round(size * 0.3)
    width = int(max(fnt.getlength(line) for line in lines)) + 2 * pad
    height = line_height * (len(lines) - 1) + ascent + descent + 2 * pad
    alpha = round(255 * opacity)
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ink = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    for row, line in enumerate(lines):
        x = (width - fnt.getlength(line)) / 2
        y = pad + row * line_height
        ImageDraw.Draw(shadow).text((x, y + size * 0.05), line, font=fnt, fill=(0, 0, 0, alpha // 2))
        ImageDraw.Draw(ink).text((x, y), line, font=fnt, fill=(255, 255, 255, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.08)))
    shadow.alpha_composite(ink)
    return shadow
