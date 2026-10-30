"""Line up what was said with what the script says, word by word.

The transcript holds the words the user said (their times estimated inside each speech turn);
the script holds the words they were meant to say. Matching the two (difflib's longest runs of
agreeing words, kept only where at least two words in a row agree, so a common word on its own
proves nothing) gives three things: where each line of the script starts in one video of the
whole part, how much of each line was actually said, and which caption words differ from the
script (a misheard name, a word said twice).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import Match, SequenceMatcher

TOKEN = re.compile(r"[^\W_]+")  # letters and digits; punctuation, quotes and hyphens split words
MIN_RUN = 2  # words in a row that must agree for a match to count
NEAR = 3  # a lone agreeing word counts when matches lie this close on both sides
QUOTES = str.maketrans("", "", '"“”')


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text)]


@dataclass
class Alignment:
    """For each script token the heard token it matches (or None), and the other way round."""

    script_to_heard: list[int | None]
    heard_to_script: list[int | None]


def align(script: list[str], heard: list[str]) -> Alignment:
    blocks = [b for b in SequenceMatcher(None, script, heard, autojunk=False).get_matching_blocks() if b.size]
    runs = [b for b in blocks if b.size >= MIN_RUN]
    keep = list(runs)
    # A lone agreeing word counts between two runs (the words around it were misheard); the
    # start and the end of both texts count as runs.
    edges = [Match(0, 0, 0), *runs, Match(len(script), len(heard), 0)]
    for b in blocks:
        if b.size >= MIN_RUN:
            continue
        x = [r for r in edges if r.a + r.size <= b.a and r.b + r.size <= b.b][-1]
        y = next(r for r in edges if r.a >= b.a + b.size and r.b >= b.b + b.size)
        gaps = (b.a - x.a - x.size, b.b - x.b - x.size, y.a - b.a - b.size, y.b - b.b - b.size)
        if max(gaps) <= NEAR:
            keep.append(b)
    script_to_heard: list[int | None] = [None] * len(script)
    heard_to_script: list[int | None] = [None] * len(heard)
    for b in keep:
        for k in range(b.size):
            script_to_heard[b.a + k] = b.b + k
            heard_to_script[b.b + k] = b.a + k
    return Alignment(script_to_heard, heard_to_script)


@dataclass
class Text:
    """Some text as words (what is shown) and tokens (what is matched), each token knowing its word."""

    words: list[str]
    tokens: list[str]
    word_of: list[int]  # per token
    owner: list[int]  # per token: which piece of text it came from (a scene, a turn)

    @classmethod
    def of(cls, pieces: list[list[str]]) -> Text:
        """`pieces`: the words of each scene (or turn), in order."""
        text = cls([], [], [], [])
        for index, piece in enumerate(pieces):
            for word in piece:
                for token in tokens(word):
                    text.tokens.append(token)
                    text.word_of.append(len(text.words))
                    text.owner.append(index)
                text.words.append(word)
        return text


def said_share(script_tokens: list[str], heard_tokens: list[str]) -> float:
    """How much of a line was said: the share of its words that match what was heard."""
    if not script_tokens:
        return 1.0
    matched = align(script_tokens, heard_tokens).script_to_heard
    return sum(1 for h in matched if h is not None) / len(script_tokens)


def line_shares(texts: list[str], heard_words: list[str]) -> list[float]:
    """How much of each line was said, for lines said in order in one recording."""
    script = Text.of([t.split() for t in texts])
    heard = [token for word in heard_words for token in tokens(word)]
    matches = align(script.tokens, heard).script_to_heard
    totals, hits = [0] * len(texts), [0] * len(texts)
    for k, owner in enumerate(script.owner):
        totals[owner] += 1
        hits[owner] += matches[k] is not None
    return [hits[i] / totals[i] if totals[i] else 1.0 for i in range(len(texts))]


@dataclass
class CaptionNote:
    """How one caption turn compares with the script."""

    share: float  # of its words, how many match the script
    differs: list[str]  # the words that are not in the script there (a misheard name, a repeat)
    script: str  # the turn as the script words it ("" when it does not follow the script closely)


CLOSE = 0.5  # a turn with less of its words in the script is not compared word by word
MAX_ODD_RUN = 3  # nor one with more words than this in a row that are not in the script (ad-libbed)


def caption_notes(scenes: list[str], turns: list[list[str]]) -> list[CaptionNote | None]:
    """For each caption turn (its words), where it differs from the script `scenes` (their text);
    None for a turn that matches the script exactly. Only a turn that follows the script, with a
    few odd words here and there (a misheard name, a word said twice), is compared word by word;
    a turn said in the user's own words gets its share only, since the script's words would not
    caption what they said."""
    script = Text.of([s.split() for s in scenes])
    heard = Text.of(turns)
    al = align(script.tokens, heard.tokens)
    notes: list[CaptionNote | None] = []
    for index, words in enumerate(turns):
        own = [k for k, owner in enumerate(heard.owner) if owner == index]
        matched = [k for k in own if al.heard_to_script[k] is not None]
        if len(matched) == len(own):
            notes.append(None)
            continue
        share = len(matched) / len(own)
        run = longest = 0
        for k in own:
            run = run + 1 if al.heard_to_script[k] is None else 0
            longest = max(longest, run)
        if share < CLOSE or longest > MAX_ODD_RUN:
            notes.append(CaptionNote(share=round(share, 2), differs=[], script=""))
            continue
        word_ids = sorted({heard.word_of[k] for k in own})
        first_word = heard.word_of[matched[0]]
        last_word = heard.word_of[matched[-1]]
        odd = {heard.word_of[k] for k in own if al.heard_to_script[k] is None}
        differs = list(dict.fromkeys(heard.words[w] for w in word_ids if w in odd))
        s0 = script.word_of[_matched(al, matched[0])]
        s1 = script.word_of[_matched(al, matched[-1])]
        before = [heard.words[w] for w in word_ids if w < first_word]
        after = [heard.words[w] for w in word_ids if w > last_word]
        middle = [w.translate(QUOTES) for w in script.words[s0 : s1 + 1]]
        suggestion = " ".join(w for w in [*before, *middle, *after] if w)
        if " ".join(words) == suggestion:
            suggestion = ""
        notes.append(CaptionNote(share=round(share, 2), differs=differs[:12], script=suggestion))
    return notes


def _matched(al: Alignment, heard_token: int) -> int:
    script_token = al.heard_to_script[heard_token]
    assert script_token is not None
    return script_token
