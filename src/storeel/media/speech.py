"""Where speech is in an audio track, from its loudness.

Muse Voice Transcribe times whole turns, and its turn edges are "audio processed when the
model detected" onset and end, not acoustic boundaries: the end in particular trails the
real end of speech. The loudness envelope finds where speech actually starts, stops and
pauses inside a turn, so words can be spread over the time someone is really talking.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FRAME = 0.01  # seconds per envelope frame


@dataclass(frozen=True)
class Envelope:
    level: np.ndarray  # RMS level per 10 ms frame, dBFS
    floor: float  # noise floor estimate, dBFS

    @classmethod
    def from_wav(cls, path: Path) -> Envelope:
        with wave.open(str(path)) as wav:
            if wav.getsampwidth() != 2:
                raise ValueError("expected 16-bit PCM")
            rate, channels = wav.getframerate(), wav.getnchannels()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return cls.from_samples(samples / 32768.0, rate)

    @classmethod
    def from_samples(cls, samples: np.ndarray, rate: int) -> Envelope:
        hop = max(1, round(rate * FRAME))
        frames = len(samples) // hop
        if frames == 0:
            return cls(level=np.full(1, -120.0), floor=-120.0)
        blocks = samples[: frames * hop].reshape(frames, hop)
        rms = np.sqrt(np.mean(blocks * blocks, axis=1))
        level = 20 * np.log10(rms + 1e-7)
        level = np.convolve(level, np.ones(3) / 3, mode="same")  # smooth out single-frame flicker
        floor = float(np.clip(np.percentile(level, 10), -80.0, -25.0))
        return cls(level=level, floor=floor)

    @property
    def duration(self) -> float:
        return len(self.level) * FRAME

    def segments(
        self,
        start: float,
        end: float,
        *,
        min_gap: float = 0.18,
        min_speech: float = 0.08,
    ) -> list[tuple[float, float]]:
        """Stretches of speech between `start` and `end`; gaps shorter than `min_gap` are bridged."""
        i0 = max(0, int(start / FRAME))
        i1 = min(len(self.level), int(np.ceil(end / FRAME)))
        if i1 - i0 < 2:
            return []
        level = self.level[i0:i1]
        peak = float(np.percentile(level, 98))
        threshold = max(self.floor + 10.0, peak - 30.0)
        active = level > threshold
        runs: list[list[int]] = []
        index = 0
        while index < len(active):
            if not active[index]:
                index += 1
                continue
            begin = index
            while index < len(active) and active[index]:
                index += 1
            if runs and begin - runs[-1][1] < min_gap / FRAME:
                runs[-1][1] = index
            else:
                runs.append([begin, index])
        return [((i0 + a) * FRAME, (i0 + b) * FRAME) for a, b in runs if (b - a) >= min_speech / FRAME]
