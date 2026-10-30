"""Muse Spark looks at each new character portrait of a novel part before it is used.

Every later part redraws a character from their first portrait (the face is kept from it), so a
wrong one would carry forward: two people, cut-off feet, another outfit, writing, a different
face. The check sees the portrait as it will be used (the cut-out on grey) with the words it was
drawn from, and the earlier portrait for a redraw; a wrong one is drawn again with the check's
fix added to the prompt.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from ..jobs import JobContext
from ..meta import MetaAPIError
from ..meta.schema import OutputError, parse_output, text_format
from ..prompts import load_prompt

RETAKES = 1  # redraws after a failed check: each one is a picture, a cut-out and a check
MAX_SIDE = 768  # the checker sees a smaller copy: enough to judge, fewer image tokens
MAX_OUTPUT = 6000  # a look, not long thinking


class PortraitVerdict(BaseModel):
    people: int = Field(1, description="distinct people or figures visible")
    whole_body: bool = Field(True, description="the whole figure is visible, head to feet")
    matches: bool = Field(True, description="the figure fits the words it was drawn from")
    same_person: bool = Field(True, description="the same person as the reference (true without one)")
    writing: bool = Field(False, description="letters, words, numbers or signs are visible")
    problems: list[str] = Field(default_factory=list, description="major problems; empty if none")
    fix: str = Field("", description="sentences to add to the drawing prompt; empty if none")


@dataclass
class Check:
    ok: bool
    problems: list[str]
    fix: str
    score: float  # lower is better: picks the best of several takes


def enabled(ctx: JobContext) -> bool:
    return ctx.settings.picture_check_effort != "off"


def _image_part(png: bytes) -> dict:
    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("RGBA")
    plate = Image.new("RGBA", image.size, (128, 128, 128, 255))  # a cut-out on neutral grey
    plate.alpha_composite(image)
    rgb = plate.convert("RGB")
    rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=85)
    return {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
    }


def check_portrait(
    ctx: JobContext, png: bytes, drawn_from: str, references: list[dict], name: str
) -> Check | None:
    """The checker's verdict on one portrait, or None when the check could not be made (the
    portrait is then used as it is: a check never stops a part)."""
    model = ctx.settings.check_model
    content: list[dict] = [
        {"type": "input_text", "text": f"DRAWN FROM: {drawn_from}"},
        {"type": "input_text", "text": "PORTRAIT:"},
        _image_part(png),
    ]
    for reference in references[:1]:
        content += [{"type": "input_text", "text": f"REFERENCE: the earlier portrait of {name}."}, reference]
    try:
        result = ctx.client.responses(
            {
                "model": model,
                "store": False,
                "instructions": load_prompt("portrait_check"),
                "input": [{"type": "message", "role": "user", "content": content}],
                "reasoning": {"effort": ctx.settings.picture_check_effort},
                "max_output_tokens": MAX_OUTPUT,
                "text": text_format("portrait_check", PortraitVerdict),
            },
            cancel=ctx.cancelled,
        )
    except MetaAPIError as exc:
        if exc.usage:
            ctx.spend_text(model, exc.usage)
        ctx.log(f"portrait check of {name} skipped: {exc}")
        return None
    ctx.spend_text(model, result.usage)
    try:
        verdict, _ = parse_output(PortraitVerdict, result.text)
    except (OutputError, ValidationError) as exc:
        ctx.log(f"portrait check of {name} skipped: the answer could not be read ({exc.__class__.__name__})")
        return None
    problems = [" ".join(p.split()) for p in verdict.problems if p.strip()]
    flags = {
        f"{verdict.people} figures instead of one": verdict.people != 1,
        "not the whole body": not verdict.whole_body,
        "does not match the description": not verdict.matches,
        "not the same person as before": not verdict.same_person,
        "writing in the picture": verdict.writing,
    }
    for label, raised in flags.items():
        if raised and not problems:
            problems.append(label)
    raised = sum(flags.values())
    return Check(
        ok=not raised and not problems,
        problems=problems[:6],
        fix=" ".join(verdict.fix.split())[:400],
        score=3 * raised + len(problems),
    )


def retake_text(text: str, check: Check) -> str:
    """The drawing prompt for another attempt: the checker's fix, else what to avoid."""
    fix = check.fix or ("Avoid: " + "; ".join(check.problems) + ".")
    return f"{text} {fix}"
