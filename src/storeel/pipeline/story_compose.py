"""Path C: compile a novel part in its promo layout, timed to the user's takes.

Timing: each take is one segment of the reel. Its transcript words are shared out among the
beats recorded in it by their share of the take's characters, so a beat's pictures start on
the word its text starts with (the user may not read the teleprompter word for word, so
proportions are safer than matching every word). A beat's "switch" is found by its words.

Layout (fractions of the frame): a red tag at the top, then one main
item (a note, chat bubbles, a photo card, a scene card or a cut-out object) in the upper half,
and up to two characters standing at the bottom on their side. The first time the storyteller
voices a character (a beat quoting them), that character's name shows over their head. The
hook has no pictures and keeps the speaker sharp; after it the speaker is blurred behind the
story (style permitting). The poll and the end card are fixed screens; a "Part N" badge is up
from the first frame.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from ..files import ProjectFiles
from ..models import Beat, BibleCharacter, Project, Story, StoryShow, Word
from .analyze import find_quote
from .compose import Compositor, H, W, _Card
from .layout import covered, to_region
from .render import (
    INK,
    RED,
    WHITE,
    badge,
    card,
    chat_bubble,
    cutout_sprite,
    name_tag,
    note_card,
    photo_card,
    pill,
    title_block,
)
from .story import CTA, HOOK, OUTRO, POLL

MIN_LINE = 0.25  # seconds: no beat is squeezed to less than this


@dataclass
class Line:
    """A stretch of the reel: the hook, a beat (or the part of it after its switch), the poll or
    the call to action."""

    kind: str  # hook | beat | poll | cta
    start: float
    end: float
    take: str
    show: StoryShow | None = None
    beat: Beat | None = None


def _segment_words(project: Project, start: float, end: float) -> list[Word]:
    if project.transcript is None:
        return []
    return [w for t in project.transcript.turns for w in t.words if start - 0.05 <= w.start < end]


def split_by_text(
    texts: list[str], words: list[Word], start: float, end: float
) -> list[tuple[float, float, list[Word]]]:
    """`[start, end]` shared among `texts` in order, by their share of the characters: each
    boundary falls on the spoken word nearest that share (or on the time share, without words)."""
    total = sum(max(1, len(t)) for t in texts)
    shares, acc = [], 0
    for t in texts:
        shares.append(acc / total)
        acc += max(1, len(t))
    if words:
        weights = [len(w.text) + 1 for w in words]
        wsum = sum(weights)
        cum, positions = 0, []
        for w in weights:
            positions.append(cum / wsum)
            cum += w
        cuts = []
        for share in shares:
            k = min(range(len(words)), key=lambda i: abs(positions[i] - share))
            cuts.append((k, words[k].start if share > 0 else start))
    else:
        cuts = [(0, start + share * (end - start)) for share in shares]
    out: list[tuple[float, float, list[Word]]] = []
    for i, (k, t0) in enumerate(cuts):
        t0 = max(t0, out[-1][0] + MIN_LINE) if out else start
        t0 = min(t0, end - MIN_LINE * (len(cuts) - i))
        if out:
            out[-1] = (out[-1][0], t0, out[-1][2])
        upto = cuts[i + 1][0] if i + 1 < len(cuts) else len(words)
        out.append((t0, end, words[k:upto] if words else []))
    return out


def _switch_time(beat: Beat, words: list[Word], start: float, end: float) -> float | None:
    if beat.switch is None:
        return None
    span = find_quote(words, beat.switch.at) if words else None
    if span is not None:
        at = words[span[0]].start
    else:
        index = beat.text.lower().find(beat.switch.at.lower())
        if index <= 0:
            return None
        at = start + (end - start) * index / max(1, len(beat.text))
    return at if start + MIN_LINE <= at <= end - MIN_LINE else None


def _whole_video_takes(project: Project) -> dict[str, tuple[float, float]]:
    """One video of the whole part (no takes): each take's stretch, from the words spoken."""
    source, script = project.source, project.script
    if source is None or script is None:
        return {}
    words = _segment_words(project, 0.0, source.duration)
    spans = split_by_text([s.lines for s in script.scenes], words, 0.0, source.duration)
    return {scene.id: (a, b) for scene, (a, b, _) in zip(script.scenes, spans, strict=True)}


def take_spans(project: Project) -> dict[str, tuple[float, float]]:
    """Where each take is on the reel's timeline: its recording, or its share of one video."""
    source = project.source
    if source is None:
        return {}
    spans = {seg.scene_id: (seg.start, seg.end) for seg in source.segments if seg.scene_id}
    return spans or _whole_video_takes(project)


def timeline(project: Project) -> list[Line]:
    """Every line of the part placed on the reel's timeline. The takes are the hook, the beats'
    takes (one per beat; a part written before may group several), then the poll and the call
    to action (or, in a part written before, both in one take)."""
    story, source, script = project.story, project.source, project.script
    if story is None or source is None or script is None:
        return []
    takes = take_spans(project)
    lines: list[Line] = []
    for scene in script.scenes:
        span = takes.get(scene.id)
        if span is None:
            continue
        start, end = span
        if scene.purpose == HOOK:
            lines.append(Line("hook", start, end, scene.id))
        elif scene.purpose == POLL:
            lines.append(Line("poll", start, end, scene.id))
        elif scene.purpose == CTA:
            lines.append(Line("cta", start, end, scene.id))
        elif scene.purpose == OUTRO:
            words = _segment_words(project, start, end)
            parts = split_by_text([story.poll.text, story.cta], words, start, end)
            lines.append(Line("poll", parts[0][0], parts[0][1], scene.id))
            lines.append(Line("cta", parts[1][0], parts[1][1], scene.id))
        else:
            beats = [b for b in story.beats if b.take == scene.id]
            if not beats:
                continue
            words = _segment_words(project, start, end)
            shares = split_by_text([b.text for b in beats], words, start, end)
            for beat, (t0, t1, own) in zip(beats, shares, strict=True):
                at = _switch_time(beat, own, t0, t1)
                if at is None:
                    lines.append(Line("beat", t0, t1, scene.id, beat.show, beat))
                else:
                    assert beat.switch is not None
                    lines.append(Line("beat", t0, at, scene.id, beat.show, beat))
                    lines.append(Line("beat", at, t1, scene.id, beat.switch.show, beat))
    return lines


# ---- the layout -------------------------------------------------------------------------------

# Where things go, as fractions of the frame.
TAG_Y = 0.15
TAG_SHIFT = 0.05  # the main item moves down this much under a tag
CARD_Y, CARD_W = 0.29, 0.84
OBJECT_W = {"small": 0.42, "medium": 0.64, "large": 0.94}
OBJECT_H = {"small": 0.24, "medium": 0.34, "large": 0.46}  # tall objects are sized by height
NOTE_Y = 0.30
CHAT_Y, CHAT_STEP, CHAT_W = 0.22, 0.135, 0.80
SLOT_X = {"left": 0.24, "right": 0.76}
STAND_H, STAND_BOTTOM = 0.52, 1.02
BADGE_XY = (0.04, 0.035)
BADGE_SIZE = 0.026  # of the height: small enough to sit above the platforms' top bar
NAME_SIZE, NAME_GAP = 0.034, 0.006  # a voiced character's name, just above their head
POLL_Y = (0.17, 0.265, 0.345)
END_TOP, END_PROP_Y, END_PILL_Y = 0.115, 0.465, 0.635
WORDS = {
    "id": {"poll": "KAMU PILIH MANA?", "end": "Baca lengkapnya di link bio"},
    "en": {"poll": "WHICH WOULD YOU PICK?", "end": "Read the full part at the link in bio"},
}


class Sprites:
    """Builds and caches each screen element of a part, positioned on the frame."""

    def __init__(
        self,
        project: Project,
        files: ProjectFiles,
        novel_files: ProjectFiles | None,
        cast: dict[str, BibleCharacter] | None = None,
    ) -> None:
        self.project = project
        self.story = project.story
        self.files = {"project": files, "novel": novel_files}
        self.pictures = project.part_pictures or {}
        self.props = {p.id: p for p in self.story.props} if self.story else {}
        self.photos = {p.id: p for p in self.story.photos} if self.story else {}
        # where each character stands and what viewers call them: the bible's, then this part's
        self.slots = {cid: c.slot for cid, c in (cast or {}).items()}
        self.labels = {cid: c.label for cid, c in (cast or {}).items()}
        for c in self.story.characters if self.story else []:
            self.slots[c.id], self.labels[c.id] = c.slot, c.label
        self.bases = {v.id: v.base for v in self.story.variants} if self.story else {}
        self.cache: dict[tuple, Image.Image] = {}

    def image(self, picture_id: str) -> Image.Image | None:
        picture = self.pictures.get(picture_id)
        files = self.files.get(picture.scope) if picture else None
        if picture is None or not picture.key or files is None or not files.exists(picture.key):
            return None
        with Image.open(files.path(picture.key)) as opened:
            return opened.convert("RGBA" if picture.cutout else "RGB")

    def _cached(self, key: tuple, build) -> Image.Image | None:
        if key not in self.cache:
            self.cache[key] = build()
        return self.cache[key]

    def standing(self, show: StoryShow) -> list[str]:
        """The characters a beat's screen shows standing at the bottom (those with a picture)."""
        return [c for c in show.characters if self.image(c) is not None][:2] if show.characters else []

    def person(self, character: str) -> str:
        """Who a picture is of: a variant (Agus injured) is its base character (Agus)."""
        return self.bases.get(character, character)

    def label(self, character: str) -> str:
        return self.labels.get(character) or self.labels.get(self.person(character)) or ""

    def layers(self, show: StoryShow, name: str = "") -> list[tuple[Image.Image, tuple[int, int]]]:
        """One beat's screen: (sprite, top-left) in drawing order. `name` is a standing character
        whose name goes over their head (the storyteller voices them for the first time)."""
        out: list[tuple[Image.Image, tuple[int, int]]] = []
        shift = 0.0
        if show.tag:
            tag = self._cached(("tag", show.tag), lambda: pill(show.tag, round(0.04 * H)))
            out.append((tag, (W // 2 - tag.width // 2, round(TAG_Y * H) - tag.height // 2)))
            shift = TAG_SHIFT
        chars = self.standing(show)

        def centred(sprite: Image.Image, y: float) -> None:
            out.append((sprite, (W // 2 - sprite.width // 2, round(y * H) - sprite.height // 2)))

        if show.note.text:
            width = round((0.66 if chars else 0.74) * W)
            centred(
                self._cached(
                    ("note", show.note.text, show.note.style, width),
                    lambda: note_card(show.note.text, show.note.style, width, H),
                ),
                NOTE_Y + shift,
            )
        elif show.chat:
            x = 0.5
            if len(chars) == 1:
                x = 0.44 if self.slot(chars[0]) == "right" else 0.56
            for k, message in enumerate(show.chat[:2]):
                bubble = self._cached(
                    ("chat", message.sender, message.text),
                    lambda m=message: chat_bubble(m.sender, m.text, round(CHAT_W * W), H),
                )
                out.append(
                    (
                        bubble,
                        (
                            round(x * W) - bubble.width // 2,
                            round((CHAT_Y + CHAT_STEP * k + shift) * H) - bubble.height // 2,
                        ),
                    )
                )
        elif show.photo and (picture := self.image(show.photo)) is not None:
            title = self.photos[show.photo].title if show.photo in self.photos else ""
            centred(
                self._cached(("photo", show.photo), lambda: photo_card(picture, round(CARD_W * W), title)),
                CARD_Y + shift,
            )
        elif show.prop and (picture := self.image(show.prop)) is not None:
            meta = self.props.get(show.prop)
            info = self.pictures.get(show.prop)
            if info is not None and info.cutout:
                size = meta.size if meta else "medium"
                if chars and size == "large":
                    size = "medium"
                if meta and meta.shape == "tall":
                    box = (round(W * 0.8), round(OBJECT_H[size] * H))
                    y = 0.34 + shift
                else:
                    box = (round(OBJECT_W[size] * W), round(H * 0.4))
                    y = 0.4 if size == "large" else 0.35 + shift
                centred(self._cached(("object", show.prop, size), lambda: cutout_sprite(picture, *box)), y)
            else:
                centred(
                    self._cached(("scene", show.prop), lambda: photo_card(picture, round(CARD_W * W))),
                    0.30 + shift,
                )
        slots = ["left", "right"] if len(chars) == 2 else [self.slot(c) for c in chars]
        named: tuple[Image.Image, tuple[int, int]] | None = None
        for cid, slot in zip(chars, slots, strict=True):
            picture = self.image(cid)
            info = self.pictures.get(cid)
            if picture is None:
                continue
            if info is not None and info.cutout:
                sprite = self._cached(
                    ("stand", cid), lambda p=picture: cutout_sprite(p, round(0.56 * W), round(STAND_H * H))
                )
            else:  # SAM missed: a framed portrait instead
                sprite = self._cached(
                    ("standcard", cid), lambda p=picture: card(p, round(0.46 * W), round(0.4 * H))
                )
            x = round(SLOT_X[slot] * W) - sprite.width // 2
            y = round(STAND_BOTTOM * H) - sprite.height
            out.append((sprite, (x, y)))
            if cid == name and (text := self.label(cid)):
                named = self._name_over(text, sprite, x, y)
        if named is not None:
            out.append(named)  # last, so nothing covers it
        return out

    def _name_over(
        self, text: str, sprite: Image.Image, x: int, y: int
    ) -> tuple[Image.Image, tuple[int, int]]:
        """`text` centred just above the top of the picture in `sprite` (not its shadow)."""
        tag = self._cached(("name", text), lambda: name_tag(text, round(NAME_SIZE * H), round(0.9 * W)))
        top = _solid(sprite)[1]
        bottom = _solid(tag)[3]
        tx = min(max(0, x + sprite.width // 2 - tag.width // 2), W - tag.width)
        ty = max(round(0.02 * H), y + top - round(NAME_GAP * H) - bottom)
        return tag, (tx, ty)

    def slot(self, character: str) -> str:
        return self.slots.get(character) or self.slots.get(self.person(character)) or "left"


def _solid(image: Image.Image) -> tuple[int, int, int, int]:
    """The box of an image's opaque part: the picture or the text, without its soft shadow."""
    box = image.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    return box or (0, 0, image.width, image.height)


class PartCompositor(Compositor):
    """The reel for a novel part: the speaker, the beats' pictures, the poll, the end card."""

    def __init__(
        self,
        project: Project,
        files: ProjectFiles,
        novel_files: ProjectFiles | None,
        cast: dict[str, BibleCharacter] | None = None,
    ) -> None:
        self._novel_files = novel_files
        self._cast = cast or {}
        super().__init__(project, files)

    def _build_pictures(self, project: Project, files: ProjectFiles) -> list[tuple[float, float]]:
        story = project.story
        if story is None:
            return []
        style = project.style
        sprites = Sprites(project, files, self._novel_files, self._cast)
        language = project.script.language if project.script else "id"
        words = WORDS.get(language, WORDS["id"])
        lines = timeline(project)
        spans: list[tuple[float, float]] = []
        faces = project.part_faces
        ident = 0
        named: set[str] = set()  # the characters whose name has been on screen

        def add(
            image: Image.Image, xy: tuple[int, int], start: float, end: float, animate: bool = True
        ) -> None:
            nonlocal ident
            ident += 1
            center = (xy[0] + image.width // 2, xy[1] + image.height // 2)
            self.cards.append(_Card(start, end, image, center, ident=ident, animate=animate))

        def voiced(line: Line) -> str:
            """The character standing in this line whose words the storyteller says, the first
            time they do (their name goes over their head)."""
            speaker = line.beat.speaker if line.beat is not None else "narrator"
            if speaker == "narrator" or line.show is None:
                return ""
            person = sprites.person(speaker)
            if person in named:
                return ""
            shown = next((c for c in sprites.standing(line.show) if sprites.person(c) == person), "")
            if shown and sprites.label(shown):
                named.add(person)
                return shown
            return ""

        previous: list[tuple[int, int, int]] = []  # what was on screen in the line before: no re-pop
        for line in lines:
            if line.kind == "hook":
                previous = []
                continue
            if line.kind == "beat" and line.show is not None:
                layers = sprites.layers(line.show, name=voiced(line))
            elif line.kind == "poll":
                layers = self._poll(story, words)
            else:
                layers = self._end(project, sprites, words)
            now = []
            for image, xy in layers:
                key = (id(image), *xy)
                add(image, xy, line.start, line.end, animate=key not in previous)
                now.append(key)
            previous = now
            behind = style.speaker_behind
            blur = behind == "blur"
            if behind == "auto":
                boxes = faces.get(line.take)
                if boxes is None:
                    self.unchecked_faces += 1
                    blur = True
                else:
                    blur = any(covered(to_region(x, y, im.width, im.height), boxes) for im, (x, y) in layers)
            if blur and line.kind != "hook":
                spans.append((line.start, line.end))
        if lines:
            part = f"Part {story.part}"
            mark = badge(part, story.chapter_title, round(BADGE_SIZE * H), round(0.86 * W))
            end = next((x.start for x in lines if x.kind == "cta"), self.duration)
            add(mark, (round(BADGE_XY[0] * W), round(BADGE_XY[1] * H)), 0.0, end, animate=False)
        return spans

    def _poll(self, story: Story, words: dict[str, str]) -> list[tuple[Image.Image, tuple[int, int]]]:
        out = []
        for text, y, size, box, ink, width in (
            (words["poll"], POLL_Y[0], 0.036, RED, (255, 255, 255, 255), None),
            (f"A. {story.poll.a}", POLL_Y[1], 0.032, WHITE, INK, round(0.72 * W)),
            (f"B. {story.poll.b}", POLL_Y[2], 0.032, WHITE, INK, round(0.72 * W)),
        ):
            sprite = pill(text, round(size * H), box, ink, width)
            out.append((sprite, (W // 2 - sprite.width // 2, round(y * H) - sprite.height // 2)))
        return out

    def _end(
        self, project: Project, sprites: Sprites, words: dict[str, str]
    ) -> list[tuple[Image.Image, tuple[int, int]]]:
        story = project.story
        assert story is not None
        novel_title = (project.title.split(" - Part")[0]).strip()
        titles = title_block(
            f"Part {story.part}", story.chapter_title, novel_title, round(0.88 * W), round(0.05 * H)
        )
        out = [(titles, (W // 2 - titles.width // 2, round(END_TOP * H)))]
        key_prop = next((p.id for p in story.props if not p.refs and sprites.image(p.id) is not None), None)
        if key_prop:
            picture = sprites.image(key_prop)
            info = sprites.pictures.get(key_prop)
            if picture is not None:
                box = (round(0.6 * W), round(0.22 * H))
                sprite = cutout_sprite(picture, *box) if info and info.cutout else card(picture, *box)
                out.append((sprite, (W // 2 - sprite.width // 2, round(END_PROP_Y * H) - sprite.height // 2)))
        end = pill(words["end"], round(0.032 * H), WHITE, INK)
        out.append((end, (W // 2 - end.width // 2, round(END_PILL_Y * H) - end.height // 2)))
        return out
