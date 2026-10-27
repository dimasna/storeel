"""SAM 3.1 image segmentation over the Responses API.

SAM answers a short noun phrase ("orange cat", "face") with a box and a mask for every
match, as special-token text, one line per frame (an image is frame 0):

    <0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|><|mask;x=0;y=0;c=..;data=H,W,!payload|>,1<|box...

Boxes are read straight from that documented grammar. Masks are decoded only when needed,
with Meta's `meta_sam_parser` codec: it is pure Python and takes seconds for a large mask,
so faces (box only) are never decoded and a reference cutout decodes just the match it uses.
Each mask is box-local and is placed back at its box.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field

import numpy as np
from meta_sam_parser import SegmentationMask, decode_mask_to_raster
from PIL import Image

from ..common import CancelCheck
from .client import MetaClient

log = logging.getLogger(__name__)

FRAME = re.compile(r"^<(\d+)f(?:;[^>]*)?>")
RECORD = re.compile(r",?(\d+)((?:<\|[A-Za-z][A-Za-z0-9_.-]*(?:;[^|]*)?\|>)+)")
TOKEN = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|]*))?\|>")
MASK_DATA = re.compile(r"^(\d+),(\d+),([!~].*)$")


@dataclass
class Detection:
    """One match: a half-open box in source pixels, and its mask (decoded on first use)."""

    object_id: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float
    encoded: SegmentationMask | None = None
    _mask: np.ndarray | None = field(default=None, repr=False)

    @property
    def box_area(self) -> int:
        return (self.right - self.left) * (self.bottom - self.top)

    @property
    def score(self) -> float:
        return self.confidence * self.box_area

    @property
    def mask(self) -> np.ndarray:
        """The box-local boolean mask; the box itself when SAM sent none."""
        if self._mask is None:
            shape = (self.bottom - self.top, self.right - self.left)
            if self.encoded is None:
                self._mask = np.ones(shape, dtype=bool)
            else:
                raw = decode_mask_to_raster(self.encoded)
                raster = np.frombuffer(raw, dtype=np.uint8).reshape(self.encoded.height, self.encoded.width)
                if raster.shape != shape:  # not seen so far; keep the box's footprint
                    resized = Image.fromarray(raster * 255).resize((shape[1], shape[0]), Image.NEAREST)
                    raster = np.asarray(resized) > 127
                self._mask = raster.astype(bool)
        return self._mask

    @property
    def area(self) -> int:
        return int(self.mask.sum())

    def full_mask(self, width: int, height: int) -> np.ndarray:
        """The mask on a `height` x `width` canvas (the source image)."""
        canvas = np.zeros((height, width), dtype=bool)
        x0, y0 = max(0, self.left), max(0, self.top)
        x1, y1 = min(width, self.right), min(height, self.bottom)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = self.mask[y0 - self.top : y1 - self.top, x0 - self.left : x1 - self.left]
        return canvas


def _fields(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (text or "").split(";"):
        key, _, value = part.partition("=")
        if key:
            out[key] = value
    return out


def parse_detections(text: str, frame: int = 0) -> list[Detection]:
    """The matches on one frame of SAM's output text. Empty text means zero matches."""
    detections: list[Detection] = []
    for line in text.splitlines():
        header = FRAME.match(line.strip())
        if header is None or int(header.group(1)) != frame:
            continue
        for record in RECORD.finditer(line.strip()[header.end() :]):
            tokens = {name: _fields(body) for name, body in TOKEN.findall(record.group(2))}
            box = tokens.get("box")
            if box is None:
                continue
            try:
                left, top = int(box["x1"]), int(box["y1"])
                right, bottom = int(box["x2"]) + 1, int(box["y2"]) + 1  # x2, y2 are inclusive
                confidence = float(box.get("c") or tokens.get("mask", {}).get("c") or 1.0)
            except (KeyError, ValueError):
                log.warning("skipping a SAM record with an unreadable box")
                continue
            encoded = None
            data = MASK_DATA.match(tokens.get("mask", {}).get("data", ""))
            if data:
                height, width, payload = int(data.group(1)), int(data.group(2)), data.group(3)
                encoding = "one_bit" if payload.startswith("!") else "lossless"
                encoded = SegmentationMask(encoding=encoding, payload=payload, width=width, height=height)
            if right > left and bottom > top:
                detections.append(Detection(record.group(1), left, top, right, bottom, confidence, encoded))
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
