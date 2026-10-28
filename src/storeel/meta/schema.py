"""Structured output: Pydantic models as strict JSON schemas for `text.format`, and a
lenient reader for what comes back."""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import BaseModel

_DROP = frozenset({"title", "default"})


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the strict subset Model API validates.

    `$ref`s are inlined, every object gets `additionalProperties: false`, and `required`
    lists every property. Fields with defaults become required too: decoding is
    constrained to the schema, so the model always has to produce them.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any, names: bool = False) -> Any:
        """`names`: `node` maps property names to schemas, so its keys are kept as they are
        (a field called "title" is a property, not Pydantic's "title" label)."""
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if names:
            return {name: resolve(value) for name, value in node.items()}
        if "$ref" in node:
            target = resolve(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            for key, value in node.items():
                if key != "$ref" and key not in _DROP:
                    target[key] = resolve(value)
            return target
        out = {key: resolve(value, key == "properties") for key, value in node.items() if key not in _DROP}
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return resolve(schema)


def text_format(name: str, model: type[BaseModel]) -> dict[str, Any]:
    """The Responses API `text` parameter that constrains output to `model`."""
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": strict_json_schema(model),
            "strict": True,
        }
    }


class OutputError(ValueError):
    """The model's answer is not a JSON object."""


def _json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate a fenced or prefixed answer: take the outermost {...}.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise OutputError("the answer is not JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OutputError(f"the answer is not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise OutputError("the answer is not a JSON object")
    return data


def parse_output[M: BaseModel](model: type[M], text: str) -> tuple[M, list[str]]:
    """Read structured output leniently.

    Muse Spark does not always produce every field the schema marks required (a script came
    back without its title), so output models give a default to every field they can do
    without, and this also returns the top-level fields that were missing.
    """
    data = _json_object(text)
    missing = [name for name in model.model_fields if name not in data]
    return model.model_validate(data), missing
