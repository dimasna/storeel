"""ffmpeg and ffprobe: probing uploads, normalising clips and extracting audio and frames.

Every clip is normalised to the reel's frame before anything else touches it: 1080x1920
(centre-cropped to fill), constant frame rate, H.264 tagged BT.709, AAC 48 kHz stereo. The
transcript, the SAM coordinates and the compositor then all share one timeline and one
pixel space.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..common import CancelCheck, Cancelled

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920
STANDARD_FPS = (24, 25, 30, 50, 60)
HDR_TRANSFERS = frozenset({"arib-std-b67", "smpte2084"})  # HLG, PQ


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe failed; the message carries the end of its error output."""


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegError(f"{' and '.join(missing)} not found on PATH (macOS: brew install ffmpeg)")


def run(
    cmd: list[str],
    *,
    what: str = "ffmpeg",
    cancel: CancelCheck | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    """Run an ffmpeg command, killing it if the job is cancelled. Returns its stderr."""
    if on_progress is not None:
        cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if on_progress else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    errors: deque[str] = deque(maxlen=300)

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            errors.append(line.rstrip())

    def drain_progress() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and value.isdigit() and on_progress is not None:
                on_progress(int(value) / 1e6)  # both keys are microseconds

    threads = [threading.Thread(target=drain_stderr, daemon=True)]
    if on_progress is not None:
        threads.append(threading.Thread(target=drain_progress, daemon=True))
    for thread in threads:
        thread.start()
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel():
                    proc.kill()
                    proc.wait()
                    raise Cancelled from None
    finally:
        for thread in threads:
            thread.join(timeout=5)
    output = "\n".join(errors)
    if proc.returncode != 0:
        tail = "\n".join(list(errors)[-8:]) or f"exit code {proc.returncode}"
        raise FFmpegError(f"{what} failed: {tail}")
    return output


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int  # as displayed, after any rotation flag
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    color_transfer: str
    color_primaries: str

    @property
    def hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS


def _rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, den = value.split("/", 1)
    try:
        rate = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if 1.0 <= rate <= 240.0 else None


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(float(side["rotation"]))
            except (TypeError, ValueError):
                pass
    try:
        return int((stream.get("tags") or {}).get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def _duration_from_packets(path: Path) -> float:
    """Duration of files whose header has none (browser MediaRecorder WebM), read from packets."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    end = 0.0
    for line in out.stdout.splitlines():
        parts = line.split(",")
        try:
            pts = float(parts[0])
        except (ValueError, IndexError):
            continue
        try:
            length = float(parts[1])
        except (ValueError, IndexError):
            length = 0.0
        end = max(end, pts + length)
    return end


def probe(path: Path) -> Probe:
    """Read the facts the pipeline needs about a video file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if out.returncode != 0:
        raise FFmpegError(f"could not read the file as video: {out.stderr.strip()[-300:]}")
    info = json.loads(out.stdout or "{}")
    streams = info.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise FFmpegError("the file has no video stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if abs(_rotation(video)) % 180 == 90:
        width, height = height, width
    duration = 0.0
    for raw in ((info.get("format") or {}).get("duration"), video.get("duration")):
        try:
            duration = float(raw)
            break
        except (TypeError, ValueError):
            continue
    if not math.isfinite(duration) or duration <= 0:
        duration = _duration_from_packets(path)
    if width <= 0 or height <= 0 or duration <= 0:
        raise FFmpegError("could not read the video's size or duration")
    return Probe(
        duration=duration,
        width=width,
        height=height,
        fps=_rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or 30.0,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        video_codec=str(video.get("codec_name") or ""),
        color_transfer=str(video.get("color_transfer") or ""),
        color_primaries=str(video.get("color_primaries") or ""),
    )


def choose_fps(rates: list[float]) -> int:
    """One frame rate for the whole reel: the most common source rate, snapped to a standard one."""
    snapped = [min(STANDARD_FPS, key=lambda s: abs(s - rate)) for rate in rates if rate > 0]
    if not snapped:
        return 30
    return max(sorted(set(snapped), reverse=True), key=snapped.count)


def _base_cmd() -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]


def normalize_clip(
    src: Path,
    dst: Path,
    info: Probe,
    fps: int,
    *,
    cancel: CancelCheck | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Re-encode one clip into the reel's frame, frame rate, colour space and audio format."""
    filters: list[str] = []
    if info.hdr:
        # No zscale/tone-mapping in common ffmpeg builds: map HLG/PQ from BT.2020 as if it were
        # SDR. HLG (what phones record) stays watchable this way; PQ comes out flat.
        log.warning("%s is HDR (%s); converting to SDR approximately", src.name, info.color_transfer)
        filters.append("colorspace=all=bt709:iall=bt2020:fast=1:format=yuv420p")
    filters += [
        f"fps={fps}",
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos"
        ":out_color_matrix=bt709:out_range=tv",
        f"crop={WIDTH}:{HEIGHT}",
        "setsar=1",
        "format=yuv420p",
    ]
    cmd = [*_base_cmd(), "-i", str(src)]
    if not info.has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if info.has_audio else "1:a:0", "-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-profile:v", "high"]
    cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    # apad + -shortest: audio and video end together, so clips concatenate without drift.
    cmd += ["-af", "aresample=48000:async=1:first_pts=0,apad", "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    cmd += ["-shortest", "-movflags", "+faststart", str(dst)]
    run(cmd, what=f"normalising {src.name}", cancel=cancel, on_progress=on_progress)


def concat(parts: list[Path], dst: Path, *, cancel: CancelCheck | None = None) -> None:
    """Join normalised clips: video is copied, audio re-encoded once so the track is continuous."""
    if len(parts) == 1:
        shutil.copyfile(parts[0], dst)
        return
    listing = dst.with_suffix(".txt")

    def quoted(path: Path) -> str:
        return "'" + str(path.resolve()).replace("'", "'\\''") + "'"

    listing.write_text("ffconcat version 1.0\n" + "".join(f"file {quoted(p)}\n" for p in parts))
    try:
        cmd = [*_base_cmd(), "-f", "concat", "-safe", "0", "-i", str(listing)]
        cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy"]
        cmd += ["-af", "aresample=48000:async=1", "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        cmd += ["-movflags", "+faststart", str(dst)]
        run(cmd, what="joining clips", cancel=cancel)
    finally:
        listing.unlink(missing_ok=True)


def make_proxy(src: Path, dst: Path, *, cancel: CancelCheck | None = None) -> None:
    """A small silent copy for Muse Spark: it gets the transcript as text, so no audio track."""
    cmd = [*_base_cmd(), "-i", str(src), "-an", "-vf", "fps=10,scale=540:960:flags=bicubic"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p"]
    cmd += ["-movflags", "+faststart", str(dst)]
    run(cmd, what="making the analysis copy", cancel=cancel)


def extract_wav(src: Path, dst: Path, *, cancel: CancelCheck | None = None) -> None:
    """Mono 16-bit PCM at 24 kHz, Muse Voice Transcribe's native format."""
    cmd = [*_base_cmd(), "-i", str(src), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le"]
    cmd += ["-map_metadata", "-1", str(dst)]
    run(cmd, what="extracting audio", cancel=cancel)


def extract_frame(src: Path, seconds: float, dst: Path, duration: float | None = None) -> None:
    """One frame as PNG (input seeking is frame-accurate when decoding)."""
    if duration is not None:
        seconds = min(seconds, max(0.0, duration - 0.1))
    cmd = [*_base_cmd(), "-ss", f"{max(0.0, seconds):.3f}", "-i", str(src), "-frames:v", "1"]
    cmd += ["-update", "1", str(dst)]
    run(cmd, what="extracting a frame")
    if not dst.exists():
        raise FFmpegError(f"no frame at {seconds:.2f}s")


def measure_loudness(src: Path, *, target: float = -14.0, cancel: CancelCheck | None = None) -> dict | None:
    """First loudnorm pass. None when there is nothing to normalise (a silent track)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(src), "-vn"]
    cmd += ["-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
    output = run(cmd, what="measuring loudness", cancel=cancel)
    try:
        stats = json.loads(output[output.rindex("{") : output.rindex("}") + 1])
        if not math.isfinite(float(stats["input_i"])) or float(stats["input_i"]) < -70:
            return None
    except (ValueError, KeyError):
        return None
    return stats


def loudnorm_filter(stats: dict | None, *, target: float = -14.0) -> str | None:
    """Second loudnorm pass, linear, with the first pass's measurements."""
    if stats is None:
        return None
    return (
        f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true"
    )
