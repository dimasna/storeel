"""HTTP API for the studio, plus the static single-page UI.

The server holds the Model API key and spends money on the user's behalf, but has no login
yet: it is meant for this machine only. It binds to 127.0.0.1 by default, accepts only known
Host headers (blocking DNS-rebinding), and refuses state-changing requests sent by other web
sites (Origin / Sec-Fetch-Site checks). Uploads are size-checked before they are read.

Each step of the flow is an action on the backend; the UI only calls them. While a job runs,
a project accepts no edits except cancelling, so a job never works on data that changes
under it.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..config import ConfigError, Settings, get_settings
from ..db import Conflict, NotFound
from ..jobs import PipelineError, Workers
from ..media import ffmpeg as ff
from ..models import DEFAULT_TITLE, Display, Idea, Project, Scene, Script, ScriptEdit, Style
from ..pipeline.render import FONT_FILE
from ..pipeline.run import HANDLERS
from ..pipeline.transcribe import retime
from ..projects import create_project, import_clip, summary, view
from ..services import Services

log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent / "static"
MEDIA_PREFIXES = ("uploads/", "refs/", "assets/", "renders/")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
UPLOAD_SUFFIXES = ("/clips", "/take")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewProject(Body):
    path: Literal["video", "idea"]
    title: str = Field(DEFAULT_TITLE, max_length=120)


class TitleEdit(Body):
    title: str = Field(min_length=1, max_length=120)


class ClipOrder(Body):
    ids: list[str] = Field(max_length=50)


class ProcessRequest(Body):
    fresh: bool = False  # new pictures for every moment


class TurnEdit(Body):
    text: str = Field(min_length=1, max_length=2000)


class MomentEdit(Body):
    enabled: bool | None = None
    display: Display | None = None


class Regenerate(Body):
    prompt: str | None = Field(None, min_length=3, max_length=1200)


class RenderRequest(Body):
    fit_mb: int | None = Field(None, ge=5, le=500)


def _same_site(request: Request) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == request.headers.get("host", "")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = Services.create(settings)
    workers = Workers(services, HANDLERS, settings.workers)
    db = services.db

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ff.require_ffmpeg()
        if not settings.has_api_key:
            log.warning("MODEL_API_KEY is not set: the studio opens, but jobs will fail until it is")
        workers.start()
        try:
            yield
        finally:
            workers.stop()
            services.close()

    app = FastAPI(
        title="Storeel Studio",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = services

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable) -> Response:
        if request.method not in SAFE_METHODS:
            if not _same_site(request):
                return JSONResponse({"detail": "cross-site requests are not allowed"}, status_code=403)
            if request.url.path.endswith(UPLOAD_SUFFIXES):
                length = request.headers.get("content-length", "")
                if not length.isdigit():
                    return JSONResponse({"detail": "uploads need a Content-Length"}, status_code=411)
                if int(length) > settings.max_upload_mb * 1_000_000 + 1_000_000:
                    return JSONResponse(
                        {"detail": f"the file is larger than {settings.max_upload_mb} MB"}, status_code=413
                    )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # revalidate, so an update is never stale
        return response

    # Added last, so it runs first: unknown Host headers never reach the guard or the routes.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PipelineError)
    async def bad_input(_: Request, exc: PipelineError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ConfigError)
    async def misconfigured(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ValueError)
    async def invalid(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ---- helpers ----------------------------------------------------------------------------

    def load(project_id: str) -> Project:
        services.files(project_id)  # validates the id's shape
        return db.get_project(project_id)

    def idle(project_id: str) -> None:
        job = db.latest_job(project_id)
        if job is not None and job.active:
            raise Conflict(f"wait for the {job.kind} job to finish (or cancel it)")

    def edit(project_id: str, change: Callable[[Project], Any]) -> dict[str, Any]:
        load(project_id)
        idle(project_id)
        project, _ = db.update_project(project_id, change)
        return view(services, project)

    def start(project_id: str, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        settings.require_api_key()
        db.enqueue(project_id, kind, params)
        return view(services, load(project_id))

    def scene(project: Project, scene_id: str) -> Scene:
        if project.script is None:
            raise PipelineError("write the script first")
        found = next((s for s in project.script.scenes if s.id == scene_id), None)
        if found is None:
            raise NotFound(f"no scene {scene_id}")
        return found

    # ---- configuration and projects ---------------------------------------------------------

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "api_key": settings.has_api_key,
            "max_input_seconds": settings.max_input_seconds,
            "max_upload_mb": settings.max_upload_mb,
            "models": {
                "spark": settings.spark_model,
                "image": settings.image_model,
                "asr": settings.asr_model,
                "sam": settings.sam_model,
            },
            "style": Style.model_json_schema(),
            "idea": Idea.model_json_schema(),
        }

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [summary(services, p) for p in db.list_projects()]

    @app.post("/api/projects", status_code=201)
    def new_project(body: NewProject) -> dict[str, Any]:
        return view(services, create_project(services, body.path, body.title))

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return view(services, load(project_id))

    @app.patch("/api/projects/{project_id}")
    def rename(project_id: str, body: TitleEdit) -> dict[str, Any]:
        load(project_id)  # a title is safe to change while a job runs
        project, _ = db.update_project(
            project_id, lambda p: setattr(p, "title", " ".join(body.title.split()))
        )
        return view(services, project)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str) -> Response:
        load(project_id)
        idle(project_id)
        db.delete_project(project_id)
        services.files(project_id).remove_all()
        return Response(status_code=204)

    # ---- path A: clips ----------------------------------------------------------------------

    @app.post("/api/projects/{project_id}/clips")
    def upload_clip(project_id: str, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        project = load(project_id)
        if project.path != "video":
            raise PipelineError("this project records scenes; upload clips to a video project")
        idle(project_id)
        clip = import_clip(services, project, file.file, file.filename)

        def add(p: Project) -> None:
            p.clips.append(clip)
            p.invalidate_media()

        return edit(project_id, add)

    @app.delete("/api/projects/{project_id}/clips/{clip_id}")
    def delete_clip(project_id: str, clip_id: str) -> dict[str, Any]:
        removed: list[str] = []

        def drop(p: Project) -> None:
            keep = [c for c in p.clips if c.id != clip_id]
            if len(keep) == len(p.clips):
                raise NotFound(f"no clip {clip_id}")
            removed.extend(c.key for c in p.clips if c.id == clip_id)
            p.clips = keep
            p.invalidate_media()

        result = edit(project_id, drop)
        for key in removed:
            services.files(project_id).delete(key)
        return result

    @app.put("/api/projects/{project_id}/clips/order")
    def order_clips(project_id: str, body: ClipOrder) -> dict[str, Any]:
        def reorder(p: Project) -> None:
            if sorted(body.ids) != sorted(c.id for c in p.clips):
                raise PipelineError("the order must list every clip once")
            by_id = {c.id: c for c in p.clips}
            if [c.id for c in p.clips] != body.ids:
                p.clips = [by_id[i] for i in body.ids]
                p.invalidate_media()

        return edit(project_id, reorder)

    # ---- choices ----------------------------------------------------------------------------

    @app.put("/api/projects/{project_id}/style")
    def set_style(project_id: str, body: Style) -> dict[str, Any]:
        return edit(project_id, lambda p: setattr(p, "style", body))

    # ---- path B: idea, script and takes -----------------------------------------------------

    @app.put("/api/projects/{project_id}/idea")
    def set_idea(project_id: str, body: Idea) -> dict[str, Any]:
        project = load(project_id)
        if project.path != "idea":
            raise PipelineError("this project starts from a video")
        settings.require_api_key()
        old_takes: list[str] = []

        def save(p: Project) -> None:
            old_takes.extend(s.take.key for s in (p.script.scenes if p.script else []) if s.take)
            p.idea = body
            p.script = None
            p.invalidate_media()

        edit(project_id, save)
        for key in old_takes:
            services.files(project_id).delete(key)
        return start(project_id, "script")

    @app.put("/api/projects/{project_id}/script")
    def set_script(project_id: str, body: ScriptEdit) -> dict[str, Any]:
        removed: list[str] = []
        ids = [s.id for s in body.scenes]
        if len(set(ids)) != len(ids):
            raise PipelineError("scene ids must be unique")
        entity_ids = {e.id for e in body.entities}

        def save(p: Project) -> None:
            if p.script is None:
                raise PipelineError("write the script first")
            takes = {s.id: s.take for s in p.script.scenes if s.take}
            scenes = [
                Scene(
                    **s.model_dump(exclude={"entities"}), entities=[e for e in s.entities if e in entity_ids]
                )
                for s in body.scenes
            ]
            for item in scenes:
                item.take = takes.pop(item.id, None)
                if item.display == "none":
                    item.visual = ""
            removed.extend(t.key for t in takes.values())
            if removed:
                p.invalidate_media()
            p.script = Script(title=body.title, language=body.language, scenes=scenes, entities=body.entities)

        result = edit(project_id, save)
        for key in removed:
            services.files(project_id).delete(key)
        return result

    @app.post("/api/projects/{project_id}/scenes/{scene_id}/take")
    def upload_take(project_id: str, scene_id: str, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        project = load(project_id)
        idle(project_id)
        previous = scene(project, scene_id).take
        clip = import_clip(services, project, file.file, file.filename, replacing=previous)

        def attach(p: Project) -> None:
            scene(p, scene_id).take = clip
            p.invalidate_media()

        try:
            result = edit(project_id, attach)
        except BaseException:
            services.files(project_id).delete(clip.key)
            raise
        if previous is not None:
            services.files(project_id).delete(previous.key)
        return result

    @app.delete("/api/projects/{project_id}/scenes/{scene_id}/take")
    def delete_take(project_id: str, scene_id: str) -> dict[str, Any]:
        removed: list[str] = []

        def detach(p: Project) -> None:
            item = scene(p, scene_id)
            if item.take is not None:
                removed.append(item.take.key)
                item.take = None
                p.invalidate_media()

        result = edit(project_id, detach)
        for key in removed:
            services.files(project_id).delete(key)
        return result

    # ---- processing and review --------------------------------------------------------------

    @app.post("/api/projects/{project_id}/process")
    def process(project_id: str, body: ProcessRequest) -> dict[str, Any]:
        project = load(project_id)
        if not project.inputs():
            raise PipelineError("add a video first" if project.path == "video" else "record the scenes first")
        return start(project_id, "process", {"fresh": body.fresh})

    @app.put("/api/projects/{project_id}/turns/{turn_id}")
    def edit_turn(project_id: str, turn_id: int, body: TurnEdit) -> dict[str, Any]:
        def save(p: Project) -> None:
            if p.transcript is None:
                raise PipelineError("there is no transcript yet")
            for index, turn in enumerate(p.transcript.turns):
                if turn.id == turn_id:
                    p.transcript.turns[index] = retime(turn, body.text)
                    return
            raise NotFound(f"no turn {turn_id}")

        return edit(project_id, save)

    @app.patch("/api/projects/{project_id}/moments/{moment_id}")
    def edit_moment(project_id: str, moment_id: str, body: MomentEdit) -> dict[str, Any]:
        if body.display is not None:
            settings.require_api_key()  # a new shape needs a new picture
        changed_display: list[bool] = []

        def save(p: Project) -> None:
            moment = next((m for m in (p.analysis.moments if p.analysis else []) if m.id == moment_id), None)
            if moment is None:
                raise NotFound(f"no moment {moment_id}")
            if body.enabled is not None:
                moment.enabled = body.enabled
            if body.display is not None and body.display != moment.display:
                moment.display = body.display
                moment.note = None
                changed_display.append(True)

        result = edit(project_id, save)
        if changed_display:  # a card and a full-screen picture have different shapes
            return start(project_id, "regenerate", {"moment_id": moment_id, "new_take": False})
        return result

    @app.post("/api/projects/{project_id}/moments/{moment_id}/regenerate")
    def regenerate(project_id: str, moment_id: str, body: Regenerate) -> dict[str, Any]:
        def save(p: Project) -> None:
            moment = next((m for m in (p.analysis.moments if p.analysis else []) if m.id == moment_id), None)
            if moment is None:
                raise NotFound(f"no moment {moment_id}")
            if body.prompt:
                moment.prompt = " ".join(body.prompt.split())

        settings.require_api_key()
        edit(project_id, save)
        return start(project_id, "regenerate", {"moment_id": moment_id, "new_take": True})

    @app.post("/api/projects/{project_id}/render")
    def render(project_id: str, body: RenderRequest) -> dict[str, Any]:
        project = load(project_id)
        if project.analysis is None or project.transcript is None:
            raise PipelineError("process the video first")
        db.enqueue(project_id, "render", {"fit_mb": body.fit_mb})  # no Model API calls
        return view(services, load(project_id))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        job = db.cancel(job_id)
        return view(services, load(job.project_id))

    # ---- media and the UI -------------------------------------------------------------------

    @app.get("/api/projects/{project_id}/media/{key:path}")
    def media(project_id: str, key: str, download: bool = False) -> FileResponse:
        project = load(project_id)
        if not key.startswith(MEDIA_PREFIXES):
            raise NotFound("no such file")
        path = services.files(project_id).path(key)
        if not path.is_file():
            raise NotFound("no such file")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {"Cache-Control": "private, max-age=3600"}
        if download:
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in project.title)[:60].strip("-")
            name = f"{safe or 'reel'}-{path.stem.removeprefix('reel-')}{path.suffix}"
            return FileResponse(path, media_type=media_type, headers=headers, filename=name)
        return FileResponse(path, media_type=media_type, headers=headers)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/font.ttf", include_in_schema=False)
    def font() -> FileResponse:
        return FileResponse(
            FONT_FILE, media_type="font/ttf", headers={"Cache-Control": "public, max-age=604800"}
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app
