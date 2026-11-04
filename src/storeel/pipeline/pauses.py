"""The long pauses of a reel, for Style.pauses "trim": the render cuts them out of the finished
video, sound and picture together, so everything drawn over it stays in step.

A pause is a silence in the speaker's audio longer than MIN_PAUSE. It keeps KEEP_AFTER after the
words before it and KEEP_BEFORE before the words after it; the rest is cut. The silence before
the first words is shortened the same way; the end is kept (a novel part's end screen holds
there). A cut never touches a word the transcript heard, and every cut starts and ends on a
frame, so the sound and the picture lose exactly the same time.
"""

from __future__ import annotations

from itertools import pairwise

from ..files import ProjectFiles
from ..media.speech import Envelope
from ..models import Project

MIN_PAUSE = 0.7  # seconds of silence before a pause is shortened
KEEP_AFTER = 0.3  # seconds kept after the words before a pause
KEEP_BEFORE = 0.25  # seconds kept before the words after it
SHORTEST_CUT = 0.1  # seconds: a smaller cut is left out


def cuts(project: Project, files: ProjectFiles) -> list[tuple[float, float]]:
    """The stretches to cut, in seconds on the reel's timeline, on frame boundaries."""
    source, transcript = project.source, project.transcript
    if source is None or transcript is None or not source.audio_key or not files.exists(source.audio_key):
        return []
    envelope = Envelope.from_wav(files.path(source.audio_key))
    duration, fps = source.duration, source.fps
    speech = envelope.segments(0.0, min(duration, envelope.duration), min_gap=0.25)
    words = sorted((w.start, w.end) for turn in transcript.turns for w in turn.words)
    if not speech:
        return []
    out: list[tuple[float, float]] = []
    gaps = [(0.0, speech[0][0])] + [(a[1], b[0]) for a, b in pairwise(speech)]
    for index, (lo, hi) in enumerate(gaps):
        if hi - lo < MIN_PAUSE:
            continue
        start = lo if index == 0 else lo + KEEP_AFTER
        end = hi - KEEP_BEFORE
        # Never into a word: the transcript's words bound the cut too.
        for w0, w1 in words:
            if w0 < end and w1 > start:
                if w0 - start > end - w1:
                    end = min(end, w0 - 0.05)
                else:
                    start = max(start, w1 + 0.05)
        start, end = round(start * fps) / fps, round(end * fps) / fps
        if end - start >= SHORTEST_CUT:
            out.append((start, end))
    return out


def kept(cut: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """The stretches left between the cuts."""
    out, t = [], 0.0
    for start, end in cut:
        if start > t:
            out.append((t, start))
        t = max(t, end)
    if t < duration:
        out.append((t, duration))
    return out
