"""Job handlers: what each kind of background job does, stage by stage."""

from __future__ import annotations

from ..jobs import Handler, JobContext, PipelineError
from ..models import Analysis, Project
from .analyze import analyze
from .assets import make_anchors, make_pictures
from .compose import compose
from .detect import find_faces, references
from .ingest import ingest
from .script import write_script
from .transcribe import transcribe


def _language(project: Project) -> str:
    if project.path == "idea" and project.script is not None:
        return project.script.language
    return project.style.language


def _keywords(project: Project) -> list[str]:
    """Names from the script, so the transcription spells them the way the script does."""
    if project.script is None:
        return []
    return [e.name for e in project.script.entities if e.name]


def _pictures(ctx: JobContext, project: Project, analysis: Analysis, only: set[str] | None) -> None:
    source = project.source
    if source is None:
        raise PipelineError("process the clips first")
    style = ctx.project().style
    changed = analysis.apply_layout(style.picture_layout)
    if changed:

        def relayout(p: Project) -> None:
            if p.analysis is not None:
                p.analysis.apply_layout(style.picture_layout)

        ctx.update(relayout)
        ctx.log(f"layout {style.picture_layout}: {len(changed)} picture(s) change shape")
    ctx.step("Finding faces and references", 0.55, 0.65)
    references(ctx, source, analysis)
    find_faces(ctx, source, analysis, style, only)
    ctx.flush_usage()
    ctx.step("Generating pictures", 0.65, 1.0)
    make_anchors(ctx, analysis, style, only)
    make_pictures(ctx, analysis, style, only)


def handle_script(ctx: JobContext) -> None:
    ctx.step("Writing the script", 0.0, 1.0)
    write_script(ctx)


def handle_process(ctx: JobContext) -> None:
    """Ingest -> transcribe -> plan pictures -> SAM -> Muse Image. Every stage reuses what it
    made before when its inputs have not changed, so a retry only redoes what is missing."""
    if ctx.params.get("fresh"):  # "redo all pictures": new takes for every moment

        def bump(p: Project) -> None:
            for moment in p.analysis.moments if p.analysis else []:
                moment.take += 1

        ctx.update(bump)
    ctx.step("Preparing the video", 0.0, 0.25)
    source = ingest(ctx)
    ctx.flush_usage()
    ctx.check()
    project = ctx.project()
    ctx.step("Transcribing", 0.25, 0.35)
    transcript = transcribe(ctx, source, _language(project), _keywords(project))
    ctx.flush_usage()
    ctx.check()
    ctx.step("Planning the pictures", 0.35, 0.55)
    analysis = analyze(ctx, source, transcript)
    ctx.flush_usage()
    ctx.check()
    _pictures(ctx, ctx.project(), analysis, None)


def handle_regenerate(ctx: JobContext) -> None:
    """A new picture for one moment (after the user edited its prompt or display)."""
    moment_id = str(ctx.params.get("moment_id") or "")

    def bump(p: Project) -> None:
        moment = next((m for m in (p.analysis.moments if p.analysis else []) if m.id == moment_id), None)
        if moment is None:
            raise PipelineError(f"no moment {moment_id!r}")
        if ctx.params.get("new_take", True):
            moment.take += 1
        moment.enabled = True

    project, _ = ctx.update(bump)
    assert project.analysis is not None
    _pictures(ctx, project, project.analysis, {moment_id})


def handle_render(ctx: JobContext) -> None:
    ctx.step("Rendering the reel", 0.0, 1.0)
    project = ctx.project()
    if project.transcript is None or project.analysis is None:
        raise PipelineError("process the clips before rendering")
    fit = ctx.params.get("fit_mb")
    compose(ctx, project, fit_mb=int(fit) if fit else None)


HANDLERS: dict[str, Handler] = {
    "script": handle_script,
    "process": handle_process,
    "regenerate": handle_regenerate,
    "render": handle_render,
}
