"""Turn the project's clips (or recorded takes) into one master video, a proxy and a WAV."""

from __future__ import annotations

import os

from ..common import digest
from ..jobs import JobContext, PipelineError
from ..media import ffmpeg as ff
from ..models import Project, Segment, Source

VERSION = 2  # 2: frames tagged BT.709


def _scene_of(project: Project) -> dict[str, str]:
    if project.script is None:
        return {}
    return {scene.take.id: scene.id for scene in project.script.scenes if scene.take}


def ingest(ctx: JobContext) -> Source:
    project = ctx.project()
    clips = project.inputs()
    if not clips:
        raise PipelineError("add a video (or record every scene) first")
    if project.path == "idea" and project.script and any(s.take is None for s in project.script.scenes):
        raise PipelineError("record every scene first")
    total = sum(c.duration for c in clips)
    limit = ctx.settings.max_input_seconds
    if total > limit + 1:
        raise PipelineError(f"the clips are {total:.0f}s long; the limit is {limit}s")
    fps = ff.choose_fps([c.fps for c in clips])
    key = digest(VERSION, fps, [(c.id, c.key, c.size, round(c.duration, 3)) for c in clips])
    files = ctx.files
    if (
        project.source is not None
        and project.source.digest == key
        and all(
            files.exists(k) for k in (project.source.key, project.source.proxy_key, project.source.audio_key)
        )
    ):
        ctx.log("source: unchanged, reusing it")
        return project.source

    scenes = _scene_of(project)
    parts, segments, offset = [], [], 0.0
    for index, clip in enumerate(clips):
        ctx.check()
        normalized_key = f"work/clips/{clip.id}-{fps}fps-v{VERSION}.mp4"
        path = files.prepare(normalized_key)
        if not path.exists():
            src = files.path(clip.key)
            info = ff.probe(src)
            ctx.log(
                f"normalising {clip.name}: {info.width}x{info.height} {info.fps:.2f} fps {info.duration:.1f}s"
                + (" (HDR)" if info.hdr else "")
            )
            tmp = path.with_name(f".{path.stem}.tmp.mp4")

            def report(seconds: float, i: int = index, length: float = info.duration) -> None:
                ctx.progress((i + min(1.0, seconds / max(0.1, length))) / (len(clips) + 1))

            try:
                ff.normalize_clip(src, tmp, info, fps, cancel=ctx.cancelled, on_progress=report)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        length = ff.probe(path).duration
        segments.append(
            Segment(
                start=round(offset, 3),
                end=round(offset + length, 3),
                clip_id=clip.id,
                scene_id=scenes.get(clip.id),
            )
        )
        offset += length
        parts.append(path)
    keep = {p.name for p in parts}
    clips_dir = files.path("work/clips")
    for stale in clips_dir.glob("*.mp4"):
        if stale.name not in keep:
            stale.unlink(missing_ok=True)

    source_path = files.prepare("work/source.mp4")
    for target, make in (
        (source_path, lambda tmp: ff.concat(parts, tmp, cancel=ctx.cancelled)),
        (files.prepare("work/proxy.mp4"), lambda tmp: ff.make_proxy(source_path, tmp, cancel=ctx.cancelled)),
        (files.prepare("work/audio.wav"), lambda tmp: ff.extract_wav(source_path, tmp, cancel=ctx.cancelled)),
    ):
        tmp = target.with_name(f".{target.stem}.tmp{target.suffix}")
        try:
            make(tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    duration = ff.probe(source_path).duration
    source = Source(
        key="work/source.mp4",
        proxy_key="work/proxy.mp4",
        audio_key="work/audio.wav",
        duration=round(duration, 3),
        fps=fps,
        segments=segments,
        digest=key,
    )
    ctx.log(f"source: {len(clips)} clip(s), {duration:.1f}s at {fps} fps")
    ctx.update(lambda p: setattr(p, "source", source))
    return source
