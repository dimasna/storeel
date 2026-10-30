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


# ---- novel parts: the screen elements --------------------------------------------------------

RED = (229, 9, 20, 235)
WHITE = (255, 255, 255, 240)
INK = (20, 20, 24, 255)


def _wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = [""]
    for word in text.split():
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and fnt.getlength(trial) > max_width:
            lines.append(word)
        else:
            lines[-1] = trial
    return lines


def pill(
    text: str,
    size: int,
    box: tuple[int, int, int, int] = RED,
    ink: tuple[int, int, int, int] = (255, 255, 255, 255),
    width: int | None = None,
    weight: int = 800,
) -> Image.Image:
    """A rounded banner of text (a tag, a poll option, the end card's call to action), with a
    soft shadow. `width` fixes the banner's width; otherwise it fits the text."""
    fnt = font(size, weight)
    pad_x, pad_y = round(size * 0.55), round(size * 0.32)
    max_text = (width - 2 * pad_x) if width else 10_000
    lines = _wrap(text, fnt, max_text)
    ascent, descent = fnt.getmetrics()
    line_h = ascent + descent
    text_w = max(int(fnt.getlength(line)) for line in lines)
    w = width or text_w + 2 * pad_x
    h = line_h * len(lines) + 2 * pad_y
    card_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card_img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=round(min(h, size * 1.6) * 0.42), fill=box)
    for row, line in enumerate(lines):
        draw.text((w / 2, pad_y + row * line_h + ascent), line, font=fnt, anchor="ms", fill=ink)
    return _shadowed(card_img, blur=max(3, size // 6), offset=max(2, size // 10), opacity=0.35)


def name_tag(text: str, size: int, max_width: int) -> Image.Image:
    """A character's name over their head, the first time the storyteller voices them: white bold
    text with a dark outline and a soft shadow, on one line (smaller if it would not fit)."""
    fnt = font(size, 800)
    while size > 12 and fnt.getlength(text) > max_width:
        size = round(size * 0.9)
        fnt = font(size, 800)
    stroke = max(2, round(size * 0.075))
    ascent, descent = fnt.getmetrics()
    pad = stroke + round(size * 0.3)
    width, height = int(fnt.getlength(text)) + 2 * pad, ascent + descent + 2 * pad
    base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text(
        (pad + size * 0.03, pad + ascent + size * 0.06),
        text,
        font=fnt,
        anchor="ls",
        fill=(0, 0, 0, 150),
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 150),
    )
    ImageDraw.Draw(base).text(
        (pad, pad + ascent),
        text,
        font=fnt,
        anchor="ls",
        fill=(255, 255, 255, 255),
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 255),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.06)))
    shadow.alpha_composite(base)
    return shadow


def photo_card(picture: Image.Image, width: int, title: str = "") -> Image.Image:
    """A photo in a dark rounded frame with its caption under it, the whole picture shown."""
    pad = max(6, round(width * 0.0165))
    radius = max(10, round(width * 0.036))
    inner = width - 2 * pad
    photo = picture.convert("RGB")
    photo = photo.resize((inner, max(1, round(inner * photo.height / photo.width))), Image.LANCZOS)
    title_font = font(max(16, round(width / 22)), 600)
    strip = round(title_font.size * 2.0) if title else 0
    size = (width, photo.height + 2 * pad + strip)
    framed = Image.new("RGBA", size, (0, 0, 0, 0))
    framed.paste((32, 33, 36, 245), (0, 0, *size), _rounded_mask(size, radius))
    framed.paste(photo, (pad, pad), _rounded_mask(photo.size, max(4, radius - round(pad * 0.8))))
    if title:
        ImageDraw.Draw(framed).text(
            (pad + round(pad * 0.6), pad + photo.height + strip / 2),
            title,
            font=title_font,
            anchor="lm",
            fill=(232, 234, 237, 255),
        )
    return _shadowed(
        framed, blur=max(6, round(width * 0.02)), offset=max(4, round(width * 0.015)), opacity=0.3
    )


NOTE_STYLES = {
    "paper": ((250, 246, 232, 255), (40, 36, 30, 255), -3.0),
    "sign": ((246, 214, 72, 255), (24, 22, 18, 255), 0.0),
    "screen": ((24, 26, 32, 250), (232, 236, 244, 255), 0.0),
}


def note_card(text: str, style: str, width: int, frame_height: int) -> Image.Image:
    """Writing the viewer must read: a note on paper (tilted, with tape), a sign or a screen."""
    paper, ink, tilt = NOTE_STYLES.get(style, NOTE_STYLES["paper"])
    size = max(18, round(frame_height * 0.03))
    fnt = font(size, 700)
    pad = round(size * 1.1)
    lines = _wrap(text, fnt, width - 2 * pad)
    ascent, descent = fnt.getmetrics()
    line_h = round((ascent + descent) * 1.18)
    h = line_h * len(lines) + 2 * pad
    note = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(note)
    draw.rounded_rectangle((0, 0, width - 1, h - 1), radius=round(frame_height * 0.008), fill=paper)
    for row, line in enumerate(lines):
        draw.text((width / 2, pad + row * line_h + ascent), line, font=fnt, anchor="ms", fill=ink)
    if style == "paper":
        tape = Image.new("RGBA", (round(width * 0.22), round(size * 1.1)), (236, 228, 196, 190))
        holder = Image.new("RGBA", (width, h + tape.height // 2), (0, 0, 0, 0))
        holder.alpha_composite(note, (0, tape.height // 2))
        holder.alpha_composite(tape, ((width - tape.width) // 2, 0))
        note = holder
    if tilt:
        note = note.rotate(tilt, resample=Image.BICUBIC, expand=True)
    return _shadowed(note, blur=max(5, size // 3), offset=max(3, size // 5), opacity=0.35)


def chat_bubble(sender: str, text: str, width: int, frame_height: int) -> Image.Image:
    """A phone message: the sender's name above the text, in a white rounded bubble."""
    size = max(16, round(frame_height * 0.026))
    name_font, text_font = font(round(size * 0.82), 700), font(size, 500)
    pad = round(size * 0.8)
    lines = _wrap(text, text_font, width - 2 * pad)
    ascent, descent = text_font.getmetrics()
    line_h = round((ascent + descent) * 1.12)
    name_h = round(name_font.size * 1.5)
    h = pad + name_h + line_h * len(lines) + pad
    bubble = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bubble)
    draw.rounded_rectangle((0, 0, width - 1, h - 1), radius=round(size * 1.1), fill=(255, 255, 255, 245))
    draw.text(
        (pad, pad + name_font.getmetrics()[0]), sender, font=name_font, anchor="ls", fill=(37, 99, 235, 255)
    )
    for row, line in enumerate(lines):
        draw.text((pad, pad + name_h + row * line_h + ascent), line, font=text_font, anchor="ls", fill=INK)
    return _shadowed(bubble, blur=max(5, size // 3), offset=max(3, size // 5), opacity=0.3)


def title_block(tag: str, title: str, novel: str, width: int, size: int) -> Image.Image:
    """The end card's titles: a red "Part N" pill, the part's title, the novel's name."""
    tag_img = pill(tag, round(size * 0.62))
    title_font, novel_font = font(size, 800), font(round(size * 0.6), 600)
    stroke = max(2, round(size * 0.06))
    title_lines = _wrap(title, title_font, width)
    novel_lines = _wrap(novel, novel_font, width)
    ta, td = title_font.getmetrics()
    na, nd = novel_font.getmetrics()
    title_h = round((ta + td) * 1.08) * len(title_lines)
    novel_h = round((na + nd) * 1.1) * len(novel_lines)
    gap = round(size * 0.35)
    h = tag_img.height + gap + title_h + gap + novel_h
    block = Image.new("RGBA", (width, h + stroke * 2), (0, 0, 0, 0))
    block.alpha_composite(tag_img, ((width - tag_img.width) // 2, 0))
    draw = ImageDraw.Draw(block)
    y = tag_img.height + gap
    for line in title_lines:
        draw.text(
            (width / 2, y + ta),
            line,
            font=title_font,
            anchor="ms",
            fill=(255, 255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 200),
        )
        y += round((ta + td) * 1.08)
    y += gap
    for line in novel_lines:
        draw.text(
            (width / 2, y + na),
            line,
            font=novel_font,
            anchor="ms",
            fill=(255, 255, 255, 220),
            stroke_width=max(1, stroke // 2),
            stroke_fill=(0, 0, 0, 180),
        )
        y += round((na + nd) * 1.1)
    return block


def badge(part: str, title: str, size: int, max_width: int) -> Image.Image:
    """Top-left from the first frame (so the platforms' cover shows it): "Part N" and the title."""
    tag_img = pill(part, size)
    title_font = font(round(size * 0.78), 700)
    stroke = max(2, round(size * 0.08))
    lines = _wrap(title, title_font, max_width - tag_img.width - round(size * 0.4))
    if len(lines) > 2:  # two lines at most, the second one ending on an ellipsis
        second = lines[1]
        while second and title_font.getlength(second + "…") > max_width - tag_img.width - round(size * 0.4):
            second = second.rsplit(" ", 1)[0] if " " in second else second[:-1]
        lines = [lines[0], second.rstrip(" ,.;:") + "…"]
    ascent, descent = title_font.getmetrics()
    line_h = ascent + descent
    text_w = max((int(title_font.getlength(x)) for x in lines), default=0)
    w = tag_img.width + round(size * 0.4) + text_w + 2 * stroke
    h = max(tag_img.height, line_h * len(lines) + 2 * stroke)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(tag_img, (0, (h - tag_img.height) // 2))
    draw = ImageDraw.Draw(out)
    top = (h - line_h * len(lines)) / 2
    for row, line in enumerate(lines):
        draw.text(
            (tag_img.width + round(size * 0.4), top + row * line_h + ascent),
            line,
            font=title_font,
            anchor="ls",
            fill=(255, 255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 190),
        )
    return out
