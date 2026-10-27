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
TRAILING = re.compile(r"[,.;:…]+$")


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class CaptionPage:
    words: tuple[CaptionWord, ...]
    start: float
    end: float


def display_text(token: str, case: str) -> str:
    """The word as shown: commas and full stops dropped (question and exclamation marks kept)."""
    text = TRAILING.sub("", token.strip())
    return text.upper() if case == "upper" else text


def build_pages(turns: list[Turn], case: str = "original") -> list[CaptionPage]:
    groups: list[list[CaptionWord]] = []
    for turn in turns:
        current: list[CaptionWord] = []
        for word in turn.words:
            text = display_text(word.text, case)
            if not text:
                continue
            caption = CaptionWord(text, word.start, word.end)
            if current:
                chars = sum(len(w.text) + 1 for w in current) + len(text)
                pause = caption.start - current[-1].end
                if pause > BREAK_GAP:
                    groups.append(current)
                    current = []
                elif len(current) >= MAX_WORDS or chars > MAX_CHARS:
                    # Don't end a page on a short word ("di", "to", "the"): carry it over.
                    carry = []
                    if len(current) >= 3 and len(current[-1].text) <= 3 and current[-1].text.isalpha():
                        carry = [current.pop()]
                    groups.append(current)
                    current = carry
            current.append(caption)
            if len(current) >= 2 and SENTENCE_END.search(word.text):
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
