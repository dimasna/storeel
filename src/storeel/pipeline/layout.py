"""Where things go on the 9:16 frame.

The platforms cover the top ~10% (account bar) and the bottom ~18% (caption, music, handle)
of a reel, and their buttons sit on the right edge. Captions live in a band in the lower or
middle part. Picture cards go in the largest area that is clear of all of that and of the
speaker's face, so the face is never covered.
"""

from __future__ import annotations

from ..media.ffmpeg import HEIGHT, WIDTH
from ..models import Region

SAFE_TOP, SAFE_BOTTOM = 0.10, 0.80
SAFE_LEFT, SAFE_RIGHT = 0.06, 0.94
MARGIN = 0.015
MIN_WIDTH, MIN_HEIGHT = 0.36, 0.13
MAX_HEIGHT = 0.36
CAPTION_CENTER = {"lower": 0.72, "middle": 0.5}
CAPTION_HALF_BAND = 0.065


def caption_band(position: str) -> tuple[float, float]:
    center = CAPTION_CENTER.get(position, CAPTION_CENTER["lower"])
    return center - CAPTION_HALF_BAND, center + CAPTION_HALF_BAND


def _subtract(span: tuple[float, float], blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """`span` minus every block (each widened by MARGIN)."""
    pieces = [span]
    for b0, b1 in blocks:
        b0, b1 = b0 - MARGIN, b1 + MARGIN
        pieces = [
            part
            for a0, a1 in pieces
            for part in ((a0, min(a1, b0)), (max(a0, b1), a1))
            if part[1] - part[0] > 1e-6
        ]
    return pieces


def expand_face(face: Region) -> Region:
    """A face box grown to cover hair, ears and chin."""
    w, h = face.width, face.height
    return Region(
        x0=max(0.0, face.x0 - 0.2 * w),
        y0=max(0.0, face.y0 - 0.5 * h),
        x1=min(1.0, face.x1 + 0.2 * w),
        y1=min(1.0, face.y1 + 0.3 * h),
    )


def _overlaps(a: Region, b: Region) -> bool:
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def _capped(region: Region) -> Region:
    if region.height <= MAX_HEIGHT:
        return region
    middle = (region.y0 + region.y1) / 2
    return Region(x0=region.x0, y0=middle - MAX_HEIGHT / 2, x1=region.x1, y1=middle + MAX_HEIGHT / 2)


def card_region(faces: list[Region] | None, caption_position: str, captions_on: bool = True) -> Region | None:
    """The best place for a picture card, or None when there is no room beside the face."""
    blocked = [caption_band(caption_position)] if captions_on else []
    obstacles = [expand_face(face) for face in faces or []]
    candidates = [
        Region(x0=SAFE_LEFT, y0=y0, x1=SAFE_RIGHT, y1=y1)
        for y0, y1 in _subtract((SAFE_TOP, SAFE_BOTTOM), blocked + [(o.y0, o.y1) for o in obstacles])
    ]
    for o in obstacles:  # columns beside a face
        for y0, y1 in _subtract((max(SAFE_TOP, o.y0), min(SAFE_BOTTOM, o.y1)), blocked):
            candidates.append(Region(x0=SAFE_LEFT, y0=y0, x1=o.x0 - MARGIN, y1=y1))
            candidates.append(Region(x0=o.x1 + MARGIN, y0=y0, x1=SAFE_RIGHT, y1=y1))
    usable = [
        _capped(r)
        for r in candidates
        if r.width >= MIN_WIDTH and r.height >= MIN_HEIGHT and not any(_overlaps(r, o) for o in obstacles)
    ]
    if not usable:
        return None
    return max(usable, key=lambda r: r.width * WIDTH * r.height * HEIGHT)
