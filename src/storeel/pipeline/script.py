"""Path B: Muse Spark writes a scene-by-scene script from the user's idea."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..common import slug
from ..jobs import JobContext, PipelineError
from ..meta.schema import text_format
from ..models import DEFAULT_TITLE, Idea, Project, Scene, Script, ScriptEntity
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


class SceneOut(BaseModel):
    purpose: Literal["hook", "context", "story", "point", "payoff", "cta"] = Field(
        description="the job this scene does"
    )
    lines: str = Field(
        description="exactly what the speaker says, in the script's language; at most 30 words"
    )
    direction: str = Field(
        description="a short delivery note (emotion, gesture, pace), in the script's language"
    )
    display: Literal["none", "cutaway", "overlay"] = Field(
        description="how a picture is shown during the scene"
    )
    visual: str = Field(description="English: the one picture to show, or empty when display is none")
    entities: list[str] = Field(description="ids of the entities in the picture")


class EntityOut(BaseModel):
    id: str = Field(description="lowercase snake_case id")
    kind: Literal["character", "object", "place"]
    name: str = Field(description="what the speaker calls it")
    description: str = Field(
        description="English: how it looks, concretely (age, build, hair, clothes; material, colour; "
        "architecture, light)"
    )
    real_world: bool = Field(description="true only for a real, recognisable landmark, brand or product")


class ScriptOut(BaseModel):
    title: str = Field(description="a short title for the video, in the script's language")
    scenes: list[SceneOut]
    entities: list[EntityOut]


def _prompt(idea: Idea) -> str:
    words = round(idea.length * WORDS_PER_SECOND[idea.language])
    scenes = min(12, max(3, round(idea.length / 7)))
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


def clean_script(out: ScriptOut, language: Literal["id", "en"]) -> Script:
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
        raise PipelineError("Muse Spark returned a script without scenes; try again")
    return Script(
        title=out.title.strip()[:120] or DEFAULT_TITLE,
        language=language,
        scenes=scenes[:20],
        entities=entities,
    )


def write_script(ctx: JobContext) -> Script:
    project = ctx.project()
    if project.idea is None:
        raise PipelineError("describe the idea first")
    idea = project.idea
    ctx.log(f"Muse Spark: writing a {idea.length}s {idea.format} script ({idea.language})")
    result = ctx.client.responses(
        {
            "model": ctx.settings.spark_model,
            "store": False,
            "instructions": INSTRUCTIONS,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": _prompt(idea)}],
                }
            ],
            "reasoning": {"effort": ctx.settings.spark_effort},
            "text": text_format("reel_script", ScriptOut),
        },
        cancel=ctx.cancelled,
    )
    ctx.spend(
        spark_input_tokens=result.input_tokens,
        spark_cached_tokens=result.cached_tokens,
        spark_output_tokens=result.output_tokens,
    )
    ctx.log(
        f"script written in {result.seconds:.0f}s"
        f" ({result.input_tokens} in, {result.output_tokens} out tokens)"
    )
    try:
        out = ScriptOut.model_validate_json(result.text)
    except ValueError as exc:
        raise PipelineError(f"Muse Spark returned a script that does not parse: {exc}") from exc
    script = clean_script(out, idea.language)
    words = sum(len(s.lines.split()) for s in script.scenes)
    ctx.log(f"script: {len(script.scenes)} scenes, {words} words, {len(script.entities)} entities")

    def save(p: Project) -> None:
        p.script = script
        if p.title in ("", DEFAULT_TITLE):
            p.title = script.title
        p.invalidate_media()

    ctx.update(save)
    return script
