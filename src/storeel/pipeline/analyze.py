"""The plan model (Muse Wonder by default) watches the video with its transcript and plans the
pictures.

It lists the characters, objects and places the pictures need (and which of them can be
seen in the footage, for SAM), and picks the moments where a picture helps. Each moment
quotes the words it illustrates; the quote is found in the timed transcript, so moments
start on the word instead of relying on the model to read timestamps precisely.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ..common import digest, slug
from ..jobs import JobContext, PipelineError
from ..meta import MetaAPIError
from ..meta.schema import OutputError, parse_output, text_format
from ..models import (
    DEFAULT_TITLE,
    Analysis,
    Entity,
    Moment,
    Project,
    Source,
    Transcript,
    Word,
    text_model_name,
)
from ..prompts import load_prompt

VERSION = 2  # 2: pictures are cards or cut-outs (with a subject for SAM)
SECONDS_PER_MOMENT = {"few": 12.0, "balanced": 7.0, "many": 4.5}
MIN_LENGTH = {"cutaway": 1.5, "overlay": 2.0, "cutout": 2.0}
MAX_LENGTH = {"cutaway": 6.0, "overlay": 8.0, "cutout": 8.0}
HOOK = 1.0  # keep the first second (the platforms' cover frame) on the speaker
GAP = 0.3

INSTRUCTIONS = load_prompt("analysis")


# The schema sent with the request marks every field required (see strict_json_schema), but
# the model can still leave fields out, so the defaults here say what to assume instead.
class EntityOut(BaseModel):
    id: str = Field("", description="lowercase snake_case id")
    kind: Literal["character", "object", "place"] = "object"
    name: str = Field("", description="what the speaker calls it, e.g. 'Milo', 'my mum', 'the café'")
    description: str = Field("", description="English: how it looks, concretely, for an image model")
    real_world: bool = Field(
        False, description="true only for a real, recognisable landmark, brand or product"
    )
    visible_in_video: bool = Field(False, description="true when it is clearly visible in the footage")
    segment_prompt: str = Field(
        "", description="when a visible character or object: a short noun phrase, else ''"
    )
    visible_at: float = Field(-1, description="when visible: seconds where it is clearly visible; else -1")


class MomentOut(BaseModel):
    quote: str = Field("", description="3-15 consecutive words copied exactly from one transcript turn")
    display: Literal["overlay", "cutout", "cutaway"] = "overlay"
    subject: str = Field(
        "", description="a short English noun phrase naming the main thing the picture shows"
    )
    entities: list[str] = Field(default_factory=list, description="ids of the entities the picture shows")
    prompt: str = Field("", description="English: the one picture to show, for an image model")


class AnalysisOut(BaseModel):
    title: str = Field("", description="a short title for the reel, in the speaker's language")
    summary: str = Field("", description="one sentence: what the video is about")
    language: str = Field("", description="the main spoken language as an ISO 639-1 code, e.g. 'id' or 'en'")
    entities: list[EntityOut] = Field(default_factory=list)
    moments: list[MomentOut] = Field(default_factory=list)


def target_moments(duration: float, visuals: str) -> int:
    if visuals == "off" or duration < 3:
        return 0
    return max(1, min(20, round(duration / SECONDS_PER_MOMENT[visuals])))


def _token(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in text if ch.isalnum())


def find_quote(words: list[Word], quote: str) -> tuple[int, int] | None:
    """The first and last index of `quote` in `words`: exact match first, then a close one."""
    wanted = [t for t in (_token(x) for x in quote.split()) if t]
    tokens = [_token(w.text) for w in words]
    n = len(wanted)
    if n == 0 or n > len(tokens):
        return None
    for i in range(len(tokens) - n + 1):
        if tokens[i : i + n] == wanted:
            return i, i + n - 1
    target = " ".join(wanted)
    best, best_ratio = None, 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(len(tokens) - size + 1):
            ratio = difflib.SequenceMatcher(None, " ".join(tokens[i : i + size]), target).ratio()
            if ratio > best_ratio:
                best, best_ratio = (i, i + size - 1), ratio
    return best if best_ratio >= 0.8 else None


def _plan_block(project: Project, source: Source) -> str:
    """Path B: the script the speaker recorded, scene by scene, placed on the timeline."""
    script = project.script
    if script is None:
        return ""
    where = {seg.scene_id: seg for seg in source.segments if seg.scene_id}
    lines = [
        "THE SCRIPT THE SPEAKER RECORDED, scene by scene, with each scene's place on the timeline and the "
        "picture planned for it. Follow the plan: place each planned picture on the words of its scene "
        "that it illustrates and keep its display, unless the recording makes it wrong.",
    ]
    for scene in script.scenes:
        seg = where.get(scene.id)
        span = f"{seg.start:.1f}-{seg.end:.1f}s" if seg else "?"
        planned = (
            f'{scene.display}: "{scene.visual}" (entities: {", ".join(scene.entities) or "none"})'
            if scene.display != "none"
            else "none, stay on the speaker"
        )
        lines.append(
            f'- {scene.id} ({span}, {scene.purpose}): says "{scene.lines}". Planned picture: {planned}'
        )
    if script.entities:
        lines.append("ENTITIES PLANNED (reuse these ids and descriptions):")
        lines += [f"- {e.id} ({e.kind}) {e.name}: {e.description}" for e in script.entities]
    return "\n".join(lines)


def _prompt(project: Project, transcript: Transcript, source: Source, count: int) -> str:
    turns = [f"[{t.id}] {t.start:.1f}-{t.end:.1f}s: {t.text}" for t in transcript.turns]
    parts = [
        f"VIDEO DURATION: {source.duration:.1f} seconds",
        "TRANSCRIPT (turn id, start-end, text):",
        *(turns or ["(no speech recognised)"]),
        "",
        f"Aim for about {count} moments.",
    ]
    plan = _plan_block(project, source)
    if plan:
        parts += ["", plan]
    parts += ["", "Plan the pictures."]
    return "\n".join(parts)


def normalize(
    out: AnalysisOut, transcript: Transcript, duration: float, count: int, allow_full: bool = False
) -> Analysis:
    """Keep only what can be used: unique ids, known references, moments placed on the words.
    Full-screen pictures are kept only when the script plan asked for them (`allow_full`);
    otherwise a planned cutaway becomes a card, since pictures float over the speaker."""
    entities: list[Entity] = []
    for item in out.entities:
        entity_id = slug(item.id or item.name, "entity")
        if not item.name.strip() or any(e.id == entity_id for e in entities):
            continue
        visible = item.visible_in_video and 0 <= item.visible_at <= duration
        prompt = " ".join(item.segment_prompt.split())[:60] if visible and item.kind != "place" else ""
        entities.append(
            Entity(
                id=entity_id,
                kind=item.kind,
                name=item.name.strip()[:80],
                description=" ".join(item.description.split())[:800],
                real_world=item.real_world,
                visible_in_video=visible and (item.kind == "place" or bool(prompt)),
                segment_prompt=prompt,
                visible_at=round(item.visible_at, 2) if visible else None,
            )
        )
    known = {e.id for e in entities}
    words = [w for turn in transcript.turns for w in turn.words]
    placed: list[Moment] = []
    for item in out.moments:
        span = find_quote(words, item.quote)
        prompt = " ".join(item.prompt.split())
        if span is None or not prompt:
            continue
        display = item.display if item.display != "cutaway" or allow_full else "overlay"
        first, last = words[span[0]], words[span[1]]
        start = max(HOOK, first.start - 0.1)
        end = max(last.end + 0.25, start + MIN_LENGTH[display])
        end = min(end, start + MAX_LENGTH[display], duration)
        if end - start < MIN_LENGTH[display] * 0.8:
            continue
        placed.append(
            Moment(
                id="",
                start=round(start, 3),
                end=round(end, 3),
                quote=" ".join(w.text for w in words[span[0] : span[1] + 1]),
                display=display,
                planned=display,
                subject=" ".join(item.subject.split())[:60],
                entities=[e for e in dict.fromkeys(slug(x) for x in item.entities) if e in known][:4],
                prompt=prompt[:1200],
            )
        )
    placed.sort(key=lambda m: m.start)
    moments: list[Moment] = []
    for moment in placed:
        if moments and moment.start < moments[-1].end + GAP:
            moment.start = round(moments[-1].end + GAP, 3)
        if moment.end - moment.start >= MIN_LENGTH[moment.display] * 0.8:
            moments.append(moment)
    cap = max(count + 2, round(count * 1.4))
    if len(moments) > cap:  # keep an even spread
        step = (len(moments) - 1) / (cap - 1)
        moments = [moments[round(i * step)] for i in range(cap)]
    for index, moment in enumerate(moments, 1):
        moment.id = f"m{index:02d}"
    language = re.sub(r"[^a-z]", "", out.language.lower())[:3] or "und"
    return Analysis(
        title=" ".join(out.title.split())[:120],
        summary=" ".join(out.summary.split())[:500],
        language=language,
        entities=entities,
        moments=moments,
    )


def analyze(ctx: JobContext, source: Source, transcript: Transcript) -> Analysis:
    project = ctx.project()
    count = target_moments(source.duration, project.style.visuals)
    plan = project.script.model_dump(exclude={"scenes": {"__all__": {"take"}}}) if project.script else None
    key = digest(
        VERSION,
        ctx.settings.plan_model,
        ctx.settings.plan_effort,
        source.digest,
        [(t.start, t.end, t.original) for t in transcript.turns],
        count,
        plan,
    )
    if project.analysis is not None and project.analysis.digest == key:
        ctx.log("analysis: unchanged, reusing it")
        return project.analysis
    if count == 0:
        title = project.title
        analysis = Analysis(title=title, summary="", language="und", entities=[], moments=[], digest=key)
        ctx.log("pictures are off: no analysis needed")
        ctx.update(lambda p: setattr(p, "analysis", analysis))
        return analysis

    client = ctx.client
    model = ctx.settings.plan_model
    name = text_model_name(model)
    proxy = ctx.files.path(source.proxy_key)
    file_id = client.upload_file(proxy, "video/mp4", expires_seconds=3600, cancel=ctx.cancelled)
    try:
        ctx.log(
            f"{name}: watching {source.duration:.1f}s of video with {len(transcript.turns)} turn(s)"
            f" (effort {ctx.settings.plan_effort})"
        )
        result = client.responses(
            {
                "model": model,
                "store": False,
                "instructions": INSTRUCTIONS,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": _prompt(project, transcript, source, count)},
                            {"type": "input_video", "file_id": file_id},
                        ],
                    }
                ],
                "reasoning": {"effort": ctx.settings.plan_effort},
                "max_output_tokens": ctx.settings.max_output_tokens,
                "text": text_format("reel_pictures", AnalysisOut),
            },
            cancel=ctx.cancelled,
        )
    except MetaAPIError as exc:
        if not exc.output_limit:
            raise
        ctx.spend_text(model, exc.usage)
        raise PipelineError(
            f"{name}'s picture plan ran past {ctx.settings.max_output_tokens} output tokens and was"
            " stopped; try again (or raise STOREEL_MAX_OUTPUT_TOKENS for a long video)"
        ) from exc
    finally:
        client.delete_file(file_id)  # the video is personal: do not leave it stored
    ctx.spend_text(model, result.usage)
    ctx.log(
        f"analysis took {result.seconds:.0f}s: {result.input_tokens} input tokens"
        f" ({result.cached_tokens} cached), {result.output_tokens} output"
        f" ({result.reasoning_tokens} reasoning)"
    )
    try:
        out, missing = parse_output(AnalysisOut, result.text)
    except (OutputError, ValidationError) as exc:
        raise PipelineError(
            f"{name}'s picture plan could not be read ({exc.__class__.__name__}); try again"
        ) from exc
    if missing:
        ctx.log(f"{name} left out: {', '.join(missing)} (filled in)")
    allow_full = project.script is not None and any(s.display == "cutaway" for s in project.script.scenes)
    analysis = normalize(out, transcript, source.duration, count, allow_full)
    analysis.digest = key
    dropped = len(out.moments) - len(analysis.moments)
    ctx.log(
        f"analysis: {len(analysis.entities)} entities, {len(analysis.moments)} moments"
        + (f" ({dropped} dropped: quote not found, overlapping or too short)" if dropped > 0 else "")
    )
    if not analysis.moments and transcript.turns:
        ctx.log("no usable moments: the reel will have captions only")

    def save(p: Project) -> None:
        p.analysis = analysis
        if p.path == "video" and analysis.title and p.title in ("", DEFAULT_TITLE):
            p.title = analysis.title

    ctx.update(save)
    return analysis
