"""HTTP API for the studio, plus the static single-page UI.

Each user brings their own Model API key: the browser sends it with the requests that start
a job, and the server keeps it in memory only until that job ends (see services.KeyVault).
There is no login. On your own machine the studio binds to 127.0.0.1 and everything is open;
hosted, private projects give each browser only its own reels and novels (see owners.py). It
accepts only known Host headers (blocking DNS-rebinding), and refuses state-changing requests
sent by other web sites (Origin / Sec-Fetch-Site checks). Uploads are size-checked before
they are read.

Each step of the flow is an action on the backend; the UI only calls them. While a job runs,
a project accepts no edits except cancelling, so a job never works on data that changes
under it.
"""

from __future__ import annotations

import contextlib
import logging
import mimetypes
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..common import now_iso
from ..config import ConfigError, Settings, get_settings
from ..db import Conflict, NotFound
from ..estimate import estimate_part
from ..jobs import PipelineError, Workers
from ..maintenance import Cleaner
from ..media import ffmpeg as ff
from ..meta import MetaAPIError
from ..models import (
    DEFAULT_TITLE,
    AgentChat,
    AgentMessage,
    Display,
    Genre,
    Idea,
    Narration,
    Novel,
    Poll,
    Project,
    Scene,
    Script,
    ScriptEdit,
    Style,
    VisualStyle,
    text_model_name,
)
from ..novels import add_chapter, create_novel, novel_summary, novel_view, open_chapter
from ..pipeline.render import FONT_FILE
from ..pipeline.run import HANDLERS
from ..pipeline.story import apply_edit, narration_options
from ..pipeline.transcribe import retime
from ..projects import create_project, import_clip, is_showcase, summary, view
from ..services import Services, valid_key
from . import owners

log = logging.getLogger(__name__)


def _frontend_dir() -> Path:
    """Where the single-page app is served from.

    Defaults to the bundled `static/` folder; a deployment (e.g. Modal) can point
    STOREEL_FRONTEND_DIR at a built Vite app instead. The chosen folder must hold an
    `index.html`; its `assets/` sub-folder (Vite's hashed bundles) is served if present.
    """
    import os

    override = os.environ.get("STOREEL_FRONTEND_DIR", "").strip()
    bundled = Path(__file__).resolve().parent / "static"
    if override and (Path(override) / "index.html").is_file():
        return Path(override)
    return bundled


STATIC = _frontend_dir()
MEDIA_PREFIXES = ("uploads/", "refs/", "assets/", "renders/", "part/")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
UPLOAD_SUFFIXES = ("/clips", "/take")
KEY_HEADER = "x-model-api-key"
# The jobs that call the Model API ("agent_apply" carries a key only when it draws pictures).
KEYED_JOBS = frozenset({"script", "story", "process", "regenerate", "agent"})


class KeyRequired(Exception):
    """The request needs the user's Model API key and did not carry a usable one."""


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
    render: bool = False  # a novel part: render the reel once its pictures are drawn


class PartRequest(Body):
    from_video: bool = False  # make the part from the user's own video of it, not from the chapter
    brief: str | None = Field(None, max_length=600)  # what the creator asks the writer for ("" clears it)


class TurnEdit(Body):
    text: str = Field(min_length=1, max_length=2000)


class MomentEdit(Body):
    enabled: bool | None = None
    display: Display | None = None


class Regenerate(Body):
    prompt: str | None = Field(None, min_length=3, max_length=1200)


class RenderRequest(Body):
    fit_mb: int | None = Field(None, ge=5, le=500)


class AgentRequest(Body):
    message: str = Field(min_length=1, max_length=2000)


class AgentDecision(Body):
    approve: list[str] = Field(default_factory=list, max_length=50)  # the rest are dismissed


class NovelFields(Body):
    title: str = Field(min_length=1, max_length=120)
    synopsis: str = Field("", max_length=4000)
    language: Literal["id", "en"] = "id"
    narration: Narration = "casual"
    visual_style: VisualStyle = "realistic_3d"
    watermark: str = Field("", max_length=60)
    genre: Genre = "auto"  # its parts' theme; "auto": Muse Spark picks it as the first part is written


class NewChapter(Body):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = Field("", max_length=160)
    number: int | None = Field(None, ge=1, le=999)


class ChapterEdit(Body):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = Field("", max_length=160)


class BeatEdit(Body):
    text: str = Field(min_length=1, max_length=400)
    direction: str = Field("", max_length=200)


class StoryEdit(Body):
    chapter_title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=400)
    hook_direction: str = Field("", max_length=200)
    beats: list[BeatEdit] = Field(min_length=1, max_length=40)
    poll: Poll
    cta: str = Field(min_length=1, max_length=400)


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
        if settings.has_api_key:
            log.info("MODEL_API_KEY is only used by `storeel make`; the studio asks each user for theirs")
        workers.start()
        cleaner = Cleaner(services, settings.ttl_hours, settings.showcase) if settings.ttl_hours else None
        if cleaner is not None:
            cleaner.start()
            log.info("cleanup: reels and novels untouched for %gh are deleted", settings.ttl_hours)
        try:
            yield
        finally:
            if cleaner is not None:
                cleaner.stop()
            workers.stop()

    app = FastAPI(
        title="Storeel Studio",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = services

    def access(method: str, path: str, owner: str) -> JSONResponse | None:
        """Refuse a request for someone else's reel or novel, or a change to the showcase."""
        write = method not in SAFE_METHODS
        what, item_owner, showcase = "", None, False
        try:
            if match := owners.PROJECT_PATH.match(path):
                project = db.get_project(match[1])
                what, item_owner, showcase = "reel", project.owner, is_showcase(services, project)
            elif match := owners.NOVEL_PATH.match(path):
                novel = db.get_novel(match[1])
                what, item_owner, showcase = "novel", novel.owner, novel.id in settings.showcase
            elif match := owners.JOB_PATH.match(path):
                project = db.get_project(db.get_job(match[1]).project_id)
                what, item_owner, showcase = "reel", project.owner, is_showcase(services, project)
                write = True  # a job is only ever cancelled
            else:
                return None
        except NotFound:
            return None  # the route answers "not found" itself
        verdict = owners.allowed(
            owner, item_owner, private=settings.private_projects, showcase=showcase, write=write
        )
        if verdict == "read-only":
            message = f"this {what} is a showcase: it can be watched, not changed"
            return JSONResponse({"detail": message, "code": "showcase"}, status_code=403)
        if verdict == "hidden":
            return JSONResponse({"detail": f"no {what} with that id"}, status_code=404)
        return None

    # Defined before the guard, so it runs after it: a cross-site request is refused first.
    @app.middleware("http")
    async def ownership(request: Request, call_next: Callable) -> Response:
        token, fresh = owners.token_from(request)
        request.state.owner = owners.owner_of(token)
        refused = None
        if request.url.path.startswith("/api/"):
            refused = await run_in_threadpool(access, request.method, request.url.path, request.state.owner)
        response = refused or await call_next(request)
        if fresh:
            response.set_cookie(
                owners.COOKIE,
                token,
                max_age=owners.MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=owners.served_over_https(request),
                path="/",
            )
        return response

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable) -> Response:
        if request.method not in SAFE_METHODS:
            if not _same_site(request):
                return JSONResponse({"detail": "cross-site requests are not allowed"}, status_code=403)
            if request.url.path.endswith(UPLOAD_SUFFIXES):
                length = request.headers.get("content-length", "")
                # Reject an oversized body up front when the length is declared. A missing or
                # non-numeric length (e.g. a chunked upload behind a proxy) is allowed through:
                # import_clip streams the body in chunks and enforces max_upload_mb itself.
                if length.isdigit() and int(length) > settings.max_upload_mb * 1_000_000 + 1_000_000:
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

    @app.exception_handler(KeyRequired)
    async def key_required(_: Request, exc: KeyRequired) -> JSONResponse:
        message = str(exc) or "add your Meta Model API key first"
        return JSONResponse({"detail": message, "code": "api_key_required"}, status_code=401)

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

    def user_key(request: Request) -> str:
        raw = request.headers.get(KEY_HEADER)
        key = valid_key(raw)
        if key is None:
            raise KeyRequired("" if raw is None else "that does not look like a Model API key")
        return key

    def start(
        project_id: str, kind: str, params: dict[str, Any] | None = None, key: str | None = None
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        if kind in KEYED_JOBS and key is None:
            raise KeyRequired()
        if key is not None:  # held before the job exists, so no worker can run it keyless
            services.keys.put(job_id, key)
        try:
            db.enqueue(project_id, kind, params, job_id=job_id)
        except BaseException:
            services.keys.drop(job_id)
            raise
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
            "bring_your_own_key": True,
            "max_input_seconds": settings.max_input_seconds,
            "max_upload_mb": settings.max_upload_mb,
            "ttl_hours": settings.ttl_hours,  # 0: reels are kept until deleted
            "models": {
                "script": settings.script_model,
                "script_name": text_model_name(settings.script_model),
                "script_effort": settings.script_effort,
                "plan": settings.plan_model,
                "plan_name": text_model_name(settings.plan_model),
                "plan_effort": settings.plan_effort,
                "image": settings.image_model,
                "asr": settings.asr_model,
                "sam": settings.sam_model,
            },
            "style": Style.model_json_schema(),
            "idea": Idea.model_json_schema(),
            "novel": Novel.model_json_schema(),
            "narration": narration_options(),
        }

    @app.post("/api/key/check")
    def check_key(request: Request) -> JSONResponse:
        """Ask Meta which models the user's key can use (nothing is stored)."""
        key = user_key(request)
        client = services.client(key, max_attempts=2)
        try:
            models = client.list_models()
        except MetaAPIError as exc:
            status = 401 if exc.status in (401, 403) else 502
            return JSONResponse({"detail": f"Meta did not accept the key: {exc}"}, status_code=status)
        finally:
            client.close()
        needed = [
            settings.script_model,
            settings.plan_model,
            settings.image_model,
            settings.asr_model,
            settings.sam_model,
        ]
        needed = list(dict.fromkeys(needed))
        return JSONResponse({"ok": True, "models": models, "missing": [m for m in needed if m not in models]})

    @app.get("/api/estimate/part")
    def part_estimate(
        chars: Annotated[int, Query(ge=0, le=200_000)],
        background: Annotated[Literal["dalang", "scene", "studio"], Query()] = "dalang",
    ) -> dict[str, float | int]:
        """What making a part of a chapter this long costs at list prices (nothing runs), in the
        look chosen for it (every look cuts the speaker out all through, so they can step back
        under the pictures; the scene and studio looks also put something behind them)."""
        return estimate_part(chars, background)

    @app.get("/api/projects")
    def list_projects(request: Request) -> list[dict[str, Any]]:
        owner = request.state.owner
        return [
            summary(services, p)
            for p in db.list_projects()
            if not settings.private_projects or p.owner == owner or is_showcase(services, p)
        ]

    @app.post("/api/projects", status_code=201)
    def new_project(body: NewProject, request: Request) -> dict[str, Any]:
        return view(services, create_project(services, body.path, body.title, owner=request.state.owner))

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
        if project.path == "idea":
            raise PipelineError("this project records scenes; upload clips to a video project")
        if project.path == "novel" and project.clips:
            raise PipelineError("a part takes one video: remove the current one first")
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
    def set_idea(project_id: str, body: Idea, request: Request) -> dict[str, Any]:
        project = load(project_id)
        if project.path != "idea":
            raise PipelineError("this project starts from a video")
        key = user_key(request)  # before anything changes, so a missing key loses nothing
        old_takes: list[str] = []

        def save(p: Project) -> None:
            old_takes.extend(s.take.key for s in (p.script.scenes if p.script else []) if s.take)
            p.idea = body
            p.script = None
            p.invalidate_media()

        edit(project_id, save)
        for take in old_takes:
            services.files(project_id).delete(take)
        return start(project_id, "script", key=key)

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
            if p.path == "novel":
                raise PipelineError("edit a novel part's words in the part script")
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
    def process(project_id: str, body: ProcessRequest, request: Request) -> dict[str, Any]:
        project = load(project_id)
        if not project.inputs():
            raise PipelineError("add a video first" if project.path == "video" else "record the scenes first")
        params: dict[str, Any] = {"fresh": body.fresh}
        if body.render and project.path == "novel":
            params["render"] = True
        return start(project_id, "process", params, key=user_key(request))

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
    def edit_moment(project_id: str, moment_id: str, body: MomentEdit, request: Request) -> dict[str, Any]:
        key = user_key(request) if body.display is not None else None  # a new shape needs a new picture
        changed_display: list[bool] = []

        def save(p: Project) -> None:
            moment = next((m for m in (p.analysis.moments if p.analysis else []) if m.id == moment_id), None)
            if moment is None:
                raise NotFound(f"no moment {moment_id}")
            if body.enabled is not None:
                moment.enabled = body.enabled
            if body.display is not None and body.display != moment.display:
                moment.display = body.display
                moment.chosen = True  # the layout setting no longer overrides this picture
                moment.note = None
                changed_display.append(True)

        result = edit(project_id, save)
        if changed_display:  # a card and a full-screen picture have different shapes
            return start(project_id, "regenerate", {"moment_id": moment_id, "new_take": False}, key=key)
        return result

    @app.post("/api/projects/{project_id}/moments/{moment_id}/regenerate")
    def regenerate(project_id: str, moment_id: str, body: Regenerate, request: Request) -> dict[str, Any]:
        def save(p: Project) -> None:
            moment = next((m for m in (p.analysis.moments if p.analysis else []) if m.id == moment_id), None)
            if moment is None:
                raise NotFound(f"no moment {moment_id}")
            if body.prompt:
                moment.prompt = " ".join(body.prompt.split())

        key = user_key(request)
        edit(project_id, save)
        return start(project_id, "regenerate", {"moment_id": moment_id, "new_take": True}, key=key)

    # ---- path C: novels, chapters and parts ---------------------------------------------------

    def load_novel(novel_id: str) -> Novel:
        services.novel_files(novel_id)  # validates the id's shape
        return db.get_novel(novel_id)

    @app.get("/api/novels")
    def list_novels(request: Request) -> list[dict[str, Any]]:
        owner = request.state.owner
        return [
            novel_summary(services, n)
            for n in db.list_novels()
            if not settings.private_projects or n.owner == owner or n.id in settings.showcase
        ]

    @app.post("/api/novels", status_code=201)
    def new_novel(body: NovelFields, request: Request) -> dict[str, Any]:
        return novel_view(services, create_novel(services, **body.model_dump(), owner=request.state.owner))

    @app.get("/api/novels/{novel_id}")
    def get_novel(novel_id: str) -> dict[str, Any]:
        return novel_view(services, load_novel(novel_id))

    @app.put("/api/novels/{novel_id}")
    def edit_novel(novel_id: str, body: NovelFields) -> dict[str, Any]:
        load_novel(novel_id)
        fields = body.model_dump()
        if "genre" not in body.model_fields_set:  # a form without it (the older UI) keeps the genre
            del fields["genre"]

        def save(n: Novel) -> None:
            for name, value in fields.items():
                setattr(n, name, value)

        novel, _ = db.update_novel(novel_id, save)
        return novel_view(services, novel)

    @app.delete("/api/novels/{novel_id}", status_code=204)
    def delete_novel(novel_id: str) -> Response:
        novel = load_novel(novel_id)
        reels = [c.project_id for c in novel.chapters if c.project_id]
        for project_id in reels:
            with contextlib.suppress(NotFound):
                idle(project_id)
        for project_id in reels:
            with contextlib.suppress(NotFound):
                db.delete_project(project_id)
            services.files(project_id).remove_all()
        db.delete_novel(novel_id)
        services.novel_files(novel_id).remove_all()
        return Response(status_code=204)

    @app.post("/api/novels/{novel_id}/chapters", status_code=201)
    def new_chapter(novel_id: str, body: NewChapter) -> dict[str, Any]:
        load_novel(novel_id)
        return novel_view(services, add_chapter(services, novel_id, body.text, body.title, body.number))

    @app.put("/api/novels/{novel_id}/chapters/{number}")
    def edit_chapter(novel_id: str, number: int, body: ChapterEdit) -> dict[str, Any]:
        load_novel(novel_id)
        if len(body.text.strip()) < 200:
            raise PipelineError("paste the whole chapter text (at least a few paragraphs)")

        def save(n: Novel) -> None:
            chapter = n.chapter(number)
            if chapter is None:
                raise NotFound(f"no chapter {number}")
            chapter.text, chapter.title = body.text.strip(), " ".join(body.title.split())

        novel, _ = db.update_novel(novel_id, save)
        return novel_view(services, novel)

    @app.delete("/api/novels/{novel_id}/chapters/{number}")
    def delete_chapter(novel_id: str, number: int) -> dict[str, Any]:
        novel = load_novel(novel_id)
        chapter = novel.chapter(number)
        if chapter is None:
            raise NotFound(f"no chapter {number}")
        if chapter.project_id:
            with contextlib.suppress(NotFound):
                idle(chapter.project_id)
                db.delete_project(chapter.project_id)
            services.files(chapter.project_id).remove_all()

        def drop(n: Novel) -> None:
            n.chapters = [c for c in n.chapters if c.number != number]
            # What this chapter added to the bible goes with it.
            n.bible.characters = {k: c for k, c in n.bible.characters.items() if c.created_in != number}
            n.bible.props = {k: p for k, p in n.bible.props.items() if p.created_in != number}
            for c in n.bible.characters.values():
                c.notes = [x for x in c.notes if x.chapter != number]
                c.looks = [x for x in c.looks if x.chapter != number]

        novel, _ = db.update_novel(novel_id, drop)
        return novel_view(services, novel)

    @app.post("/api/novels/{novel_id}/chapters/{number}/reel")
    def chapter_reel(novel_id: str, number: int) -> dict[str, Any]:
        load_novel(novel_id)
        return view(services, open_chapter(services, novel_id, number))

    @app.get("/api/novels/{novel_id}/media/{key:path}")
    def novel_media(novel_id: str, key: str) -> FileResponse:
        load_novel(novel_id)
        if not key.startswith("bible/"):
            raise NotFound("no such file")
        path = services.novel_files(novel_id).path(key)
        if not path.is_file():
            raise NotFound("no such file")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/projects/{project_id}/story")
    def write_part(project_id: str, request: Request, body: PartRequest | None = None) -> dict[str, Any]:
        project = load(project_id)
        if project.path != "novel":
            raise PipelineError("this reel is not a novel chapter")
        from_video = bool(body and body.from_video)
        if from_video and not project.clips:
            raise PipelineError("upload your video of the part first")
        key = user_key(request)  # before anything changes, so a missing key loses nothing
        if body is not None and body.brief is not None:
            brief = " ".join(body.brief.split())
            edit(project_id, lambda p: setattr(p, "brief", brief))
        params = {"from_video": True} if from_video else {}
        return start(project_id, "story", params, key=key)

    @app.put("/api/projects/{project_id}/story")
    def edit_part(project_id: str, body: StoryEdit) -> dict[str, Any]:
        project = load(project_id)
        if project.novel_id is None:
            raise PipelineError("this reel is not a novel chapter")
        novel = load_novel(project.novel_id)

        def save(p: Project) -> None:
            apply_edit(
                p,
                novel,
                chapter_title=body.chapter_title,
                hook=body.hook,
                hook_direction=body.hook_direction,
                beats=[(b.text, b.direction) for b in body.beats],
                poll=body.poll,
                cta=body.cta,
            )

        return edit(project_id, save)

    @app.post("/api/projects/{project_id}/render")
    def render(project_id: str, body: RenderRequest, request: Request) -> dict[str, Any]:
        project = load(project_id)
        if project.analysis is None or project.transcript is None:
            raise PipelineError("process the video first")
        # Free: the key, when the user gave one, is used only for a look chosen after processing
        # (SAM tracking them for a title behind them, or finding their face).
        key = valid_key(request.headers.get(KEY_HEADER))
        return start(project_id, "render", {"fit_mb": body.fit_mb}, key=key)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        job = db.cancel(job_id)
        return view(services, load(job.project_id))

    # ---- the editing agent ------------------------------------------------------------------

    @app.post("/api/projects/{project_id}/agent")
    def agent_message(project_id: str, body: AgentRequest, request: Request) -> dict[str, Any]:
        project = load(project_id)
        if project.transcript is None:
            raise PipelineError("process the video first: the editor works on its captions and pictures")
        key = user_key(request)  # before anything changes, so a missing key loses nothing
        text = body.message.strip()
        if not text:
            raise PipelineError("write what to change")

        def add(p: Project) -> None:
            p.agent.dismiss_pending()  # a new request replaces the proposals not yet approved
            p.agent.messages.append(AgentMessage(role="user", text=text, created_at=now_iso()))

        edit(project_id, add)
        return start(project_id, "agent", key=key)

    @app.post("/api/projects/{project_id}/agent/decide")
    def agent_decide(project_id: str, body: AgentDecision, request: Request) -> dict[str, Any]:
        project = load(project_id)
        approve = set(body.approve)
        pending = project.agent.latest_actions("pending")
        chosen = [a for a in pending if a.id in approve]
        # A new picture or outfit calls Muse Image; a render alone uses the key only if it was
        # given (to track the speaker for a title behind them, see render).
        if any(a.kind in ("picture", "outfit") for a in chosen):
            key: str | None = user_key(request)
        else:
            key = valid_key(request.headers.get(KEY_HEADER))

        def decide(p: Project) -> None:
            for action in p.agent.latest_actions("pending"):
                action.status = "approved" if action.id in approve else "dismissed"

        result = edit(project_id, decide)
        if not chosen:
            return result
        return start(project_id, "agent_apply", key=key)

    @app.delete("/api/projects/{project_id}/agent")
    def agent_clear(project_id: str) -> dict[str, Any]:
        return edit(project_id, lambda p: setattr(p, "agent", AgentChat()))

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

    # A built Vite app references its hashed bundles under /assets; serve them when present.
    assets_dir = STATIC / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/font.ttf", include_in_schema=False)
    def font() -> FileResponse:
        return FileResponse(
            FONT_FILE, media_type="font/ttf", headers={"Cache-Control": "public, max-age=604800"}
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    # Serve files Vite emits at the web root (favicon, icons, manifest, …) without a catch-all:
    # the SPA uses hash routing, so no non-asset path needs to resolve to index.html.
    @app.get("/{filename}", include_in_schema=False)
    def root_file(filename: str) -> FileResponse:
        candidate = (STATIC / filename).resolve()
        if candidate.is_file() and candidate.is_relative_to(STATIC.resolve()) and "/" not in filename:
            media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            return FileResponse(candidate, media_type=media_type, headers={"Cache-Control": "no-cache"})
        raise NotFound("no such file")

    return app
