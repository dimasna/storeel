"""Caption pages: the transcript's words grouped into short screens of text, Reels-style."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Turn

MAX_WORDS = 5
MAX_CHARS = 24
BREAK_GAP = 0.5  # a pause this long starts a new page
HOLD = 0.35  # a page stays this long after its last word, unless the next one starts
SENTENCE_END = re.compile(r"[.!?…]['\"”’)]*$")
CLAUSE_END = re.compile(r"[,;:—–]['\"”’)]*$")
TRAILING = re.compile(r"[,.;:…]+$")


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start: float
    end: float
    emphasis: bool = False


@dataclass(frozen=True)
class CaptionPage:
    words: tuple[CaptionWord, ...]
    start: float
    end: float


def display_text(token: str, case: str) -> str:
    """The word as shown: commas and full stops dropped (question and exclamation marks kept)."""
    text = TRAILING.sub("", token.strip())
    return text.upper() if case == "upper" else text


def build_pages(
    turns: list[Turn],
    case: str = "original",
    max_words: int = MAX_WORDS,
    max_chars: int = MAX_CHARS,
    clauses: bool = False,
) -> list[CaptionPage]:
    """The pages, in order. A pause or a sentence's end starts a new page; with `clauses`, so
    does a comma (the word-by-word styles read a phrase at a time)."""
    groups: list[list[CaptionWord]] = []
    for turn in turns:
        current: list[CaptionWord] = []
        for word in turn.words:
            text = display_text(word.text, case)
            if not text:
                continue
            caption = CaptionWord(text, word.start, word.end, word.emphasis)
            if current:
                chars = sum(len(w.text) + 1 for w in current) + len(text)
                pause = caption.start - current[-1].end
                if pause > BREAK_GAP:
                    groups.append(current)
                    current = []
                elif len(current) >= max_words or chars > max_chars:
                    # Don't end a page on a short word ("di", "to", "the"): carry it over.
                    carry = []
                    if len(current) >= 3 and len(current[-1].text) <= 3 and current[-1].text.isalpha():
                        carry = [current.pop()]
                    groups.append(current)
                    current = carry
            current.append(caption)
            if (len(current) >= 2 and SENTENCE_END.search(word.text)) or (
                clauses and CLAUSE_END.search(word.text)
            ):
                groups.append(current)
                current = []
        if current:
            groups.append(current)

    pages: list[CaptionPage] = []
    for index, words in enumerate(groups):
        start = words[0].start
        end = words[-1].end + HOLD
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start)
        pages.append(CaptionPage(tuple(words), start, max(end, words[-1].end)))
    return pages


# Words that are never the one to stress, when the words come without Muse Spark's choice.
_PLAIN_WORDS = (
    "the a an and or but of to in on at for with from that this these those was were is are be "
    "been have has had not you your they them their there then than when what which who because "
    "yang dan di ke dari itu ini dengan untuk karena tapi juga sudah akan bisa tidak nggak gak "
    "aku kamu dia mereka kita kami saya sama lagi aja udah buat"
)
PLAIN = frozenset(_PLAIN_WORDS.split())


def stressed(pages: list[CaptionPage], picked: bool) -> list[list[bool]]:
    """Which words of each page to stress: Muse Spark's choice, or, for a transcript it never
    looked at, the longest word of a page of three or more (six letters at least, not a filler)."""
    if picked or any(w.emphasis for page in pages for w in page.words):
        return [[w.emphasis for w in page.words] for page in pages]
    out = []
    for page in pages:
        flags = [False] * len(page.words)
        candidates = [
            (len(w.text), k)
            for k, w in enumerate(page.words)
            if len(w.text) >= 6 and w.text.isalpha() and w.text.lower() not in PLAIN
        ]
        if len(page.words) >= 3 and candidates:
            flags[max(candidates)[1]] = True
        out.append(flags)
    return out
