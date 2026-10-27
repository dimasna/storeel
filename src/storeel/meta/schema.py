"""Structured output: Pydantic models as strict JSON schemas for `text.format`."""

from __future__ import annotations

import copy
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

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = resolve(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            for key, value in node.items():
                if key != "$ref" and key not in _DROP:
                    target[key] = resolve(value)
            return target
        out = {key: resolve(value) for key, value in node.items() if key not in _DROP}
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
