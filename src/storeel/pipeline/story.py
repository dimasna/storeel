"""Path C: a novel chapter becomes one part of a series.

The script model writes the part: the HOOK (a fixed opening that names the part and the novel,
then a punch), the BEATS (a bridge from the previous part or part one's setup, rises, the turn,
the cliffhanger), and the OUTRO (a poll, then the call to action). Each beat also says what the
screen shows. The checks below enforce that shape; what they find is sent back for one
or two repair rounds, and whatever is still wrong is kept on the story for the user to see.

The user records the part themselves, one short take per line: the hook, each beat, the poll,
then the call to action. A slip costs one beat to redo, and each beat's pictures are timed by
its own recording.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ..common import slug
from ..config import TEXT_EFFORTS
from ..jobs import JobContext, PipelineError
from ..meta import MetaAPIError
from ..meta.schema import OutputError, parse_output, text_format
from ..models import (
    DEFAULT_TITLE,
    Beat,
    Bible,
    ChatMessage,
    Novel,
    Poll,
    Project,
    Scene,
    Script,
    Story,
    StoryBibleNote,
    StoryCharacter,
    StoryLook,
    StoryNote,
    StoryPhoto,
    StoryProp,
    StoryShow,
    StorySwitch,
    StoryVariant,
    Turn,
    text_model_name,
)
from ..prompts import load_prompt
from . import story_review
from .align import Text, align

READ_CHARS_PER_SECOND = 13.5  # read aloud from a teleprompter, a little slower than text-to-speech
MAX_SECONDS = 170  # the reel stays under three minutes with the end card
HOOK_MAX = 150
BRIDGE_MAX = 150
POLL_MAX = 110
CTA_MAX = 130
REPAIR_ROUNDS = 2
# A part made from the user's video thinks at most this hard: on the real API, splitting a 98.5 s
# video at "max" ran past 20,000 output tokens three times; "high" answered in 66 s.
VIDEO_EFFORT = "high"
REVIEW_ROUNDS = 1  # storyboard reviews of a script in the right shape, each followed by a rewrite
REVIEW_FIX = (
    "A storyboard review read the chapter next to this script and found moments whose pictures do"
    " not show what is being said. Fix the pictures of these beats (their see, show and then; add"
    " characters, variants, props or photos where needed), keep everything else, and answer with the"
    " whole corrected JSON object:"
)
ACTS = ("bridge", "setup", "rise", "turn", "cliffhanger")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


# ---- wording: what is fixed per language and per narration style ------------------------------


@dataclass(frozen=True)
class Wording:
    language: str
    part_word: str
    forbidden: str  # what a chapter is never called aloud
    forbidden_re: re.Pattern[str]
    previously: str  # the bridge beat's tag
    screen_poll: str
    screen_end: str
    bridge_shape: str
    setup_shape: str
    poll_shape: str
    cta_shape: str
    comment_re: re.Pattern[str]
    link_re: re.Pattern[str]
    first_opening: str  # "{part}" and "{title}" are filled in
    next_opening: str
    voice: str


_ID_UNITS = ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan"]
_EN_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n: int, language: str) -> str:
    """A part number as spoken words: 3 -> "tiga" / "three", 12 -> "dua belas" / "twelve"."""
    n = int(n)
    if language == "en":
        if n < 20:
            return _EN_UNITS[n]
        if n < 100:
            tens, unit = divmod(n, 10)
            return _EN_TENS[tens] + (f"-{_EN_UNITS[unit]}" if unit else "")
        if n < 1000:
            hundreds, rest = divmod(n, 100)
            return f"{_EN_UNITS[hundreds]} hundred" + (f" {number_words(rest, 'en')}" if rest else "")
        return str(n)
    if n < 10:
        return _ID_UNITS[n]
    if n == 10:
        return "sepuluh"
    if n == 11:
        return "sebelas"
    if n < 20:
        return f"{_ID_UNITS[n - 10]} belas"
    if n < 100:
        tens, unit = divmod(n, 10)
        return f"{_ID_UNITS[tens]} puluh" + (f" {_ID_UNITS[unit]}" if unit else "")
    if n < 200:
        return "seratus" + (f" {number_words(n - 100, 'id')}" if n > 100 else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ID_UNITS[hundreds]} ratus" + (f" {number_words(rest, 'id')}" if rest else "")
    return str(n)


VOICES = {
    "id": {
        "casual": "Bahasa Jakarta santai, seperti cerita ke teman: gue / lo, nggak, udah, banget, sumpah,"
        ' kocak, "guys", sesekali kata Inggris ("plot twist", "literally", "red flag"). Hangat, lucu,'
        " dramatis saat ceritanya berbelok. Tanpa kata kasar.",
        "warm": "Santai tapi sopan dan hangat, seperti cerita ke sahabat: aku / kamu (tidak pakai gue / lo),"
        " nggak, udah, banget. Lembut, penuh empati pada tokohnya, tetap seru.",
        "dramatic": "Narator dramatis: kalimat pendek, jeda, ketegangan yang dibangun pelan; aku / kamu,"
        " bahasa santai yang rapi tanpa slang berlebihan. Serius di bagian tegang, berbisik di bagian"
        " rahasia.",
        "funny": 'Gaya gosip kocak: gue / lo, reaksi lebay, komentar lucu di sela cerita ("sumpah ya",'
        ' "plis deh"), tapi alur ceritanya tetap runtut dan kutipannya tetap persis.',
    },
    "en": {
        "casual": 'Casual, conversational English, like telling a friend: "okay so", "literally",'
        ' "plot twist", "red flag". Warm, funny, dramatic when the story turns. No swearing.',
        "warm": "Warm and gentle, like a cozy book chat with a close friend: empathetic toward the"
        " characters, still gripping.",
        "dramatic": "A dramatic narrator: short sentences, pauses, suspense built slowly. Serious in the"
        " tense moments, hushed for the secrets.",
        "funny": "Funny gossip style: big reactions and witty asides between the story beats"
        ' ("I\'m sorry, what?"), while the story stays in order and the quotes stay exact.',
    },
}

_FIRST_OPENINGS = {
    "id": {
        "casual": "Gue baru baca {part} novel {title}",
        "warm": "Aku baru baca {part} novel {title}",
        "dramatic": "Ini {part} novel {title}",
        "funny": "Sumpah, gue baru baca {part} novel {title}",
    },
    "en": {
        "casual": "I just read {part} of {title}",
        "warm": "I just finished {part} of {title}",
        "dramatic": "This is {part} of {title}",
        "funny": "Okay, I just read {part} of {title}",
    },
}


def wording(language: str, narration: str) -> Wording:
    you = "lo" if narration in ("casual", "funny") else "kamu"
    if language == "en":
        return Wording(
            language="English",
            part_word="part",
            forbidden="chapter",
            forbidden_re=re.compile(r"\bchapters?\b", re.I),
            previously="PREVIOUSLY",
            screen_poll="WHICH WOULD YOU PICK?",
            screen_end="Read the full part at the link in bio",
            bridge_shape='"In part <previous number>, <name>, <who they are in a few words>, <what they did'
            ' or said at the very end>."',
            setup_shape='"So there\'s <who> called <name>, <their situation>."',
            poll_shape='"If you were <name>: <option a>, or <option b>? Comment A or B."',
            cta_shape='"Part <N> of <title> is at the link in bio." and one follow line for the next part:'
            ' "Follow so you don\'t miss part <N+1>."',
            comment_re=re.compile(r"\bcomment", re.I),
            link_re=re.compile(r"\blink\s+in\s+(?:my\s+)?bio\b", re.I),
            first_opening=_FIRST_OPENINGS["en"][narration],
            next_opening="Back with {part} of {title}",
            voice=VOICES["en"][narration],
        )
    return Wording(
        language="Indonesian",
        part_word="part",
        forbidden="bab",
        forbidden_re=re.compile(r"\bbab\b", re.I),
        previously="SEBELUMNYA",
        screen_poll="KAMU PILIH MANA?",
        screen_end="Baca lengkapnya di link bio",
        bridge_shape='"Di part <nomor sebelumnya>, <nama>, <siapa dia dalam beberapa kata>, <apa yang dia'
        ' lakukan atau katakan di akhir>."',
        setup_shape='"Jadi ada <siapa> namanya <nama>, <situasinya>."',
        poll_shape=f'"Kalau {you} jadi <nama>: <pilihan a>, atau <pilihan b>? Komen A atau B."',
        cta_shape='"<Part N> novel <judul> lengkapnya ada di link bio." lalu satu ajakan follow untuk part'
        ' berikutnya: "Follow biar nggak ketinggalan part <N+1>."',
        comment_re=re.compile(r"\bkomen", re.I),
        link_re=re.compile(r"\blink(?:-?nya)?\s+(?:di\s+)?bio\b", re.I),
        first_opening=_FIRST_OPENINGS["id"][narration],
        next_opening="Lanjut {part} novel {title}",
        voice=VOICES["id"][narration],
    )


def part_phrase(n: int, language: str) -> str:
    """How a part is said: "part dua" / "part two"."""
    return f"part {number_words(n, language)}"


def narration_options() -> dict[str, dict[str, dict[str, str]]]:
    """For the studio: each language's narration styles, with their voice and how part one opens."""
    return {
        language: {
            style: {
                "voice": voice,
                "opening": _FIRST_OPENINGS[language][style].format(
                    part=part_phrase(1, language), title="<title>"
                ),
            }
            for style, voice in styles.items()
        }
        for language, styles in VOICES.items()
    }


def hook_opening(novel: Novel, n: int, continuing: bool) -> str:
    w = wording(novel.language, novel.narration)
    template = w.next_opening if continuing else w.first_opening
    return template.format(part=part_phrase(n, novel.language), title=" ".join(novel.title.split()))


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def opens_correctly(hook: str, opening: str) -> bool:
    return _norm(hook).startswith(_norm(opening))


def system_prompt(novel: Novel, from_video: bool = False) -> str:
    """The script writer's rules: what to say (or, for a part made from the user's own video, how
    to split what they said), then the rules for the pictures and the character bible."""
    w = wording(novel.language, novel.narration)
    values = {
        "PART_WORD": w.part_word,
        "FORBIDDEN": w.forbidden,
        "LANGUAGE": w.language,
        "VOICE": w.voice,
        "HOOK_MAX": str(HOOK_MAX),
        "BRIDGE_MAX": str(BRIDGE_MAX),
        "BRIDGE_SHAPE": w.bridge_shape,
        "SETUP_SHAPE": w.setup_shape,
        "PREVIOUSLY": w.previously,
        "SCREEN_POLL": w.screen_poll,
        "SCREEN_END": w.screen_end,
        "POLL_SHAPE": w.poll_shape,
        "CTA_SHAPE": w.cta_shape,
    }
    text = load_prompt("story_video" if from_video else "story") + "\n\n" + load_prompt("story_pictures")
    for key, value in values.items():
        text = text.replace(f"<<{key}>>", value)
    return text


# ---- what the model answers (lenient: every field has a default) ------------------------------


class ChatOut(BaseModel):
    sender: str = ""
    text: str = ""


class NoteOut(BaseModel):
    text: str = ""
    style: Literal["paper", "sign", "screen"] = "paper"


class ShowOut(BaseModel):
    characters: list[str] = Field(default_factory=list, description="ids, at most two")
    prop: str = ""
    photo: str = ""
    chat: list[ChatOut] = Field(default_factory=list)
    note: NoteOut = Field(default_factory=NoteOut)
    tag: str = ""


class ThenOut(BaseModel):
    at: str = Field("", description="words copied exactly from the beat's text, or ''")
    show: ShowOut = Field(default_factory=ShowOut)


class BeatOut(BaseModel):
    act: Literal["bridge", "setup", "rise", "turn", "cliffhanger"] = "rise"
    text: str = Field("", description="spoken, 40-190 characters")
    speaker: str = "narrator"
    see: str = Field("", description="English: who and what the viewer sees while hearing this")
    direction: str = Field("", description="a short delivery note for the storyteller")
    show: ShowOut = Field(default_factory=ShowOut)
    then: ThenOut = Field(default_factory=ThenOut)


class CharacterOut(BaseModel):
    id: str = ""
    name: str = ""
    label: str = ""
    role: str = ""
    description: str = Field("", description="who they are, never their clothes")
    outfit: str = Field("", description="what they wear in this chapter")
    subject: str = Field("person", description="a short English noun for a segmentation model")
    slot: Literal["left", "right"] = "left"


class LookOut(BaseModel):
    id: str = ""
    outfit: str = ""


class VariantOut(BaseModel):
    id: str = ""
    base: str = ""
    change: str = ""
    persistent: bool = False


class PropOut(BaseModel):
    id: str = ""
    description: str = ""
    subject: str = ""
    shape: Literal["wide", "tall", "square"] = "square"
    size: Literal["small", "medium", "large"] = "medium"
    refs: list[str] = Field(default_factory=list)
    people: int = 0
    framing: Literal["full", "close-up"] = "full"
    backdrop: bool = False
    recurring: bool = False


class PhotoOut(BaseModel):
    id: str = ""
    description: str = ""
    title: str = ""


class BibleNoteOut(BaseModel):
    id: str = ""
    note: str = ""


class PollOut(BaseModel):
    text: str = ""
    a: str = ""
    b: str = ""


class StoryOut(BaseModel):
    chapter_title: str = Field("", description="a short title of this part, without 'Part N'")
    hook: str = ""
    hook_direction: str = ""
    beats: list[BeatOut] = Field(default_factory=list)
    poll: PollOut = Field(default_factory=PollOut)
    cta: str = ""
    characters: list[CharacterOut] = Field(default_factory=list)
    looks: list[LookOut] = Field(default_factory=list)
    variants: list[VariantOut] = Field(default_factory=list)
    props: list[PropOut] = Field(default_factory=list)
    photos: list[PhotoOut] = Field(default_factory=list)
    bible_notes: list[BibleNoteOut] = Field(default_factory=list)


# ---- the prompt for one chapter ---------------------------------------------------------------

TBC_RE = re.compile(r"^[\s_*~.\-]*(?:tbc|to be continued|bersambung)[\s_*~.!\-]*$", re.I | re.M)


def story_end(text: str, limit: int = 700) -> str:
    """The last paragraphs of a chapter, without the author's notes after its "tbc" line."""
    tbc = TBC_RE.search(text or "")
    body = (text or "")[: tbc.start()] if tbc else (text or "")
    paragraphs = [p.strip() for p in body.splitlines() if p.strip()]
    end: list[str] = []
    for p in reversed(paragraphs):
        if end and sum(len(x) + 1 for x in end) + len(p) > limit:
            break
        end.insert(0, p)
    out = "\n".join(end)
    return out if len(out) <= limit else "..." + out[-limit:]


@dataclass
class Previous:
    number: int
    title: str
    text: str
    beats: list[str]


def _bible_block(bible: Bible) -> str:
    characters = []
    for c in bible.characters.values():
        looks = sorted(c.looks, key=lambda x: x.chapter)
        last = {"chapter": looks[-1].chapter, "outfit": looks[-1].outfit} if looks else None
        characters.append(
            {
                "id": c.id,
                "name": c.name,
                "label": c.label,
                "role": c.role,
                "description": c.description,
                "last_outfit": last,
                "notes": [n.note for n in c.notes],
            }
        )
    props = [
        {"id": p.id, "description": p.description, "use": "show by id only when this object alone is shown"}
        for p in bible.props.values()
    ]
    if not characters and not props:
        return "(empty - this is the first chapter: design every character it shows)"
    return json.dumps({"characters": characters, "recurring_props": props}, ensure_ascii=False, indent=1)


def max_chars() -> int:
    return round(MAX_SECONDS * READ_CHARS_PER_SECOND)


def _context(novel: Novel, number: int, bible: Bible, previous: Previous | None) -> list[str]:
    """What every part's script is written from: the novel, the chapter, how the last part
    ended, and the character bible."""
    chapter = novel.chapter(number)
    assert chapter is not None
    language = novel.language
    title = " ".join(novel.title.split())
    out = [
        f"NOVEL: {title}",
        f"SYNOPSIS: {novel.synopsis.strip() or '(none)'}",
        "",
        f"PART {number} (chapter {number} of the novel): {chapter.title or '(untitled)'}",
        f"<<<\n{chapter.text.strip()}\n>>>",
        "",
    ]
    if previous is None:
        out += ["PREVIOUS PART: none - this is part one.", ""]
    else:
        lines = [
            f"PREVIOUS PART: {part_phrase(previous.number, language)}"
            + (f' ("{previous.title}")' if previous.title else "")
            + " - the bridge (beat 1) says how it ended."
        ]
        if previous.beats:
            lines.append("Its video ended with: " + " / ".join(previous.beats[-2:]))
        end = story_end(previous.text)
        if end:
            lines.append(f"Its text ended with:\n<<<\n{end}\n>>>")
        out += [*lines, ""]
    out += [f"CHARACTER BIBLE:\n{_bible_block(bible)}", ""]
    return out


def user_prompt(novel: Novel, number: int, bible: Bible, previous: Previous | None) -> str:
    language = novel.language
    continuing = previous is not None
    title = " ".join(novel.title.split())
    out = _context(novel, number, bible, previous)
    before = part_phrase(previous.number, language) if previous else ""
    first = (
        f'act "bridge": how {before} ended, in one sentence of at most {BRIDGE_MAX} characters'
        if continuing
        else 'act "setup": who, where and the situation'
    )
    connector = "of" if language == "en" else "novel"
    out += [
        "THE WORDS OF THIS PART:",
        f'- hook: starts with exactly these words: "{hook_opening(novel, number, continuing)}..."',
        f"- beat 1: {first}",
        f'- cta: names "{part_phrase(number, language)} {connector} {title}" and the link in bio, then the'
        f' follow line for "{part_phrase(number + 1, language)}"',
        "",
        f"LIMITS: everything spoken (hook + beats + poll + cta) together at most {max_chars()} characters"
        f" (about {MAX_SECONDS} seconds read aloud). Hook at most {HOOK_MAX} characters, the opening"
        " included.",
        "Write the part as one JSON object.",
    ]
    return "\n".join(out)


def video_prompt(
    novel: Novel, number: int, bible: Bible, previous: Previous | None, turns: list[Turn]
) -> str:
    """The request for a part made from the user's own video: the context, then what they said."""
    out = _context(novel, number, bible, previous)
    out += [
        "WHAT THEY SAID IN THEIR VIDEO (the transcript, turn by turn, with seconds; every word goes"
        " into the part, in this order):",
        *(f"[{t.start:.1f}-{t.end:.1f}s] {t.text}" for t in turns),
        "",
        "Turn their words into the part as one JSON object.",
    ]
    return "\n".join(out)


# ---- the checks -------------------------------------------------------------------------------


def spoken_chars(out: StoryOut) -> int:
    return sum(len(t) for t in [out.hook, *(b.text for b in out.beats), out.poll.text, out.cta])


def _shown(out: StoryOut) -> set[str]:
    ids: set[str] = set()
    for b in out.beats:
        ids.update(b.show.characters)
        if b.then.at.strip():
            ids.update(b.then.show.characters)
    for p in out.props:
        ids.update(p.refs)
    return ids


def validate(
    out: StoryOut, novel: Novel, number: int, bible: Bible, continuing: bool, heard: list[str] | None = None
) -> list[str]:
    """What a repair round must fix (empty = usable). `heard`: for a part made from the user's own
    video, the words they said, which replace the rules for what to say."""
    p: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            p.append(msg)

    w = wording(novel.language, novel.narration)
    language = novel.language
    bible_chars, bible_props = set(bible.characters), set(bible.props)
    new_chars = {c.id for c in out.characters}
    variants = {v.id: v for v in out.variants}
    props = {x.id: x for x in out.props}
    photos = {x.id for x in out.photos}
    people = bible_chars | new_chars | set(variants)
    names = {cid: c.name for cid, c in bible.characters.items()} | {c.id: c.name for c in out.characters}

    need(bool(out.chapter_title.strip()), "write 'chapter_title'")
    for c in out.characters:
        need(bool(ID_RE.match(c.id)), f"character id {c.id!r} must be lowercase snake_case")
        need(
            c.id not in bible_chars,
            f"character {c.id!r} is already in the bible: use it, do not redescribe it",
        )
        need(len(c.description) >= 40, f"character {c.id!r}: description too short (age, build, face, hair)")
        need(
            len(c.outfit.strip()) >= 15,
            f"character {c.id!r}: write its 'outfit' (what it wears in this chapter)",
        )
        need(bool(c.label.strip()), f"character {c.id!r}: missing label")
        need(bool(c.subject.strip()), f"character {c.id!r}: missing subject (e.g. 'woman', 'old man', 'cat')")
    looks: set[str] = set()
    for x in out.looks:
        need(
            x.id in bible_chars,
            f"looks: {x.id!r} is not a bible character (a new character's outfit goes in its entry)",
        )
        need(x.id not in looks, f"looks: {x.id!r} is listed twice")
        need(len(x.outfit.strip()) >= 15, f"looks {x.id!r}: describe what they wear in this chapter")
        looks.add(x.id)
    undressed = sorted((_shown(out) & bible_chars) - looks)
    need(
        not undressed,
        f"add a 'looks' entry for every bible character the chapter shows: {', '.join(undressed)}",
    )
    for vid, v in variants.items():
        need(bool(ID_RE.match(vid)), f"variant id {vid!r} must be lowercase snake_case")
        need(v.base in bible_chars | new_chars, f"variant {vid!r}: base {v.base!r} is not a character")
        need(len(v.change) >= 10, f"variant {vid!r}: describe the change")
    for pid, x in props.items():
        need(bool(ID_RE.match(pid)), f"prop id {pid!r} must be lowercase snake_case")
        need(
            len(x.refs) <= 2 and all(r in people for r in x.refs),
            f"prop {pid!r}: refs must be at most two character ids",
        )
        need(
            x.people >= len(x.refs), f"prop {pid!r}: people is the number of figures drawn, at least its refs"
        )
        need(len(x.description) >= 15, f"prop {pid!r}: describe it")
        if not (x.refs or x.backdrop or x.framing == "close-up" or x.people):
            need(bool(x.subject.strip()), f"prop {pid!r}: set 'subject' (a short noun naming the object)")
    for x in out.photos:
        need(len(x.description) >= 20, f"photo {x.id!r}: describe the place")

    video = heard is not None  # made from the user's own video: the words are what they said
    if video:
        need(bool(out.hook.strip()), "the hook is what they say first, before the story starts")
        need(
            2 <= len(out.beats) <= 40,
            f"{len(out.beats)} beats; split what they said after the hook into beats of 40-190 characters",
        )
    else:
        opening = hook_opening(novel, number, continuing)
        need(
            20 <= len(out.hook) <= HOOK_MAX + 10,
            f"the hook is {len(out.hook)} characters; keep it 20-{HOOK_MAX}",
        )
        need(
            opens_correctly(out.hook, opening), f'the hook must start with "{opening}..." and then the punch'
        )
        need(6 <= len(out.beats) <= 24, f"{len(out.beats)} beats; write 8 to 20")
    for i, b in enumerate(out.beats, 1):
        if video:
            need(len(b.text) <= 320, f"beat {i} is {len(b.text)} characters: split it at a comma or a clause")
        else:
            need(15 <= len(b.text) <= 220, f"beat {i}: text is {len(b.text)} characters; keep 40-190")
        need(
            b.speaker == "narrator" or b.speaker in people,
            f"beat {i}: speaker {b.speaker!r} is not narrator or a character id",
        )
        need(len(b.see) >= 8, f"beat {i}: write 'see' (who and what the viewer sees) before 'show'")
        at = b.then.at.strip()
        shows = (b.show, b.then.show) if at else (b.show,)
        if at:
            spoken = b.text.lower()
            need(
                at.lower() in spoken and not spoken.startswith(at.lower()),
                f"beat {i}: then.at must be words copied exactly from the middle of the beat's text",
            )
        for show in (b.show, b.then.show) if at else (b.show,):
            _check_show(i, show, people, props, bible_props, photos, need)
        if b.speaker != "narrator" and b.speaker in people:  # the voiced character is on screen
            who = {c: v.base for c, v in variants.items()}
            on = {who.get(c, c) for s in shows for c in s.characters}
            on |= {who.get(r, r) for s in shows if s.prop in props for r in props[s.prop].refs}
            person = who.get(b.speaker, b.speaker)
            name = (names.get(person) or person).casefold()
            texting = any(
                name and name in m.sender.casefold() for s in shows for m in s.chat
            )  # their message
            need(
                person in on or texting,
                f"beat {i}: {b.speaker!r} is quoted but not on screen: show them while their words are said",
            )
    if video:
        if out.poll.text.strip():
            need(bool(out.poll.a and out.poll.b), "the poll they said needs its two options, a and b")
            need(len(out.poll.a) <= 30 and len(out.poll.b) <= 30, "poll options at most 28 characters")
        return p + (said_problems(out, heard) if heard else [])  # no transcript: nothing to compare
    need(bool(out.poll.text and out.poll.a and out.poll.b), "poll needs text, a and b")
    need(len(out.poll.a) <= 30 and len(out.poll.b) <= 30, "poll options at most 28 characters")
    need(bool(out.cta.strip()), "missing cta")
    caps = re.findall(
        r"\b[A-Z]{4,}\b", " ".join([out.hook, *(b.text for b in out.beats), out.poll.text, out.cta])
    )
    need(
        not caps,
        f"no ALL-CAPS words in spoken text (found {', '.join(caps[:4])}); caps only in chat bubbles and tags",
    )
    total = spoken_chars(out)
    need(total <= max_chars(), f"spoken text is {total} characters; cut it to at most {max_chars()}")

    if out.beats:  # the series format
        acts = [b.act for b in out.beats]
        first = "bridge" if continuing else "setup"
        need(acts[0] == first, f'beat 1 is the {first}: give it act "{first}"')
        need("bridge" not in acts[1:], 'only beat 1 is the "bridge"')
        need(
            acts[-1] == "cliffhanger",
            'the last beat is the "cliffhanger": end on this part\'s final moment, left open',
        )
        if continuing and acts[0] == "bridge":
            need(
                len(out.beats[0].text) <= BRIDGE_MAX + 10,
                f"beat 1 (the bridge) is {len(out.beats[0].text)} characters:"
                f" one sentence of at most {BRIDGE_MAX}",
            )
    need(
        bool(w.comment_re.search(out.poll.text)),
        f"the poll ends with the invitation to comment ({w.poll_shape})",
    )
    need(
        len(out.poll.text) <= POLL_MAX + 10,
        f"the poll is {len(out.poll.text)} characters; keep it to {POLL_MAX}",
    )
    words = number_words(number, language)
    need(
        bool(re.search(rf"\bpart\s+{re.escape(words)}\b", out.cta, re.I)),
        f'the cta names this part: "{part_phrase(number, language)}"',
    )
    need(bool(w.link_re.search(out.cta)), "the cta says the whole part is at the link in bio")
    need(len(out.cta) <= CTA_MAX + 10, f"the cta is {len(out.cta)} characters; keep it to {CTA_MAX}")
    spoken = [
        ("hook", out.hook),
        *((f"beat {i}", b.text) for i, b in enumerate(out.beats, 1)),
        ("poll", out.poll.text),
        ("cta", out.cta),
    ]
    wrong = [where for where, text in spoken if w.forbidden_re.search(text)]
    need(not wrong, f'say "part", never "{w.forbidden}" ({", ".join(wrong[:4])})')
    return p


MISSING_RUN = 4  # words in a row they said that no part of the script has: a stretch left out
OFF_WORDS = 0.75  # a piece of the script with less of its words heard is not what they said


def said_problems(out: StoryOut, heard: list[str]) -> list[str]:
    """For a part made from the user's video: its words must be what they said, all of it, in
    their order (the pictures are timed by lining the two up)."""
    pieces = [
        ("the hook", out.hook),
        *((f"beat {i}", b.text) for i, b in enumerate(out.beats, 1)),
        ("the poll", out.poll.text),
        ("the cta", out.cta),
    ]
    script = Text.of([text.split() for _, text in pieces])
    said = Text.of([heard])
    al = align(script.tokens, said.tokens)
    problems: list[str] = []
    for index, (where, text) in enumerate(pieces):
        own = [k for k, owner in enumerate(script.owner) if owner == index]
        hits = sum(1 for k in own if al.script_to_heard[k] is not None)
        if own and len(own) - hits >= MISSING_RUN and hits < OFF_WORDS * len(own):
            problems.append(f'{where} ("{_short(text)}") is not what they said: copy their words, in order')
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for k, match in enumerate([*al.heard_to_script, 0]):  # the 0 closes a run at the end
        if match is None:
            start = k if start is None else start
            continue
        if start is not None and k - start >= MISSING_RUN:
            runs.append((start, k))
        start = None
    for a, b in runs[:3]:
        words = said.words[said.word_of[a] : said.word_of[b - 1] + 1]
        problems.append(
            f'they said "{_short(" ".join(words))}", which is in no part of the script: put every word'
            " they said in the hook, a beat, the poll or the cta, in their order"
        )
    if len(runs) > 3:
        problems.append(f"{len(runs) - 3} more stretches of what they said are missing")
    return problems


def _short(text: str, words: int = 12) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _check_show(
    i: int, show: ShowOut, people: set[str], props: dict, bible_props: set[str], photos: set[str], need
) -> None:
    need(len(show.characters) <= 2, f"beat {i}: show at most two characters")
    for cid in show.characters:
        need(cid in people, f"beat {i}: character {cid!r} is not in the bible, characters or variants")
    main = [
        k
        for k, v in (
            ("prop", show.prop),
            ("photo", show.photo),
            ("chat", show.chat),
            ("note", show.note.text),
        )
        if v
    ]
    need(len(main) <= 1, f"beat {i}: show at most one of prop/photo/chat/note (got {', '.join(main)})")
    if show.prop:
        need(show.prop in props or show.prop in bible_props, f"beat {i}: prop {show.prop!r} is not defined")
        in_scene = set(props[show.prop].refs if show.prop in props else []) & set(show.characters)
        need(
            not in_scene,
            f"beat {i}: {', '.join(sorted(in_scene))} would appear twice (standing and in the scene prop)",
        )
    if show.photo:
        need(show.photo in photos, f"beat {i}: photo {show.photo!r} is not defined")
    need(
        len(show.chat) <= 2 and all(m.sender and len(m.text) <= 90 for m in show.chat),
        f"beat {i}: chat is at most two messages of at most 90 characters, each with 'sender'",
    )
    need(len(show.note.text) <= 120, f"beat {i}: a note is at most 120 characters")
    need(len(show.tag) <= 24, f"beat {i}: tag at most 24 characters")


# ---- from the answer to the stored story and its takes ----------------------------------------


def _show(s: ShowOut) -> StoryShow:
    return StoryShow(
        characters=[slug(c) for c in s.characters][:2],
        prop=slug(s.prop, "") if s.prop else "",
        photo=slug(s.photo, "") if s.photo else "",
        chat=[ChatMessage(sender=m.sender[:40], text=m.text[:120]) for m in s.chat if m.text][:2],
        note=StoryNote(text=" ".join(s.note.text.split())[:160], style=s.note.style),
        tag=" ".join(s.tag.split()).upper()[:24],
    )


def to_story(
    out: StoryOut, number: int, continuing: bool, problems: list[str], from_video: bool = False
) -> Story:
    beats = [
        Beat(
            act=b.act,
            text=" ".join(b.text.split()),
            speaker=slug(b.speaker, "narrator") if b.speaker != "narrator" else "narrator",
            see=" ".join(b.see.split()),
            direction=" ".join(b.direction.split())[:120],
            show=_show(b.show),
            switch=StorySwitch(at=" ".join(b.then.at.split()), show=_show(b.then.show))
            if b.then.at.strip()
            else None,
        )
        for b in out.beats
        if b.text.strip()
    ]
    if not beats:
        raise PipelineError("the script has no beats")
    return Story(
        part=number,
        continuing=continuing,
        chapter_title=" ".join(out.chapter_title.split())[:120],
        hook=" ".join(out.hook.split()),
        hook_direction=" ".join(out.hook_direction.split())[:120],
        beats=beats,
        poll=Poll(text=" ".join(out.poll.text.split()), a=out.poll.a.strip()[:40], b=out.poll.b.strip()[:40]),
        cta=" ".join(out.cta.split()),
        characters=[
            StoryCharacter(
                id=slug(c.id or c.name, "character"),
                name=c.name.strip()[:80] or c.id,
                label=(c.label.strip().lower() or c.name.strip().lower())[:40],
                role=c.role.strip()[:160],
                description=" ".join(c.description.split())[:800],
                outfit=" ".join(c.outfit.split())[:600],
                subject=" ".join(c.subject.split())[:40] or "person",
                slot=c.slot,
            )
            for c in out.characters
            if c.id or c.name
        ],
        looks=[StoryLook(id=slug(x.id), outfit=" ".join(x.outfit.split())[:600]) for x in out.looks if x.id],
        variants=[
            StoryVariant(
                id=slug(v.id),
                base=slug(v.base),
                change=" ".join(v.change.split())[:400],
                persistent=v.persistent,
            )
            for v in out.variants
            if v.id and v.base
        ],
        props=[
            StoryProp(
                id=slug(x.id),
                description=" ".join(x.description.split())[:800],
                subject=" ".join(x.subject.split())[:60],
                shape=x.shape,
                size=x.size,
                refs=[slug(r) for r in x.refs][:2],
                people=max(0, min(8, x.people)),
                framing=x.framing,
                backdrop=x.backdrop,
                recurring=x.recurring,
            )
            for x in out.props
            if x.id
        ],
        photos=[
            StoryPhoto(
                id=slug(x.id), description=" ".join(x.description.split())[:800], title=x.title.strip()[:80]
            )
            for x in out.photos
            if x.id
        ],
        bible_notes=[
            StoryBibleNote(id=slug(x.id), note=" ".join(x.note.split())[:400])
            for x in out.bible_notes
            if x.id and x.note
        ],
        problems=problems,
        from_video=from_video,
    )


# The purposes of the takes that are not beats. OUTRO is the poll and the call to action in one
# take, as parts written before one take per beat were recorded.
HOOK, POLL, CTA, OUTRO = "hook", "poll", "call to action", "poll + call to action"


def _direction(parts: list[str]) -> str:
    seen = [p for p in dict.fromkeys(x for x in parts if x)]
    return "; ".join(seen)[:300]


def assign_takes(story: Story) -> list[Scene]:
    """One take per line of the part: the hook, each beat, the poll, the call to action. A
    take is short and its screen is timed by its own recording. Sets each beat's `take` and
    returns the scenes to record, without takes attached."""
    for number, beat in enumerate(story.beats, 2):  # t1 is the hook
        beat.take = f"t{number}"
    return scenes_for(story)


def scenes_for(story: Story, outro: bool = False) -> list[Scene]:
    """The scenes to record, from the takes the beats are already in: the hook, a scene per
    take, then the poll and the call to action. Parts written before one take per beat may
    group several beats in a take and, with `outro`, keep the poll and the call to action in
    one take."""
    scenes = [
        Scene(id="t1", purpose=HOOK, lines=(story.hook or "…")[:600], direction=story.hook_direction[:300])
    ]
    order: list[str] = []
    for beat in story.beats:
        if beat.take not in order:
            order.append(beat.take)
    for take_id in order:
        group = [b for b in story.beats if b.take == take_id]
        scenes.append(
            Scene(
                id=take_id,
                purpose=group[0].act if group[0].act in ACTS else "rise",
                lines=(" ".join(b.text for b in group) or "…")[:600],
                direction=_direction([b.direction for b in group]),
            )
        )
    n = len(order) + 2
    if outro:
        lines = f"{story.poll.text} {story.cta}".strip() or "…"
        scenes.append(Scene(id=f"t{n}", purpose=OUTRO, lines=lines[:600]))
        return scenes
    for purpose, said in ((POLL, story.poll.text), (CTA, story.cta)):
        if said or not story.from_video:  # a part made from a video has them only if they were said
            scenes.append(Scene(id=f"t{n}", purpose=purpose, lines=(said or "…")[:600]))
            n += 1
    return scenes


def _kind(purpose: str) -> str:
    return purpose if purpose in (HOOK, POLL, CTA, OUTRO) else "beat"


def takes_script(story: Story, title: str, language: str, old: Script | None, regroup: bool = True) -> Script:
    """The scenes to record for `story`. With `regroup` (a new script) every beat gets its own
    take and no recording is kept; otherwise (an edit) the takes stay as they were and each
    scene keeps its recording: the user re-records the ones whose words they changed."""
    if regroup:
        scenes = assign_takes(story)
    else:
        outro = bool(old and old.scenes and old.scenes[-1].purpose == OUTRO)
        scenes = scenes_for(story, outro=outro)
        previous = {s.id: s for s in (old.scenes if old else []) if s.take}
        for scene in scenes:
            before = previous.get(scene.id)
            if before is not None and _kind(before.purpose) == _kind(scene.purpose):
                scene.take = before.take
    return Script(title=title[:120] or DEFAULT_TITLE, language=language, scenes=scenes, entities=[])


def reel_title(novel: Novel, story: Story) -> str:
    return f"{novel.title} - Part {story.part}: {story.chapter_title}"[:120]


def _show_out(s: StoryShow) -> ShowOut:
    return ShowOut(
        characters=list(s.characters),
        prop=s.prop,
        photo=s.photo,
        chat=[ChatOut(sender=m.sender, text=m.text) for m in s.chat],
        note=NoteOut(text=s.note.text, style=s.note.style),
        tag=s.tag,
    )


def story_to_out(story: Story) -> StoryOut:
    """The stored story in the answer's shape, so an edited one goes through the same checks."""
    return StoryOut(
        chapter_title=story.chapter_title,
        hook=story.hook,
        hook_direction=story.hook_direction,
        beats=[
            BeatOut(
                act=b.act if b.act in ACTS else "rise",
                text=b.text,
                speaker=b.speaker,
                see=b.see,
                direction=b.direction,
                show=_show_out(b.show),
                then=ThenOut(at=b.switch.at, show=_show_out(b.switch.show)) if b.switch else ThenOut(),
            )
            for b in story.beats
        ],
        poll=PollOut(text=story.poll.text, a=story.poll.a, b=story.poll.b),
        cta=story.cta,
        characters=[CharacterOut(**c.model_dump()) for c in story.characters],
        looks=[LookOut(**x.model_dump()) for x in story.looks],
        variants=[VariantOut(**v.model_dump()) for v in story.variants],
        props=[PropOut(**x.model_dump()) for x in story.props],
        photos=[PhotoOut(**x.model_dump()) for x in story.photos],
        bible_notes=[BibleNoteOut(**x.model_dump()) for x in story.bible_notes],
    )


def apply_edit(
    project: Project,
    novel: Novel,
    *,
    chapter_title: str,
    hook: str,
    hook_direction: str,
    beats: list[tuple[str, str]],
    poll: Poll,
    cta: str,
) -> None:
    """The user's edits to the spoken words (and delivery notes) of a part. The checks run
    again; every recorded take is kept (the user re-records a take whose words they changed)."""
    story = project.story
    if story is None:
        raise PipelineError("write the part first")
    if len(beats) != len(story.beats):
        raise PipelineError("the edit must keep every beat")
    story.chapter_title = " ".join(chapter_title.split())[:120] or story.chapter_title
    story.hook = " ".join(hook.split())
    story.hook_direction = " ".join(hook_direction.split())[:120]
    for beat, (text, direction) in zip(story.beats, beats, strict=True):
        beat.text = " ".join(text.split())
        beat.direction = " ".join(direction.split())[:120]
        if beat.switch and beat.switch.at.lower() not in beat.text.lower():
            beat.switch = None  # its words are gone: the picture no longer changes inside the beat
    story.poll = Poll(text=" ".join(poll.text.split()), a=poll.a.strip()[:40], b=poll.b.strip()[:40])
    story.cta = " ".join(cta.split())
    bible = novel.bible.before(story.part)
    heard = None
    if story.from_video:  # its words are checked against what was said, if the transcript is there
        turns = project.transcript.turns if project.transcript else []
        heard = [w.text for t in turns for w in t.words]
    story.problems = validate(story_to_out(story), novel, story.part, bible, story.continuing, heard)
    project.script = takes_script(story, project.title, novel.language, project.script, regroup=False)


# ---- the job ----------------------------------------------------------------------------------


def previous_part(ctx: JobContext, novel: Novel, number: int) -> Previous | None:
    earlier = [c for c in novel.chapters if c.number < number]
    if not earlier:
        return None
    prev = max(earlier, key=lambda c: c.number)
    beats: list[str] = []
    title = prev.title
    if prev.project_id:
        try:
            other = ctx.services.db.get_project(prev.project_id)
        except LookupError:
            other = None
        if other is not None and other.story is not None:
            beats = [b.text for b in other.story.beats]
            title = title or other.story.chapter_title
    return Previous(number=prev.number, title=title, text=prev.text, beats=beats)


def write_story(ctx: JobContext, turns: list[Turn] | None = None) -> Story:
    """Write the part from the chapter, or, with `turns` (the transcript of the user's own video
    of the part), make it from what they said: their words split into beats, the pictures
    planned for them."""
    project = ctx.project()
    if project.novel_id is None or project.chapter is None:
        raise PipelineError("this reel is not a novel chapter")
    novel = ctx.services.db.get_novel(project.novel_id)
    number = project.chapter
    if novel.chapter(number) is None:
        raise PipelineError(f"the novel has no chapter {number}")
    from_video = turns is not None
    heard = [w.text for t in turns or [] for w in t.words] if from_video else None
    if from_video and not heard:
        raise PipelineError(
            "no speech was recognised in the video, so there is nothing to make the part from"
        )
    bible = novel.bible.before(number)
    previous = previous_part(ctx, novel, number)
    continuing = previous is not None
    model = ctx.settings.script_model
    name = text_model_name(model)
    what = f"making part {number} from your video" if from_video else f"writing part {number}"
    ctx.log(
        f"{name}: {what} of {novel.title!r} ({novel.language}, {novel.narration}, effort"
        f" {ctx.settings.script_effort}); bible: {len(bible.characters)} characters,"
        f" {len(bible.props)} props from earlier chapters"
    )
    request = (
        video_prompt(novel, number, bible, previous, turns or [])
        if from_video
        else user_prompt(novel, number, bible, previous)
    )
    messages: list[dict] = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": request}],
        }
    ]
    best: tuple[StoryOut, list[str]] | None = None
    best_rank = (1 << 30, 0)  # (format problems, storyboard mismatches): fewer is better
    reviewing = story_review.enabled(ctx)
    reviews = 0
    effort = ctx.settings.script_effort
    if from_video and effort in TEXT_EFFORTS:  # splitting their words needs less thinking than writing
        effort = TEXT_EFFORTS[min(TEXT_EFFORTS.index(effort), TEXT_EFFORTS.index(VIDEO_EFFORT))]
    rounds = REPAIR_ROUNDS + (REVIEW_ROUNDS if reviewing else 0)
    for round_no in range(rounds + 1):
        ctx.check()
        if round_no and best is not None:
            ctx.log(f"repair round {round_no}: {len(best[1])} problem(s) to fix")
        elif round_no:
            ctx.log(f"round {round_no}: trying again")
        try:
            result = ctx.client.responses(
                {
                    "model": model,
                    "store": False,
                    "instructions": system_prompt(novel, from_video),
                    "input": messages,
                    "reasoning": {"effort": effort},
                    "max_output_tokens": ctx.settings.max_output_tokens,
                    "text": text_format("novel_part", StoryOut),
                },
                cancel=ctx.cancelled,
            )
        except MetaAPIError as exc:
            if not exc.output_limit:
                raise
            ctx.spend_text(model, exc.usage)
            # The same request would run as long again: the next try thinks one level less.
            lower = TEXT_EFFORTS[max(0, TEXT_EFFORTS.index(effort) - 1)] if effort in TEXT_EFFORTS else effort
            ctx.log(
                f"the answer ran past {ctx.settings.max_output_tokens} output tokens and was stopped"
                + (f"; trying with effort {lower}" if lower != effort and best is None else "")
            )
            effort = lower
            if best is not None:
                break
            continue
        ctx.spend_text(model, result.usage)
        ctx.log(
            f"answer in {result.seconds:.0f}s ({result.input_tokens} in, {result.output_tokens} out tokens)"
        )
        try:
            out, missing = parse_output(StoryOut, result.text)
        except (OutputError, ValidationError) as exc:
            problems = [
                f"the answer could not be read ({exc.__class__.__name__}): answer with the JSON object"
            ]
            out = None
        else:
            problems = validate(out, novel, number, bible, continuing, heard)
            if missing:
                problems.insert(0, f"fill in every field (missing: {', '.join(missing)})")
        review: list[str] = []  # a script in the right shape gets one look at its pictures
        if out is not None and not problems and reviewing and reviews < REVIEW_ROUNDS and round_no < rounds:
            reviews += 1
            ctx.log("storyboard review: does every picture show what the words say?")
            review = story_review.review_story(ctx, novel, number, out, bible)
        rank = (len(problems), len(review))
        if out is not None and (best is None or rank < best_rank):
            best, best_rank = (out, problems + review), rank
        if not problems and not review:
            break
        fix = (
            "Fix these problems and answer with the whole corrected JSON object:\n- "
            + "\n- ".join(problems[:30])
            if problems
            else REVIEW_FIX + "\n- " + "\n- ".join(review)
        )
        messages += [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": result.text}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": fix,
                    }
                ],
            },
        ]
    if best is None:
        raise PipelineError(f"{name} did not return a usable part script; try again")
    out, problems = best
    story = to_story(out, number, continuing, problems, from_video)
    for item in problems:
        ctx.log(f"  still to fix: {item}")
    ctx.log(
        f"part {number}: {len(story.beats)} beats, {spoken_chars(out)} spoken characters"
        f" (~{spoken_chars(out) / READ_CHARS_PER_SECOND:.0f}s read aloud),"
        f" {len(story.characters)} new characters"
    )
    removed: list[str] = []

    def save(p: Project) -> None:
        removed.extend(s.take.key for s in (p.script.scenes if p.script else []) if s.take)
        p.story = story
        p.script = takes_script(story, reel_title(novel, story), novel.language, None)
        if p.title in ("", DEFAULT_TITLE) or p.title.startswith(f"{novel.title} - Part"):
            p.title = reel_title(novel, story)
        if from_video:  # the video is the recording: keep it and its transcript, plan the pictures anew
            p.analysis, p.part_faces = None, {}
        else:
            p.invalidate_media()

    ctx.update(save)
    for key in removed:
        ctx.files.delete(key)
    return story
