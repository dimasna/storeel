"""What the user said, next to the script they recorded (novel parts and ideas).

For the page: how much of each take's lines can be heard in the recording (a take read from
another version of the script, or not read at all, is flagged before the reel is rendered), and
where each caption turn differs from the script, for the user to review.
"""

from __future__ import annotations

from ..models import Project
from .align import CaptionNote, caption_notes, line_shares, said_share, tokens

NOT_HEARD = 0.3  # a take with less of its lines heard was read from something else
PARTLY = 0.6


def heard_shares(project: Project) -> dict[str, float]:
    """For each recorded take (scene id), the share of its lines heard in its recording."""
    script, source, transcript = project.script, project.source, project.transcript
    if script is None or source is None or transcript is None or project.path not in ("idea", "novel"):
        return {}
    words = [w for turn in transcript.turns for w in turn.words]
    segments = {seg.scene_id: seg for seg in source.segments if seg.scene_id}
    if not segments:  # one video of the whole part: the lines are lined up with all of it
        shares = line_shares([s.lines for s in script.scenes], [w.text for w in words])
        return {s.id: round(x, 2) for s, x in zip(script.scenes, shares, strict=True)}
    out: dict[str, float] = {}
    for scene in script.scenes:
        seg = segments.get(scene.id)
        if seg is None:
            continue
        heard = [t for w in words if seg.start - 0.05 <= w.start < seg.end for t in tokens(w.text)]
        out[scene.id] = round(said_share(tokens(scene.lines), heard), 2)
    return out


def heard_report(project: Project) -> dict[str, dict[str, float | str]]:
    """For the page: each recorded take's share heard and what it means ("ok", "partly", "not heard")."""
    out: dict[str, dict[str, float | str]] = {}
    for scene_id, share in heard_shares(project).items():
        status = "not heard" if share < NOT_HEARD else "partly" if share < PARTLY else "ok"
        out[scene_id] = {"share": share, "status": status}
    return out


def caption_review(project: Project) -> dict[int, CaptionNote]:
    """For each caption turn that differs from the script: how, and the script's wording."""
    script, transcript = project.script, project.transcript
    if script is None or transcript is None or project.path not in ("idea", "novel"):
        return {}
    turns = transcript.turns
    notes = caption_notes([s.lines for s in script.scenes], [t.text.split() for t in turns])
    return {turn.id: note for turn, note in zip(turns, notes, strict=True) if note is not None}
