"""Path B: the script model (Muse Spark by default) writes a scene-by-scene script from the idea."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ..common import slug
from ..jobs import JobContext, PipelineError
from ..meta import MetaAPIError
from ..meta.schema import OutputError, parse_output, text_format
from ..models import DEFAULT_TITLE, MAX_SCENES, Idea, Project, Scene, Script, ScriptEntity, text_model_name
from ..prompts import load_prompt

WORDS_PER_SECOND = {"id": 2.2, "en": 2.4}  # read from a teleprompter, a little slower than chat

FORMATS = {
    "storytime": "a story told in order: the setup, the moment it went wrong or got interesting, "
    "the turn, the outcome",
    "explainer": "one idea explained step by step, with one concrete example",
    "tips": "three to five concrete, actionable tips, one per scene",
    "review": "what it is, what is good, what is not, the verdict",
    "opinion": "the take, the reasons with one example, the strongest counterpoint, the conclusion",
}
VOICES = {
    "id": "Write every spoken line in natural, casual Indonesian, the way people talk on Reels: "
    "everyday words (aku, kamu, banget, nggak, udah, gimana), short sentences, an English word "
    "where Indonesians naturally use one. Never formal written Indonesian.",
    "en": "Write every spoken line in natural, conversational English.",
}

INSTRUCTIONS = load_prompt("script")


# The schema sent with the request marks every field required (see strict_json_schema), but
# the model can still leave fields out, so the defaults here say what to assume instead.
class SceneOut(BaseModel):
    purpose: Literal["hook", "context", "story", "point", "payoff", "cta"] = Field(
        "story", description="the job this scene does"
    )
    lines: str = Field(
        "", description="exactly what the speaker says, in the script's language; at most 30 words"
    )
    direction: str = Field(
        "", description="a short delivery note (emotion, gesture, pace), in the script's language"
    )
    # The prompt offers overlay and cutout; "cutaway" (full screen) is still read, so an
    # answer that uses it is not thrown away.
    display: Literal["none", "overlay", "cutout", "cutaway"] = Field(
        "none", description="how a picture is shown during the scene"
    )
    visual: str = Field("", description="English: the one picture to show, or empty when display is none")
    entities: list[str] = Field(default_factory=list, description="ids of the entities in the picture")


class EntityOut(BaseModel):
    id: str = Field("", description="lowercase snake_case id")
    kind: Literal["character", "object", "place"] = "object"
    name: str = Field("", description="what the speaker calls it")
    description: str = Field(
        "",
        description="English: how it looks, concretely (age, build, hair, clothes; material, colour; "
        "architecture, light)",
    )
    real_world: bool = Field(
        False, description="true only for a real, recognisable landmark, brand or product"
    )


class ScriptOut(BaseModel):
    title: str = Field("", description="a short title for the video, in the script's language")
    scenes: list[SceneOut] = Field(default_factory=list)
    entities: list[EntityOut] = Field(default_factory=list)


def idea_title(idea: Idea) -> str:
    """A title from the idea itself, for when the script comes back without one."""
    words = idea.text.split()
    title = " ".join(words[:7]) + ("…" if len(words) > 7 else "")
    return (title[:1].upper() + title[1:])[:120] or DEFAULT_TITLE


def _prompt(idea: Idea) -> str:
    words = round(idea.length * WORDS_PER_SECOND[idea.language])
    scenes = min(MAX_SCENES, max(3, round(idea.length / 7)))
    return "\n".join(
        [
            "IDEA:",
            "<<<",
            idea.text.strip(),
            ">>>",
            f"FORMAT: {idea.format}: {FORMATS[idea.format]}",
            f"TONE: {idea.tone}",
            f"LANGUAGE: {'Indonesian' if idea.language == 'id' else 'English'}. {VOICES[idea.language]}",
            f"LENGTH: about {idea.length} seconds: about {words} spoken words in {scenes} scenes.",
            "Write the script.",
        ]
    )


def clean_script(
    out: ScriptOut, language: Literal["id", "en"], fallback_title: str = DEFAULT_TITLE
) -> Script:
    """Unique ids, known entity references, and a picture only where one is described."""
    entities: list[ScriptEntity] = []
    seen: set[str] = set()
    for entity in out.entities:
        entity_id = slug(entity.id or entity.name, "entity")
        if entity_id in seen or not entity.name.strip():
            continue
        seen.add(entity_id)
        entities.append(
            ScriptEntity(
                id=entity_id,
                kind=entity.kind,
                name=entity.name.strip()[:80],
                description=" ".join(entity.description.split())[:800],
                real_world=entity.real_world,
            )
        )
    scenes: list[Scene] = []
    for scene in out.scenes:
        lines = " ".join(scene.lines.split())
        if not lines:
            continue
        visual = " ".join(scene.visual.split())
        display = scene.display if visual else "none"
        scenes.append(
            Scene(
                id=f"s{len(scenes) + 1}",
                purpose=scene.purpose,
                lines=lines[:600],
                direction=" ".join(scene.direction.split())[:300],
                display=display,
                visual=visual[:800] if display != "none" else "",
                entities=[slug(e) for e in scene.entities if slug(e) in seen][:8],
            )
        )
    if not scenes:
        raise ScriptUnusable("the script has no scenes with lines")
    return Script(
        title=" ".join(out.title.split())[:120] or fallback_title,
        language=language,
        scenes=scenes[:MAX_SCENES],
        entities=entities,
    )


class ScriptUnusable(ValueError):
    """The script model answered, but not with a script that can be recorded."""


def _ask(ctx: JobContext, idea: Idea, note: str | None) -> ScriptOut:
    prompt = _prompt(idea) + (f"\n\n{note}" if note else "")
    model = ctx.settings.script_model
    try:
        result = ctx.client.responses(
            {
                "model": model,
                "store": False,
                "instructions": INSTRUCTIONS,
                "input": [
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}
                ],
                "reasoning": {"effort": ctx.settings.script_effort},
                "max_output_tokens": ctx.settings.max_output_tokens,
                "text": text_format("reel_script", ScriptOut),
            },
            cancel=ctx.cancelled,
        )
    except MetaAPIError as exc:
        if not exc.output_limit:
            raise
        ctx.spend_text(model, exc.usage)
        raise ScriptUnusable(
            f"the answer ran past {ctx.settings.max_output_tokens} output tokens and was stopped"
        ) from exc
    ctx.spend_text(model, result.usage)
    ctx.log(
        f"script written in {result.seconds:.0f}s"
        f" ({result.input_tokens} in, {result.output_tokens} out tokens)"
    )
    try:
        out, missing = parse_output(ScriptOut, result.text)
    except (OutputError, ValidationError) as exc:
        raise ScriptUnusable(f"the answer could not be read ({exc.__class__.__name__})") from exc
    if missing:
        ctx.log(f"{text_model_name(model)} left out: {', '.join(missing)} (filled in)")
    return out


def write_script(ctx: JobContext) -> Script:
    project = ctx.project()
    if project.idea is None:
        raise PipelineError("describe the idea first")
    idea = project.idea
    name = text_model_name(ctx.settings.script_model)
    ctx.log(
        f"{name}: writing a {idea.length}s {idea.format} script ({idea.language},"
        f" effort {ctx.settings.script_effort})"
    )
    try:
        script = clean_script(_ask(ctx, idea, None), idea.language, idea_title(idea))
    except ScriptUnusable as exc:
        ctx.log(f"{exc}; asking once more")
        note = "Your previous answer could not be used. Answer with title, scenes and entities."
        try:
            script = clean_script(_ask(ctx, idea, note), idea.language, idea_title(idea))
        except ScriptUnusable as again:
            raise PipelineError(f"{name} did not return a usable script ({again}); try again") from again
    words = sum(len(s.lines.split()) for s in script.scenes)
    ctx.log(f"script: {len(script.scenes)} scenes, {words} words, {len(script.entities)} entities")

    def save(p: Project) -> None:
        p.script = script
        if p.title in ("", DEFAULT_TITLE):
            p.title = script.title
        p.invalidate_media()

    ctx.update(save)
    return script
