"""SAM 3.1 image segmentation over the Responses API.

SAM answers a short noun phrase ("orange cat", "face") with a box and a mask for every
match, as special-token text. `meta_sam_parser` (Meta's parser for that wire format) turns
the text into records; each mask is box-local, so it is placed back at the box's position.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
)
from PIL import Image

from ..common import CancelCheck
from .client import MetaClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    """One match: a half-open box in source pixels and its box-local boolean mask."""

    object_id: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float
    mask: np.ndarray

    @property
    def area(self) -> int:
        return int(self.mask.sum())

    @property
    def score(self) -> float:
        return self.confidence * self.area

    def full_mask(self, width: int, height: int) -> np.ndarray:
        """The mask on a `height` x `width` canvas (the source image)."""
        canvas = np.zeros((height, width), dtype=bool)
        x0, y0 = max(0, self.left), max(0, self.top)
        x1, y1 = min(width, self.right), min(height, self.bottom)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = self.mask[y0 - self.top : y1 - self.top, x0 - self.left : x1 - self.left]
        return canvas


def parse_detections(text: str) -> list[Detection]:
    """Parse SAM's output text (one line per frame; an image is frame 0)."""
    if not text.strip():
        return []  # zero matches is a normal result
    parser = image_segmentation_format().create_parser()
    parser.push(text if text.endswith("\n") else text + "\n", emit=False)
    result = parser.finish(CompletedOutcome()).result
    for diagnostic in result.diagnostics:
        log.warning("SAM output: %s", getattr(diagnostic, "message", diagnostic))
    boxes = {r.object_id: r for r in result.records if isinstance(r, SegmentationBoxRecord)}
    detections: list[Detection] = []
    for record in result.records:
        if not isinstance(record, SegmentationMaskRecord):
            continue
        mask = record.mask
        raster = np.frombuffer(decode_mask_to_raster(mask), dtype=np.uint8).reshape(mask.height, mask.width)
        bounds = record.bounds
        left, top = round(bounds.left), round(bounds.top)
        right, bottom = max(left + 1, round(bounds.right)), max(top + 1, round(bounds.bottom))
        if raster.shape != (bottom - top, right - left):  # not seen so far; keep the box's footprint
            raster = (
                np.asarray(Image.fromarray(raster * 255).resize((right - left, bottom - top), Image.NEAREST))
                > 127
            )
        box = boxes.get(record.object_id)
        confidence = record.confidence if record.confidence is not None else None
        if confidence is None and box is not None:
            confidence = box.confidence
        detections.append(
            Detection(
                object_id=record.object_id,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                confidence=1.0 if confidence is None else float(confidence),
                mask=raster.astype(bool),
            )
        )
    return detections


def segment_image(
    client: MetaClient,
    *,
    model: str,
    image: bytes,
    mime: str,
    prompt: str,
    cancel: CancelCheck | None = None,
) -> list[Detection]:
    """Segment every match of `prompt` (one short noun phrase) in an image."""
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    payload = {
        "model": model,
        "store": False,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        # Metadata values are strings on this endpoint.
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
    }
    result = client.responses(payload, cancel=cancel)
    detections = parse_detections(result.text)
    log.info("SAM %r: %d match(es) in %.1fs", prompt, len(detections), result.seconds)
    return detections
