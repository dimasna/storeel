"""Where things go on the 9:16 frame.

The speaker's video always fills the
frame, and pictures float over it. A card (a photo in a dark rounded frame) sits in the upper
part of the frame; a cut-out character stands at the bottom on one side; a cut-out object
floats in the upper middle. The platforms cover the top ~10% (account bar) and the bottom
~18% (caption, music, handle), and captions sit in a band in the lower or middle part, so
the pictures stay between those. Positions are fractions of the frame.
"""

from __future__ import annotations

from ..media.ffmpeg import HEIGHT, WIDTH
from ..models import Region

CAPTION_CENTER = {"lower": 0.72, "middle": 0.5}
CARD_WIDTH = 0.84  # of the width
CARD_CENTER_Y = {"lower": 0.30, "middle": 0.27}
CARD_MAX_HEIGHT = {"lower": 0.40, "middle": 0.34}
OBJECT_BOX = {"lower": (0.64, 0.34, 0.33), "middle": (0.6, 0.28, 0.28)}  # width, height, centre y
CHARACTER_HEIGHT = 0.42  # a standing cut-out, as in a novel part: its head about level with the mouth
CHARACTER_BOTTOM = 1.0  # its feet on the bottom edge
CHARACTER_MAX_WIDTH = 0.45
CHARACTER_X = (0.27, 0.73)  # left or right slot, away from the speaker's face


def expand_face(face: Region) -> Region:
    """A face box grown to cover hair, ears and chin."""
    w, h = face.width, face.height
    return Region(
        x0=max(0.0, face.x0 - 0.2 * w),
        y0=max(0.0, face.y0 - 0.5 * h),
        x1=min(1.0, face.x1 + 0.2 * w),
        y1=min(1.0, face.y1 + 0.3 * h),
    )


def covered(box: Region, faces: list[Region] | None, share: float = 0.08) -> bool | None:
    """Whether `box` covers a face (more than `share` of it); None when faces were not looked for."""
    if faces is None:
        return None
    for face in faces:
        f = expand_face(face)
        w = min(box.x1, f.x1) - max(box.x0, f.x0)
        h = min(box.y1, f.y1) - max(box.y0, f.y0)
        if w > 0 and h > 0 and w * h > share * f.width * f.height:
            return True
    return False


def card_box(caption_position: str) -> tuple[int, int, int]:
    """The card's width, maximum height and centre y, in pixels."""
    position = caption_position if caption_position in CARD_CENTER_Y else "lower"
    return (
        round(CARD_WIDTH * WIDTH),
        round(CARD_MAX_HEIGHT[position] * HEIGHT),
        round(CARD_CENTER_Y[position] * HEIGHT),
    )


def object_box(caption_position: str) -> tuple[int, int, int]:
    """A floating cut-out's maximum width and height and its centre y, in pixels."""
    w, h, y = OBJECT_BOX.get(caption_position, OBJECT_BOX["lower"])
    return round(w * WIDTH), round(h * HEIGHT), round(y * HEIGHT)


def character_x(faces: list[Region] | None) -> float:
    """The standing slot on the side away from the speaker's face (right when unknown)."""
    if not faces:
        return CHARACTER_X[1]
    face = max(faces, key=lambda f: f.width * f.height)
    return CHARACTER_X[0] if (face.x0 + face.x1) / 2 > 0.5 else CHARACTER_X[1]


def to_region(x: int, y: int, width: int, height: int) -> Region:
    """A pixel box (top-left x, y) as a Region in fractions of the frame."""
    return Region(x0=x / WIDTH, y0=y / HEIGHT, x1=(x + width) / WIDTH, y1=(y + height) / HEIGHT)
