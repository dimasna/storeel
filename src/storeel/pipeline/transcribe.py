"""Muse Voice Transcribe, then word timings for the captions.

The model returns speech turns with start and end times but no word timestamps. Inside each
turn, words are spread over the stretches where the audio is actually loud (see
media/speech.py), weighted by their syllables, so the highlighted word follows the voice
and nothing is captioned during pauses.
"""

from __future__ import annotations

import re
import uuid

from ..common import digest
from ..jobs import JobContext
from ..media.speech import Envelope
from ..models import Source, Transcript, Turn, Word

VERSION = 1
LANGUAGE_BIAS = {"auto": [], "id": ["Indonesian", "English"], "en": ["English"]}
VOWELS = re.compile(r"[aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýœ]+", re.IGNORECASE)
LEAD = 0.6  # turn onsets are detected late: look this far back for the real one
TRAIL = 0.15


def syllables(token: str) -> float:
    core = re.sub(r"[^\w]", "", token)
    if not core:
        return 0.3
    digits = sum(ch.isdigit() for ch in core)
    return max(1, len(VOWELS.findall(core))) + 1.2 * digits


def _at(position: float, speech: list[tuple[float, float]], prefer_next: bool) -> float:
    """Map a point in 'speaking time' (pauses removed) to the timeline."""
    elapsed = 0.0
    for index, (start, end) in enumerate(speech):
        length = end - start
        last = index == len(speech) - 1
        if position < elapsed + length - 1e-9 or last or (not prefer_next and position <= elapsed + length):
            return start + min(max(position - elapsed, 0.0), length)
        elapsed += length
    return speech[-1][1]


def place_words(text: str, speech: list[tuple[float, float]]) -> list[Word]:
    """Spread the words of `text` over the speech stretches (see `_place`)."""
    return _place(text.split(), speech, frozenset())


def _place(tokens: list[str], speech: list[tuple[float, float]], turn_breaks: frozenset[int]) -> list[Word]:
    """Words timed over speech stretches.

    The pauses between stretches are first matched to word boundaries (turn, sentence and
    clause ends preferred, see `align_chunks`); within each chunk, words share the speaking
    time in proportion to their syllables.
    """
    if not tokens or not speech:
        return []
    weights = [0.35 + syllables(token) for token in tokens]
    words: list[Word] = []
    for b1, b2, s1, s2 in align_chunks(tokens, weights, speech, turn_breaks):
        words += _spread(tokens[b1:b2], weights[b1:b2], speech[s1 : s2 + 1])
    return words


def _spread(tokens: list[str], weights: list[float], speech: list[tuple[float, float]]) -> list[Word]:
    total_weight = sum(weights)
    speaking = sum(end - start for start, end in speech)
    words, done = [], 0.0
    for token, weight in zip(tokens, weights, strict=True):
        begin = speaking * done / total_weight
        done += weight
        finish = speaking * done / total_weight
        start = _at(begin, speech, prefer_next=True)
        end = max(_at(finish, speech, prefer_next=False), start + 0.04)
        words.append(Word(text=token, start=round(start, 3), end=round(end, 3)))
    return words


SENTENCE_BREAK = re.compile(r"[.!?…]['\"”’)]*$")
CLAUSE_BREAK = re.compile(r"[,;:—–-]['\"”’)]*$")
SKIP_PENALTY = 0.08  # a pause inside a word or around an untranscribed filler ("um")
CROSS_PENALTY = 0.3  # a turn edge that does not fall on a pause


def _break_penalty(token: str) -> float:
    if SENTENCE_BREAK.search(token):
        return 0.0
    if CLAUSE_BREAK.search(token):
        return 0.03
    return 0.12


def align_chunks(
    tokens: list[str],
    weights: list[float],
    speech: list[tuple[float, float]],
    turn_breaks: frozenset[int] = frozenset(),
) -> list[tuple[int, int, int, int]]:
    """Match the pauses between speech stretches to word boundaries.

    Returns chunks (first word, end word, first stretch, last stretch). A dynamic program
    picks, for each pause in order, a later word boundary or none, minimising how far each
    chunk's share of the syllables is from its share of the speaking time, plus penalties
    for pausing where the text has no punctuation and for a turn edge (`turn_breaks`, word
    indexes where a new turn starts) that does not fall on a pause.
    """
    gaps, count = len(speech) - 1, len(tokens)
    if gaps <= 0 or count <= 1:
        return [(0, count, 0, gaps)]
    cum_w = [0.0]
    for weight in weights:
        cum_w.append(cum_w[-1] + weight)
    cum_t = [0.0]
    for start, end in speech:
        cum_t.append(cum_t[-1] + (end - start))
    breaks = sorted(turn_breaks)

    def cost(b1: int, b2: int, g1: int, g2: int) -> float:
        share_w = (cum_w[b2] - cum_w[b1]) / cum_w[-1]
        share_t = (cum_t[g2 + 1] - cum_t[g1 + 1]) / cum_t[-1]
        crossed = sum(1 for b in breaks if b1 < b < b2)
        return abs(share_w - share_t) + CROSS_PENALTY * crossed

    # state (gap, boundary): gap -1 / boundary 0 is the start, gap `gaps` / boundary `count` the end
    best: dict[tuple[int, int], tuple[float, tuple[int, int] | None]] = {(-1, 0): (0.0, None)}
    for g2 in range(gaps + 1):
        boundaries = range(1, count) if g2 < gaps else (count,)
        for b2 in boundaries:
            choice: tuple[float, tuple[int, int] | None] = (float("inf"), None)
            for (g1, b1), (so_far, _) in best.items():
                if g1 >= g2 or b1 >= b2:
                    continue
                total = so_far + cost(b1, b2, g1, g2) + SKIP_PENALTY * (g2 - g1 - 1)
                if g2 < gaps:
                    total += 0.0 if b2 in turn_breaks else _break_penalty(tokens[b2 - 1])
                if total < choice[0]:
                    choice = (total, (g1, b1))
            if choice[1] is not None:
                best[(g2, b2)] = choice
    chunks: list[tuple[int, int, int, int]] = []
    state: tuple[int, int] | None = (gaps, count)
    while state is not None and state != (-1, 0):
        previous = best[state][1]
        assert previous is not None
        (g1, b1), (g2, b2) = previous, state
        chunks.append((b1, b2, g1 + 1, g2))
        state = previous
    return chunks[::-1]


def build_turns(raw_turns: list[dict], envelope: Envelope, duration: float) -> list[Turn]:
    """Turns from the transcription response, with refined edges and timed words.

    Turns whose search windows touch are aligned together, so the edge between them lands
    on the pause in the audio instead of on the model's (late) detection times.
    """
    cleaned: list[tuple[float, float, str, str | None]] = []
    for raw in sorted(raw_turns, key=lambda t: t.get("startMs", 0)):
        text = " ".join(str(raw.get("transcript") or "").split())
        if not text:
            continue  # e.g. a turn the clip ended part-way through
        start = max(0.0, float(raw.get("startMs", 0)) / 1000)
        end = min(duration, max(start + 0.2, float(raw.get("endMs", 0)) / 1000))
        cleaned.append((start, end, text, raw.get("speaker")))

    groups: list[list[int]] = []
    for index, (start, _, _, _) in enumerate(cleaned):
        if groups and start - LEAD < cleaned[groups[-1][-1]][1] + TRAIL:
            groups[-1].append(index)
        else:
            groups.append([index])

    turns: list[Turn] = []
    previous_end = 0.0
    for group in groups:
        first, last = cleaned[group[0]], cleaned[group[-1]]
        lo = max(previous_end + 0.02, first[0] - LEAD)
        hi = min(last[1] + TRAIL, duration)
        speech = envelope.segments(lo, max(hi, lo + 0.2))
        if not speech:  # too quiet to tell (or not speech): trust the model's edges
            speech = [(first[0], max(last[1], first[0] + 0.2))]
        tokens: list[str] = []
        owners: list[int] = []
        for index in group:
            for token in cleaned[index][2].split():
                tokens.append(token)
                owners.append(index)
        breaks = frozenset(k for k in range(1, len(tokens)) if owners[k] != owners[k - 1])
        words = _place(tokens, speech, breaks)
        for index in group:
            own = [word for word, owner in zip(words, owners, strict=True) if owner == index]
            start, end = own[0].start, own[-1].end
            inside = [(max(a, start), min(b, end)) for a, b in speech if b > start and a < end]
            turns.append(
                Turn(
                    id=len(turns) + 1,
                    start=start,
                    end=end,
                    text=cleaned[index][2],
                    original=cleaned[index][2],
                    speaker=cleaned[index][3],
                    speech=[(round(a, 3), round(b, 3)) for a, b in inside] or [(start, end)],
                    words=own,
                )
            )
        previous_end = speech[-1][1]
    return turns


def retime(turn: Turn, text: str) -> Turn:
    """The turn with corrected caption text, re-timed over the same speech."""
    text = " ".join(text.split())
    speech = turn.speech or [(turn.start, turn.end)]
    return turn.model_copy(update={"text": text, "words": place_words(text, speech)})


def transcribe(ctx: JobContext, source: Source, language: str, keywords: list[str]) -> Transcript:
    bias = LANGUAGE_BIAS.get(language, [])
    keywords = sorted({k.strip() for k in keywords if k.strip()})[:50]
    key = digest(VERSION, source.digest, ctx.settings.asr_model, bias, keywords)
    current = ctx.project().transcript
    if current is not None and current.digest == key:
        ctx.log("transcript: unchanged, reusing it")
        return current

    wav = ctx.files.path(source.audio_key)
    session_id = f"storeel-{ctx.project_id[:12]}-{uuid.uuid4().hex[:8]}"
    ctx.log(f"Muse Voice Transcribe: {source.duration:.1f}s of audio (bias {bias or 'auto'})")
    response = ctx.client.transcribe(
        wav,
        model=ctx.settings.asr_model,
        mode="ENDPOINTING",
        language_bias=bias,
        keywords=keywords,
        session_id=session_id,
        cancel=ctx.cancelled,
    )
    ctx.spend(asr_seconds=int(response.get("audioDurationMs", 0)) // 1000)
    turns = build_turns(response.get("turns") or [], Envelope.from_wav(wav), source.duration)
    words = sum(len(t.words) for t in turns)
    ctx.log(
        f"transcript: {len(turns)} turn(s), {words} words (session {response.get('sessionId', session_id)})"
    )
    if not turns:
        ctx.log("no speech was recognised: the reel will have no captions")
    transcript = Transcript(
        turns=turns,
        duration=source.duration,
        session_id=response.get("sessionId", session_id),
        language_bias=bias,
        keywords=keywords,
        digest=key,
    )
    ctx.update(lambda p: setattr(p, "transcript", transcript))
    return transcript
