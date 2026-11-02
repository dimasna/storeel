"""What a novel part costs at Meta's list prices, before anything runs.

The figures come from real parts. A 6,574-character chapter made 12 beats, 10 pictures (7 cut
out by SAM, 5 portraits checked) and about 100 seconds of narration; a 2,489-character one
made 10 beats and about 120 seconds. Their text-model calls (writing, the storyboard check,
one fix, the portrait checks) cost $0.14-0.20. Rendering runs on the server and costs nothing.
These are estimates: the writer's thinking varies.
"""

from __future__ import annotations

from .models import PRICE_ASR_SECOND, PRICE_IMAGE, PRICE_SAM_IMAGE
from .pipeline.story import MAX_SECONDS

TEXT_BASE_USD = 0.13  # the prompts, the storyboard check, a fix round and the portrait checks
TEXT_PER_CHAR_USD = 0.00001  # the chapter is read by each of those calls
CUT_OUT_SHARE = 0.7  # most pictures are cut out of their background by SAM


def part_pictures(chapter_chars: int) -> int:
    """How many pictures a part of this chapter usually shows (2.5k characters: 8 or 9)."""
    return max(6, min(14, round(7 + chapter_chars / 1500)))


def part_seconds(chapter_chars: int) -> int:
    """How long the part is read aloud: the writer tells even a short chapter in 1.5-2 minutes."""
    return min(MAX_SECONDS, round(90 + chapter_chars / 200))


def estimate_part(chapter_chars: int) -> dict[str, float | int]:
    """The cost of a part's first pass: writing, transcribing, drawing (rendering is free)."""
    chars = max(0, chapter_chars)
    pictures = part_pictures(chars)
    seconds = part_seconds(chars)
    write = TEXT_BASE_USD + chars * TEXT_PER_CHAR_USD
    draw = pictures * (PRICE_IMAGE + CUT_OUT_SHARE * PRICE_SAM_IMAGE)
    transcribe = seconds * PRICE_ASR_SECOND
    return {
        "write_usd": round(write, 3),
        "draw_usd": round(draw, 3),
        "transcribe_usd": round(transcribe, 4),
        "total_usd": round(write + draw + transcribe, 2),
        "pictures": pictures,
        "seconds": seconds,
    }
