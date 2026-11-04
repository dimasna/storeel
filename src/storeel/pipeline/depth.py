"""The speaker, frame by frame, while the title is up, so the title can sit behind them.

SAM 3.1 tracks "person" through that stretch of the video in one request (video segmentation
is billed per frame, at least 50 a request: about $0.015 for three seconds). The masks are
decoded once, here, by a few processes at a time (Meta's decoder is pure Python, about a second
a mask; see maskdecode.py), every other frame (the one between keeps the mask before it), and
kept as one compressed array at half the reel's width and height. Rendering only reads them,
so it stays free.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..common import Cancelled, digest
from ..jobs import JobContext, PipelineError
from ..media import ffmpeg as ff
from ..meta import MetaAPIError
from ..meta.sam import FRAME
from ..models import SAM_MIN_FRAMES, Project, SpeakerMasks
from .maskdecode import unpack
from .title import title_window, title_words

MASK_W, MASK_H = 540, 960  # half the reel's size: SAM's masks come back at the clip's size
MASK_VERSION = 1
MIN_FOUND = 0.5  # the share of frames SAM must find the speaker on for the title to go behind
DECODERS = 4
DECODE_STEP = 2  # decode every this many frames
DECODE_TIMEOUT = 600.0
KEY = "work/speaker-masks.npz"
CLIP = "work/title-window.mp4"

# On the server, set by modal_app.py: decodes batches of SAM's answer lines on many machines at
# once. Takes [(lines, width, height)], gives back for each the frame numbers and their packed
# masks (see maskdecode.decode_packed). Without it, a few local processes decode.
RemoteDecode = Callable[[list[tuple[list[str], int, int]]], list[tuple[list[int], bytes]]]
REMOTE_DECODE: RemoteDecode | None = None
REMOTE_BATCH = 5  # lines a machine decodes (about 3 s each on one there; 240 in 25 s on 49 machines)


def needed(project: Project) -> bool:
    """Whether the title needs its own masks: a title behind the speaker, unless the speaker is
    tracked all through (for a cut-out background, or to step back under the pictures: those
    masks serve the title too)."""
    style = project.style
    return (
        style.title_style == "behind"
        and style.background == "dalang"
        and style.speaker_room != "auto"
        and title_window(project) is not None
    )


def sam_video(ctx: JobContext, clip: Path, frames: int) -> tuple[list[str], int, float]:
    """SAM 3.1 finding "person" in every frame of `clip`: its answer lines (one a frame), the
    frames billed (counted as spent) and how long it took."""
    payload = {
        "model": ctx.settings.sam_model,
        "store": False,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "person"},
                    {
                        "type": "input_video",
                        "video_url": "data:video/mp4;base64," + base64.b64encode(clip.read_bytes()).decode(),
                    },
                ],
            }
        ],
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},  # strings on this endpoint
    }
    result = ctx.client.responses(payload, cancel=ctx.cancelled)
    billed = int(result.usage.get("video_frames_processed") or frames)
    ctx.spend(sam_frames=max(SAM_MIN_FRAMES, billed))
    return [line for line in result.text.splitlines() if line.strip()], billed, result.seconds


def decode_masks(
    ctx: JobContext, lines: list[str], width: int = MASK_W, height: int = MASK_H
) -> dict[int, np.ndarray]:
    """SAM's answer lines decoded: frame number -> packed mask. Many machines at once on the
    server, a few local processes otherwise (or when those machines fail)."""
    if REMOTE_DECODE is not None and len(lines) > REMOTE_BATCH:
        try:
            batches = [
                (lines[k : k + REMOTE_BATCH], width, height) for k in range(0, len(lines), REMOTE_BATCH)
            ]
            out: dict[int, np.ndarray] = {}
            for frames, data in REMOTE_DECODE(batches):
                out.update(unpack(frames, data, width, height))
            ctx.check()
            ctx.log(f"decoded the masks in {len(batches)} batches on machines of their own")
            return out
        except Cancelled:
            raise
        except Exception as exc:  # the machines are a speed-up only
            ctx.log(f"decoding on more machines failed ({type(exc).__name__}: {exc}); decoding here")
    return _decode_all(ctx, lines, width, height)


def _decode_all(ctx: JobContext, lines: list[str], width: int, height: int) -> dict[int, np.ndarray]:
    """SAM's answer lines decoded in parallel processes: frame number -> packed mask."""
    count = max(1, min(DECODERS, os.cpu_count() or 1, len(lines)))
    chunks = [lines[k::count] for k in range(count)]
    jobs = []
    for k, chunk in enumerate(chunks):
        source = ctx.files.prepare(f"work/sam-lines-{k}.txt")
        source.write_text("\n".join(chunk), encoding="utf-8")
        target = ctx.files.prepare(f"work/sam-masks-{k}.npz")
        cmd = [sys.executable, "-m", "storeel.pipeline.maskdecode", str(source), str(target)]
        cmd += [str(width), str(height)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        jobs.append((proc, source, target))
    started = time.monotonic()
    limit = max(DECODE_TIMEOUT, 1.5 * len(lines) / count)  # about a second a mask, on each process
    out: dict[int, np.ndarray] = {}
    try:
        for proc, _, _ in jobs:
            while proc.poll() is None:
                if ctx.cancelled():
                    raise Cancelled
                if time.monotonic() - started > limit:
                    raise PipelineError("decoding the speaker's masks took too long")
                time.sleep(0.2)
            if proc.returncode != 0:
                error = (proc.stderr.read().decode(errors="replace") if proc.stderr else "").strip()
                raise PipelineError(f"decoding the speaker's masks failed: {error[-300:] or proc.returncode}")
        for _, _, target in jobs:
            with np.load(target) as data:
                for frame, packed in zip(data["frames"], data["masks"], strict=True):
                    out[int(frame)] = packed
    finally:
        for proc, source, target in jobs:
            if proc.poll() is None:
                proc.kill()
            source.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
    return out


def track_speaker(ctx: JobContext) -> None:
    """Make (or reuse) the speaker masks for the title's window. A failure only costs the
    effect: the title is drawn in front of the speaker, and the job goes on."""
    try:
        _track(ctx)
    except (MetaAPIError, PipelineError, ff.FFmpegError) as exc:
        ctx.log(f"could not track the speaker for the title ({exc}); it goes in front of them")
        ctx.update(lambda p: setattr(p, "speaker_masks", None))


def _track(ctx: JobContext) -> None:
    project = ctx.project()
    source = project.source
    window = title_window(project)
    if project.style.title_style != "behind" or source is None or window is None:
        return
    start, end = window
    fps = float(source.fps)
    frames = max(1, round((end - start) * fps))
    key_digest = digest(MASK_VERSION, source.digest, start, frames, fps)
    current = project.speaker_masks
    if (
        current is not None
        and current.digest == key_digest
        and (not current.key or ctx.files.exists(current.key))
    ):
        if current.key:
            ctx.log("SAM: the speaker masks for the title are unchanged, reusing them")
        else:
            ctx.log("SAM found no speaker in this stretch before, so the title stays in front")
        return
    clip = ctx.files.prepare(CLIP)
    ff.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-t", f"{frames / fps:.3f}", "-i", str(ctx.files.path(source.key)),
            "-vf", f"scale={MASK_W}:{MASK_H}", "-an", "-r", f"{fps:g}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(clip),
        ],
        what="cutting the title's stretch of video",
        cancel=ctx.cancelled,
    )  # fmt: skip
    try:
        lines, billed, seconds = sam_video(ctx, clip, frames)
    finally:
        ctx.files.delete(CLIP)
    ctx.log(f"SAM 3.1: tracked the speaker over {billed} frames in {seconds:.0f}s; decoding the masks")
    began = time.monotonic()
    # Every other frame is decoded (half the time); the one between keeps the mask before it,
    # a frame late at most, which a talking head never shows.
    wanted = [
        line for line in lines if (m := FRAME.match(line.strip())) and int(m.group(1)) % DECODE_STEP == 0
    ]
    decoded = decode_masks(ctx, wanted) if wanted else {}
    masks = np.zeros((frames, MASK_H, MASK_W), dtype=bool)
    found = looked = 0
    for frame in range(frames):
        packed = decoded.get(frame)
        if packed is not None:
            masks[frame] = np.unpackbits(packed)[: MASK_H * MASK_W].reshape(MASK_H, MASK_W).astype(bool)
            looked += 1
            found += int(masks[frame].any())
        elif frame:  # a frame not decoded (or that SAM skipped) keeps the one before it
            masks[frame] = masks[frame - 1]
    ctx.log(f"decoded {looked} masks in {time.monotonic() - began:.0f}s")
    if found < MIN_FOUND * max(1, len(range(0, frames, DECODE_STEP))):
        ctx.log(f"SAM found the speaker on {found} of {looked} frames, so the title goes in front of them")
        missing = SpeakerMasks(  # remembered, so the next render does not ask again
            key="", start=start, fps=fps, frames=frames, width=MASK_W, height=MASK_H, digest=key_digest
        )
        ctx.update(lambda p: setattr(p, "speaker_masks", missing))
        return
    path = ctx.files.prepare(KEY)
    with path.open("wb") as handle:
        np.savez_compressed(handle, masks=masks)
    stored = SpeakerMasks(
        key=KEY, start=start, fps=fps, frames=frames, width=MASK_W, height=MASK_H, digest=key_digest
    )
    ctx.update(lambda p: setattr(p, "speaker_masks", stored))
    ctx.log(f"the title {title_words(project)!r} goes behind the speaker ({found} of {looked} frames)")
