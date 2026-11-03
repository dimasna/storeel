"""Decode SAM 3.1's video masks in a process of its own, so several decode at once.

Meta's mask decoder is pure Python (about a second for a person-sized mask), so the masks of a
few seconds of video are shared out over a few of these processes by depth.py, or, on the
server, over many machines at once (`decode_packed`, see modal_app.py):

    python -m storeel.pipeline.maskdecode LINES.txt OUT.npz WIDTH HEIGHT

LINES.txt holds SAM's answer lines (one frame each); OUT.npz gets the frame numbers and, per
frame, the union of every person found, as packed bits.
"""

from __future__ import annotations

import sys
import zlib

import numpy as np

from ..meta.sam import FRAME, parse_detections

CONFIDENCE = 0.4


def decode(lines: list[str], width: int, height: int) -> tuple[list[int], list[np.ndarray]]:
    frames: list[int] = []
    masks: list[np.ndarray] = []
    for line in lines:
        header = FRAME.match(line.strip())
        if header is None:
            continue
        frame = int(header.group(1))
        union = np.zeros((height, width), dtype=bool)
        for detection in parse_detections(line, frame=frame):
            if detection.confidence >= CONFIDENCE:
                union |= detection.full_mask(width, height)
        frames.append(frame)
        masks.append(np.packbits(union))
    return frames, masks


def decode_packed(lines: list[str], width: int, height: int) -> tuple[list[int], bytes]:
    """`decode`, its masks stacked and compressed: what a decoding machine sends back."""
    frames, masks = decode(lines, width, height)
    stacked = np.stack(masks) if masks else np.zeros((0, (width * height + 7) // 8), dtype=np.uint8)
    return frames, zlib.compress(stacked.tobytes(), 3)


def unpack(frames: list[int], data: bytes, width: int, height: int) -> dict[int, np.ndarray]:
    row = (width * height + 7) // 8
    stacked = np.frombuffer(zlib.decompress(data), dtype=np.uint8).reshape(len(frames), row)
    return {frame: stacked[k] for k, frame in enumerate(frames)}


def main(argv: list[str]) -> int:
    source, target, width, height = argv[0], argv[1], int(argv[2]), int(argv[3])
    with open(source, encoding="utf-8") as handle:
        lines = [line for line in handle.read().splitlines() if line.strip()]
    frames, masks = decode(lines, width, height)
    packed = np.stack(masks) if masks else np.zeros((0, (width * height + 7) // 8), dtype=np.uint8)
    with open(target, "wb") as handle:
        np.savez(handle, frames=np.array(frames, dtype=np.int32), masks=packed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
