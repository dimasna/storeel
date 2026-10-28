"""Command line: `storeel serve` starts the studio, `storeel make` makes a reel without the UI."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import uuid
from pathlib import Path

from .common import slug
from .config import ConfigError, get_settings
from .jobs import PipelineError, execute
from .media import ffmpeg as ff
from .models import Style
from .pipeline.run import HANDLERS
from .projects import create_project, import_clip
from .services import Services

STYLE_CHOICES = Style.model_json_schema()["properties"]


def _choices(field: str) -> list[str]:
    return list(STYLE_CHOICES[field]["enum"])


def serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web.app import create_app

    if args.host not in ("127.0.0.1", "localhost"):
        print(
            "warning: the studio has no login and spends your Model API credits; only expose it on a"
            " network you trust",
            file=sys.stderr,
        )
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def make(args: argparse.Namespace) -> int:
    """Upload -> process -> render in this process: a quick end-to-end check of the pipeline."""
    settings = get_settings()
    key = settings.require_api_key()  # your own key, from MODEL_API_KEY or .env
    ff.require_ffmpeg()
    services = Services.create(settings)
    style = Style(
        language=args.language,
        visual_style=args.visual_style,
        visuals=args.visuals,
        captions=args.captions,
        watermark=args.watermark,
    )
    project = create_project(services, "video", args.title or args.videos[0].stem, style)
    print(f"project {project.id} ({settings.data_dir / 'projects' / project.id})")
    for video in args.videos:
        clip = import_clip(services, services.db.get_project(project.id), video, video.name)
        services.db.update_project(project.id, lambda p, c=clip: p.clips.append(c))
        print(f"  {video.name}: {clip.width}x{clip.height}, {clip.fps:g} fps, {clip.duration:.1f}s")
    for kind, params in (("process", {}), ("render", {"fit_mb": args.fit_mb})):
        job_id = uuid.uuid4().hex
        services.keys.put(job_id, key)
        job = services.db.claim(services.db.enqueue(project.id, kind, params, job_id=job_id).id)
        assert job is not None
        status = execute(services, job, HANDLERS)
        if status != "done":
            print(f"{kind} {status}: {services.db.get_job(job.id).error}", file=sys.stderr)
            return 1
    project = services.db.get_project(project.id)
    render = project.renders[-1]
    out = args.out or Path(f"{slug(project.title, 'reel')}.mp4")
    shutil.copyfile(services.files(project.id).path(render.key), out)
    usage = project.usage
    print(f"reel: {out} ({render.duration:.1f}s, {render.size / 1e6:.1f} MB)")
    print(
        f"Model API usage: {usage.spark_input_tokens} Spark input / {usage.spark_output_tokens} output"
        f" tokens, {usage.images} images, {usage.sam_images} SAM images, {usage.asr_seconds:.0f}s transcribed"
        f" (about ${usage.estimated_usd:.3f} at list prices)"
    )
    print(f"open the project in the studio to review it: storeel serve, then /#/p/{project.id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storeel", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("serve", help="start the studio at http://127.0.0.1:8000")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    run.set_defaults(handler=serve)

    reel = commands.add_parser("make", help="make a reel from video files, without the web UI")
    reel.add_argument("videos", nargs="+", type=Path, help="one or more clips, in order")
    reel.add_argument("--title")
    reel.add_argument("--language", choices=_choices("language"), default="auto")
    reel.add_argument("--visual-style", choices=_choices("visual_style"), default="cinematic")
    reel.add_argument("--visuals", choices=_choices("visuals"), default="balanced")
    reel.add_argument("--captions", choices=_choices("captions"), default="pill")
    reel.add_argument("--watermark", default="")
    reel.add_argument("--fit-mb", type=int, help="keep the file under this size (e.g. 25 for DMs)")
    reel.add_argument("--out", type=Path, help="where to copy the reel (default: ./<title>.mp4)")
    reel.set_defaults(handler=make)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        return args.handler(args)
    except (ConfigError, PipelineError, ff.FFmpegError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
