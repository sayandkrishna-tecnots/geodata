"""JSON Schema -> TypeScript interfaces.

Guarantee 2 of the multi-stack plan: the TS types and the Python dataclasses
describe the same fields because both are derived from `schema/*.schema.json`.
Hand-writing the TS side would let the two drift silently, and a drifted field
is invisible until a consumer reads `undefined` in production.

Field names stay **snake_case**, matching the NDJSON exactly. Camel-casing
would mean a per-row transform over 152,970 cities at load time, and would put
a translation layer between the schema and the type -- which is the thing this
module exists to prevent. The *functions* are camelCase (idiomatic JS); the
*data* is snake_case (it is the wire format).
"""

import json
import os
import re

_SCALARS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def _wrap_doc(text, indent):
    """A description as a JSDoc block, wrapped at 76 columns."""
    if not text:
        return []
    words, lines, cur = text.split(), [], ""
    for word in words:
        if cur and len(cur) + len(word) + 1 > 72 - len(indent):
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        lines.append(cur)
    if len(lines) == 1:
        return ["{}/** {} */".format(indent, lines[0])]
    out = ["{}/**".format(indent)]
    out += ["{} * {}".format(indent, line) for line in lines]
    out.append("{} */".format(indent))
    return out


def _type_expr(node, indent):
    """Render one property's type. Returns (expr, extra_lines_are_inline)."""
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])

    if "oneOf" in node:
        parts = [_type_expr(sub, indent) for sub in node["oneOf"]]
        # `null` last reads better and matches how the data is shaped.
        parts = sorted(set(parts), key=lambda p: (p == "null", p))
        return " | ".join(parts)

    kind = node.get("type")

    if isinstance(kind, list):
        return " | ".join(
            sorted({_SCALARS[k] for k in kind}, key=lambda p: (p == "null", p))
        )

    if kind == "array":
        return _type_expr(node.get("items", {}), indent) + "[]"

    if kind == "object":
        return _object_expr(node, indent)

    if kind in _SCALARS:
        return _SCALARS[kind]

    return "unknown"


def _object_expr(node, indent):
    """An inline object literal type, for nested structures like `timezones`."""
    required = set(node.get("required", []))
    inner = indent + "  "
    lines = ["{"]
    for name, prop in node.get("properties", {}).items():
        lines += _wrap_doc(prop.get("description"), inner)
        optional = "" if name in required else "?"
        lines.append("{}{}{}: {};".format(inner, name, optional, _type_expr(prop, inner)))
    lines.append(indent + "}")
    return "\n".join(lines)


def interface(schema, name=None, extra_doc=None):
    """Render one schema as an exported TS interface."""
    title = name or schema.get("title") or "Unknown"

    doc = schema.get("description", "")
    if extra_doc:
        doc = (doc + " " + extra_doc).strip()

    out = _wrap_doc(doc, "")
    out.append("export interface {} {{".format(title))
    for prop_name, prop in schema.get("properties", {}).items():
        out += _wrap_doc(prop.get("description"), "  ")
        # Every property the schema does not require is nullable in practice;
        # the builder writes explicit `null` rather than omitting keys, so the
        # type is `T | null`, not `T | undefined`. That distinction matters --
        # `?:` would let `city.latitude` be missing, which it never is.
        out.append("  {}: {};".format(prop_name, _type_expr(prop, "  ")))
    out.append("}")
    return "\n".join(out)


def load(schema_dir, stem):
    with open(os.path.join(schema_dir, stem + ".schema.json"), encoding="utf-8") as fh:
        return json.load(fh)
