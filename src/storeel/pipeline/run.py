"""Job handlers: what each kind of background job does, stage by stage."""

from __future__ import annotations

import contextlib

from ..common import Cancelled
from ..jobs import Handler, JobContext, PipelineError, describe_error
from ..models import AgentAction, Analysis, BibleCharacter, Novel, PartPicture, Project
from .agent import handle_agent
from .analyze import analyze
from .assets import make_anchors, make_pictures
from .compose import compose
from .cutout import needed as cutout_needed
from .cutout import track_reel
from .depth import needed as title_needs_masks
from .depth import track_speaker
from .detect import find_faces, references
from .emphasis import pick_emphasis
from .genre import pick_genre
from .ingest import ingest
from .motion import Renderer
from .part import find_part_faces, make_part_pictures, outfit_entry, outfit_redraws
from .script import write_script
from .story import WRITE_STEP, write_story
from .story_compose import PartCompositor
from .transcribe import transcribe


def _language(project: Project) -> str:
    if project.path in ("idea", "novel") and project.script is not None:
        return project.script.language
    return project.style.language


def _keywords(project: Project) -> list[str]:
    """Names from the script, so the transcription spells them the way the script does."""
    if project.story is not None:
        return [c.name for c in project.story.characters if c.name]
    if project.script is None:
        return []
    return [e.name for e in project.script.entities if e.name]


def _pictures(
    ctx: JobContext,
    project: Project,
    analysis: Analysis,
    only: set[str] | None,
    span: tuple[float, float] = (0.55, 1.0),
) -> None:
    """Faces, references and pictures for the moments in `only` (all when None), over `span`
    of the job's progress bar."""
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
    start, end = span
    middle = start + (end - start) * 0.22
    ctx.step("Finding faces and references", start, middle)
    references(ctx, source, analysis)
    find_faces(ctx, source, analysis, style, only)
    ctx.flush_usage()
    if only is None and title_needs_masks(ctx.project()):
        track_speaker(ctx)
        ctx.flush_usage()
    if only is None and cutout_needed(ctx.project()):
        track_reel(ctx)
        ctx.flush_usage()
    ctx.step("Generating pictures", middle, end)
    make_anchors(ctx, analysis, style, only)
    make_pictures(ctx, analysis, style, only)


def _part_pictures(ctx: JobContext, end: float = 1.0) -> None:
    """A novel part: its pictures come from its script (no planner), plus the face per take.
    The pictures fill the progress bar from 0.35 up to `end`."""
    ctx.step("Drawing the part's pictures", 0.35, end - 0.08)
    make_part_pictures(ctx)
    ctx.flush_usage()
    ctx.check()
    if ctx.project().style.speaker_behind == "auto":
        ctx.step("Finding the face", end - 0.08, end - 0.04)
        find_part_faces(ctx)
    if title_needs_masks(ctx.project()):
        ctx.step("Tracking you for the title", end - 0.04, end)
        track_speaker(ctx)
        ctx.flush_usage()
    if cutout_needed(ctx.project()):
        ctx.step("Cutting you out of the video", end - 0.04, end)
        track_reel(ctx)
        ctx.flush_usage()

    def done(p: Project) -> None:  # the reel is processed: an empty plan marks it (no moments)
        title = p.title
        p.analysis = Analysis(
            title=title, summary="", language=_language(p), entities=[], moments=[], digest="part"
        )

    ctx.update(done)


def handle_script(ctx: JobContext) -> None:
    ctx.step("Writing the script", 0.0, 1.0)
    write_script(ctx)


def handle_story(ctx: JobContext) -> None:
    pick_genre(ctx)  # a novel on "auto" gets its genre (its parts' theme) from its first part
    ctx.flush_usage()
    if not ctx.params.get("from_video"):
        ctx.step(WRITE_STEP, 0.0, 0.6)
        write_story(ctx)
        return
    # From the user's own video of the part: what they said becomes the part's words.
    project = ctx.project()
    if not project.clips:
        raise PipelineError("upload your video of the part first")
    ctx.step("Preparing the video", 0.0, 0.2)
    source = ingest(ctx)
    ctx.flush_usage()
    ctx.check()
    ctx.step("Transcribing", 0.2, 0.35)
    names = _keywords(project)  # a part made before: its characters; and the earlier parts' cast
    with contextlib.suppress(LookupError):
        novel = ctx.services.db.get_novel(project.novel_id or "")
        names += [c.name for c in novel.bible.before(project.chapter or 1).characters.values()]
    transcript = transcribe(ctx, source, _language(project), names)
    ctx.flush_usage()
    pick_emphasis(ctx, transcript)
    ctx.flush_usage()
    ctx.check()
    ctx.step("Making the part from your video", 0.35, 1.0)
    write_story(ctx, transcript.turns)


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
    pick_emphasis(ctx, transcript)
    ctx.flush_usage()
    ctx.check()
    if project.path == "novel":
        # The studio's first pass (approved as a whole) goes on to render the reel.
        then_render = bool(ctx.params.get("render"))
        _part_pictures(ctx, end=0.8 if then_render else 1.0)
        if then_render:
            ctx.flush_usage()
            ctx.check()
            ctx.step("Rendering the reel", 0.8, 1.0)
            _render(ctx, None)
        return
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
    fit = ctx.params.get("fit_mb")
    _render(ctx, int(fit) if fit else None)


def _render(ctx: JobContext, fit_mb: int | None) -> None:
    project = ctx.project()
    if project.transcript is None or project.analysis is None:
        raise PipelineError("process the clips before rendering")
    keyed = ctx.services.keys.get(ctx.job.id) is not None  # renders are free; a key is optional
    if keyed and title_needs_masks(project):
        track_speaker(ctx)  # "behind" chosen after processing (reuses the masks when they fit)
        ctx.flush_usage()
        project = ctx.project()
    if keyed and cutout_needed(project):
        track_reel(ctx)  # a cut-out background chosen after processing (reused when it fits)
        ctx.flush_usage()
        project = ctx.project()
    compositor = None
    if project.path == "novel":
        if keyed and project.style.speaker_behind == "auto" and not project.part_faces:
            find_part_faces(ctx)  # chosen after processing: check the face now
            project = ctx.project()
        cast: dict[str, BibleCharacter] = {}
        genre = None  # the novel's, for a part on the theme "auto"
        novel_files = None
        if project.novel_id:
            novel_files = ctx.services.novel_files(project.novel_id)
            with contextlib.suppress(LookupError):  # the novel is gone: the part's own cast only
                novel = ctx.services.db.get_novel(project.novel_id)
                cast, genre = novel.bible.characters, novel.genre
        compositor = PartCompositor(
            project,
            ctx.files,
            novel_files,
            cast,
            motion=Renderer(ctx.files, ctx.log, ctx.cancelled),
            genre=genre,
        )
    compose(ctx, project, fit_mb=fit_mb, compositor=compositor)


def handle_agent_apply(ctx: JobContext) -> None:
    """Run what the user approved from the editing agent: new pictures and outfits first, so
    the render after them shows them."""
    approved = ctx.project().agent.latest_actions("approved")
    if not approved:
        raise PipelineError("there is nothing approved to run")
    pictures = [a for a in approved if a.kind == "picture"]
    outfits = [a for a in approved if a.kind == "outfit"]
    render = next((a for a in approved if a.kind == "render"), None)
    drawn_by = 0.7 if render else 1.0  # where drawing ends on the progress bar
    errors: dict[str, str | None] = {}  # action id -> why it failed (None: done)
    try:
        if pictures:
            ids = _prepare_pictures(ctx, pictures, errors)
            if ids:
                project = ctx.project()
                assert project.analysis is not None
                _pictures(ctx, project, project.analysis, ids, span=(0.0, drawn_by))
                after = ctx.project().analysis
                moments = {m.id: m for m in (after.moments if after else [])}
                for action in pictures:
                    if action.id not in errors:
                        moment = moments.get(action.moment_id or "")
                        errors[action.id] = "the picture is gone" if moment is None else moment.error
            ctx.flush_usage()
            ctx.check()
        if outfits:
            ctx.step("Drawing the new outfits", 0.0, drawn_by)
            _apply_outfits(ctx, outfits, errors)
            ctx.flush_usage()
            ctx.check()
        if render is not None:
            ctx.step("Rendering the reel", drawn_by if pictures or outfits else 0.0, 1.0)
            _render(ctx, render.fit_mb)
            errors[render.id] = None
    except BaseException as exc:
        reason = "cancelled" if isinstance(exc, Cancelled) else describe_error(exc)
        for action in approved:
            errors.setdefault(action.id, reason)
        _mark_actions(ctx, errors)
        raise
    _mark_actions(ctx, errors)


def _prepare_pictures(ctx: JobContext, actions: list[AgentAction], errors: dict[str, str | None]) -> set[str]:
    """Give each approved picture its new shape or prompt, as the Review page's edits do."""

    def change(p: Project) -> set[str]:
        moments = {m.id: m for m in (p.analysis.moments if p.analysis else [])}
        ids: set[str] = set()
        for action in actions:
            moment = moments.get(action.moment_id or "")
            if moment is None:
                errors[action.id] = "the picture is gone"
                continue
            if action.display and action.display != moment.display:
                moment.display = action.display
                moment.chosen = True  # the layout setting no longer overrides this picture
                moment.note = None
            if action.prompt:
                moment.prompt = action.prompt
            if action.prompt or not action.display:
                moment.take += 1  # a new version, even when the request is the same
            moment.enabled = True
            ids.add(moment.id)
        return ids

    _, ids = ctx.update(change)
    return ids


def _apply_outfits(ctx: JobContext, actions: list[AgentAction], errors: dict[str, str | None]) -> None:
    """Give approved characters their new outfits and draw their pictures again: the portrait,
    its variants and the scenes they are in, nothing else. A character whose portrait cannot be
    drawn keeps their old outfit and pictures (no drawing is needed to put them back)."""
    project = ctx.project()
    if project.path != "novel" or project.story is None or project.novel_id is None:
        for action in actions:
            errors[action.id] = "this reel is not a novel part"
        return
    novel_id, part = project.novel_id, project.story.part
    earlier = dict(project.part_pictures or {})
    old: dict[str, str] = {}  # character id -> the outfit they wore

    def wear(p: Project) -> None:
        for action in actions:
            entry = outfit_entry(p.story, action.character or "") if p.story else None
            if entry is None or not action.outfit:
                errors[action.id] = f"{action.character} is no longer in this part's cast"
                continue
            old.setdefault(entry.id, entry.outfit)
            entry.outfit = action.outfit

    project, _ = ctx.update(wear)
    if not old:
        return
    assert project.story is not None
    only = set().union(*(outfit_redraws(project.story, cid) for cid in old))
    try:
        pictures = make_part_pictures(ctx, only=only)
    except BaseException:
        _undo_outfits(ctx, old, earlier, novel_id, part)
        raise
    failed = {cid for cid in old if not (cid in pictures and pictures[cid].key)}
    if failed:
        _undo_outfits(ctx, {cid: old[cid] for cid in failed}, earlier, novel_id, part)
        ctx.log(f"outfits: {', '.join(sorted(failed))} keep their old outfit (the portrait failed)")
    kept = {pid for pid in only if pictures.get(pid) and pictures[pid].error and pid in earlier}
    if kept - failed:  # a variant or a scene that failed: the old one is better than none

        def keep(p: Project) -> None:
            for pid in kept - failed:
                if p.part_pictures is not None:
                    p.part_pictures[pid] = earlier[pid]

        ctx.update(keep)
        ctx.log(f"outfits: {', '.join(sorted(kept - failed))} keep their old picture (drawing failed)")
    for action in actions:
        if action.id in errors or not action.character:
            continue
        picture = pictures.get(action.character)
        errors[action.id] = (
            (picture.error if picture else None) or "the portrait could not be drawn"
            if action.character in failed
            else None
        )


def _undo_outfits(
    ctx: JobContext, old: dict[str, str], earlier: dict[str, PartPicture], novel_id: str, part: int
) -> None:
    """Put characters back in their old outfits, with the pictures they had."""

    def story_back(p: Project) -> None:
        if p.story is None:
            return
        for cid, outfit in old.items():
            entry = outfit_entry(p.story, cid)
            if entry is not None:
                entry.outfit = outfit
            for pid in outfit_redraws(p.story, cid):
                if pid in earlier and p.part_pictures is not None:
                    p.part_pictures[pid] = earlier[pid]

    def bible_back(novel: Novel) -> None:
        for cid, outfit in old.items():
            character = novel.bible.characters.get(cid)
            for look in character.looks if character else []:
                if look.chapter == part:
                    look.outfit = outfit
                    if cid in earlier and earlier[cid].key:
                        look.image = earlier[cid].key

    ctx.update(story_back)
    ctx.services.db.update_novel(novel_id, bible_back)


def _mark_actions(ctx: JobContext, errors: dict[str, str | None]) -> None:
    def change(p: Project) -> None:
        for action in p.agent.latest_actions("approved"):
            if action.id in errors:
                error = errors[action.id]
                action.status, action.error = ("failed", error) if error else ("done", None)

    ctx.update(change)


HANDLERS: dict[str, Handler] = {
    "script": handle_script,
    "story": handle_story,
    "process": handle_process,
    "regenerate": handle_regenerate,
    "render": handle_render,
    "agent": handle_agent,
    "agent_apply": handle_agent_apply,
}
