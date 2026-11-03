"""The speaker in every frame of the reel, so a cut-out background can go behind them.

SAM 3.1 tracks "person" through the whole video at TRACK_FPS, in stretches of CHUNK_SECONDS sent
side by side (video segmentation is billed per frame: about $0.24 for 100 seconds). The masks are
decoded once (on many machines at once on the server, see depth.decode_masks) and kept as packed
bits at half the reel's width and height, with the holes SAM leaves (a clip-on microphone)
filled; the compositor eases from one mask to the next, so the
cut-out moves smoothly at the reel's frame rate. Rendering only reads them, so it stays free.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..common import digest
from ..jobs import JobContext, PipelineError
from ..media import ffmpeg as ff
from ..meta import MetaAPIError
from ..meta.sam import FRAME
from ..models import Project, SpeakerTrack
from .depth import MASK_H, MASK_W, decode_masks, sam_video

TRACK_FPS = 12
CHUNK_SECONDS = 20.0
PARALLEL = 4  # SAM requests at once
MIN_FOUND = 0.3  # the share of frames the speaker must be found on for the cut-out to be used
VERSION = 2  # 2: holes filled
KEY = "work/speaker-track.npz"


def _spread(open_: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """`seed` grown along each row through `open_`: a run of open pixels touching it joins it."""
    h, w = open_.shape
    flat = open_.ravel()
    start = flat & ~np.concatenate(([False], flat[:-1]))
    start[::w] = flat[::w]  # a run never carries on into the next row
    label = np.cumsum(start) * flat
    hit = np.bincount(label, weights=seed.ravel(), minlength=int(label[-1]) + 1) > 0
    hit[0] = False
    return hit[label].reshape(h, w)


def filled(mask: np.ndarray, rounds: int = 40) -> np.ndarray:
    """A speaker mask (0/1) with its holes filled: background that reaches neither the top nor the
    sides of the frame is part of them (a clip-on microphone SAM left out, the gap of a hand on the
    hip). The bottom edge does not count as outside, since the body goes on below the frame."""
    person = mask.astype(bool)
    open_ = ~person
    outside = np.zeros_like(open_)
    outside[0] = open_[0]
    outside[:, 0] |= open_[:, 0]
    outside[:, -1] |= open_[:, -1]
    count = -1
    for _ in range(rounds):  # rows then columns, until nothing more is reached
        outside = _spread(open_.T.copy(), _spread(open_, outside).T.copy()).T
        now = int(outside.sum())
        if now == count:
            return (person | ~outside).astype(np.uint8)
        count = now
    return person.astype(np.uint8)  # (never settled: leave it as SAM gave it)


def needed(project: Project) -> bool:
    return project.style.background != "original" and project.source is not None


def track_reel(ctx: JobContext) -> None:
    """Make (or reuse) the speaker's masks for the whole reel. A failure only costs the effect:
    the reel keeps the speaker's own background, and the job goes on."""
    try:
        _track(ctx)
    except (MetaAPIError, PipelineError, ff.FFmpegError) as exc:
        ctx.log(f"could not cut the speaker out ({exc}); they keep their own background")
        ctx.update(lambda p: setattr(p, "speaker_track", None))


def _track(ctx: JobContext) -> None:
    project = ctx.project()
    source = project.source
    if not needed(project) or source is None:
        return
    frames = max(1, math.ceil(source.duration * TRACK_FPS - 1e-6))
    key_digest = digest(VERSION, source.digest, TRACK_FPS, MASK_W, MASK_H)
    current = project.speaker_track
    if (
        current is not None
        and current.digest == key_digest
        and (not current.key or ctx.files.exists(current.key))
    ):
        ctx.log(
            "SAM: the speaker's cut-out is unchanged, reusing it"
            if current.key
            else "SAM found no speaker before"
        )
        return
    per_chunk = round(CHUNK_SECONDS * TRACK_FPS)
    chunks = [(k, k * CHUNK_SECONDS) for k in range(math.ceil(frames / per_chunk))]

    def one(chunk: tuple[int, float]) -> list[tuple[int, str]]:
        index, start = chunk
        length = min(CHUNK_SECONDS, source.duration - start)
        clip = ctx.files.prepare(f"work/track-{index}.mp4")
        try:
            ff.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                    "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(ctx.files.path(source.key)),
                    "-vf", f"fps={TRACK_FPS},scale={MASK_W}:{MASK_H}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(clip),
                ],
                what="cutting the video for SAM",
                cancel=ctx.cancelled,
            )  # fmt: skip
            lines, _, _ = sam_video(ctx, clip, round(length * TRACK_FPS))
        finally:
            ctx.files.delete(f"work/track-{index}.mp4")
        out = []
        for line in lines:
            text = line.strip()
            header = FRAME.match(text)
            if header is None or int(header.group(1)) >= per_chunk:
                continue
            # numbered on the reel: "<12f..." in the third stretch is frame 2 * per_chunk + 12
            number = index * per_chunk + int(header.group(1))
            out.append((number, f"<{number}f" + text[len(header.group(1)) + 2 :]))
        return out

    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(PARALLEL, len(chunks))) as pool:
        numbered = [item for part in pool.map(one, chunks) for item in part]
    ctx.flush_usage()
    ctx.log(
        f"SAM 3.1: tracked the speaker through {source.duration:.0f}s at {TRACK_FPS} fps"
        f" ({len(chunks)} request(s), {time.monotonic() - began:.0f}s); decoding {len(numbered)} masks"
    )
    began = time.monotonic()
    decoded = decode_masks(ctx, [line for _, line in sorted(numbered)])
    row = (MASK_W * MASK_H + 7) // 8
    packed = np.zeros((frames, row), dtype=np.uint8)
    found = 0
    for frame in range(frames):
        mask = decoded.get(frame)
        if mask is not None:
            bits = np.unpackbits(mask)[: MASK_W * MASK_H].reshape(MASK_H, MASK_W)
            packed[frame] = np.packbits(filled(bits))
            found += int(mask.any())
        elif frame:  # a frame SAM skipped keeps the one before it
            packed[frame] = packed[frame - 1]
    ctx.log(f"decoded {len(decoded)} masks in {time.monotonic() - began:.0f}s; the speaker is on {found}")
    if found < MIN_FOUND * frames:
        ctx.log("SAM found too little of the speaker to cut them out, so they keep their own background")
        missing = SpeakerTrack(
            key="", fps=TRACK_FPS, frames=frames, width=MASK_W, height=MASK_H, digest=key_digest
        )
        ctx.update(lambda p: setattr(p, "speaker_track", missing))
        return
    path = ctx.files.prepare(KEY)
    with path.open("wb") as handle:
        np.savez_compressed(handle, masks=packed)
    stored = SpeakerTrack(
        key=KEY, fps=TRACK_FPS, frames=frames, width=MASK_W, height=MASK_H, digest=key_digest
    )
    ctx.update(lambda p: setattr(p, "speaker_track", stored))
