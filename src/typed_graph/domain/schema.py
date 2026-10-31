"""Compile the deliberately bounded graph vocabulary into JSON Schema."""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class GraphError(ValueError):
    """An authored graph or operation violates its declared contract."""


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


ID = {"type": "string", "minLength": 1}
RESULT_SCHEMA = _object(
    {
        "status": {"enum": ["pass", "fail", "indeterminate"]},
        "findings": {"type": "array", "items": {"type": "object"}},
        "evidence": {
            "type": "array",
            "items": _object({"obligation": ID, "uri": ID}, ["obligation", "uri"]),
        },
    },
    ["status", "findings", "evidence"],
)


def _check_json_schema(value: Any) -> None:
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise GraphError(f"Invalid JSON Schema: {exc.message}") from exc

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or (child != "#" and not child.startswith("#/"))
                ):
                    raise GraphError("Only document-local JSON Pointer references are supported")
                if key in {"$id", "$anchor", "$dynamicAnchor", "$dynamicRef"}:
                    raise GraphError(
                        "Use local $defs, not resource IDs or dynamic/anchor references"
                    )
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)


def validate_schema(schema: dict[str, Any]) -> None:
    """Reject unsupported vocabulary instead of silently ignoring constraints."""
    if not isinstance(schema, dict):
        raise GraphError("Schema must be an object")
    unknown = set(schema) - {"version", "node_types", "relations", "invariants", "interceptors"}
    if unknown:
        raise GraphError(f"Unknown schema fields: {sorted(unknown)}")
    if not isinstance(schema.get("version"), str) or not schema["version"]:
        raise GraphError("Schema version must be a nonempty string")
    types = schema.get("node_types")
    relations = schema.get("relations")
    if not isinstance(types, dict) or not isinstance(relations, dict):
        raise GraphError("node_types and relations must be objects")
    for name, definition in types.items():
        if not isinstance(name, str) or not name:
            raise GraphError("Type names must be nonempty strings")
        _check_json_schema(definition)
    for name, relation in relations.items():
        if not isinstance(name, str) or not name or not isinstance(relation, dict):
            raise GraphError("Relations require named object definitions")
        if set(relation) - {"source", "target", "impact", "cardinality", "properties"}:
            raise GraphError(f"Unknown relation fields on {name}")
        for endpoint in ("source", "target"):
            allowed = relation.get(endpoint)
            if (
                not isinstance(allowed, list)
                or not allowed
                or any(not isinstance(t, str) or t not in types for t in allowed)
            ):
                raise GraphError(f"Relation {name} has invalid {endpoint} types")
        if relation.get("impact") not in {"none", "both", "target_to_source", "source_to_target"}:
            raise GraphError(f"Relation {name} requires an explicit impact direction")
        cardinality = relation.get("cardinality", {})
        if not isinstance(cardinality, dict) or set(cardinality) - {
            "out_min",
            "out_max",
            "in_min",
            "in_max",
        }:
            raise GraphError(f"Invalid cardinality on {name}")
        for key, value in cardinality.items():
            if type(value) is not int or value < 0:
                raise GraphError(f"Invalid cardinality {key}")
        for direction in ("out", "in"):
            if cardinality.get(f"{direction}_min", 0) > cardinality.get(
                f"{direction}_max", float("inf")
            ):
                raise GraphError("Cardinality minimum exceeds maximum")
        if "properties" in relation:
            _check_json_schema(relation["properties"])
    invariants = schema.get("invariants", [])
    if not isinstance(invariants, list):
        raise GraphError("invariants must be an array")
    for invariant in invariants:
        if (
            not isinstance(invariant, dict)
            or not isinstance(invariant.get("node_type"), str)
            or invariant.get("node_type") not in types
        ):
            raise GraphError("Invariant requires registered node_type")
        kind = invariant.get("kind")
        if kind == "unique":
            if set(invariant) != {"kind", "node_type", "property"} or not isinstance(
                invariant["property"], str
            ):
                raise GraphError("unique requires one property name")
        elif kind == "requires_edge":
            if set(invariant) - {"kind", "node_type", "relation", "direction", "min"}:
                raise GraphError("Unknown requires_edge fields")
            if (
                not isinstance(invariant.get("relation"), str)
                or invariant.get("relation") not in relations
            ):
                raise GraphError("requires_edge references unknown relation")
            if invariant.get("direction", "out") not in {"out", "in"}:
                raise GraphError("requires_edge direction must be out or in")
            if type(invariant.get("min", 1)) is not int or invariant.get("min", 1) < 0:
                raise GraphError("requires_edge min must be nonnegative integer")
        else:
            raise GraphError(f"Unsupported invariant kind: {kind}")
    interceptors = schema.get("interceptors", [])
    if not isinstance(interceptors, list):
        raise GraphError("interceptors must be an array")
    seen: set[str] = set()
    for handler in interceptors:
        if not isinstance(handler, dict) or set(handler) - {
            "id",
            "target_type",
            "handler",
            "version",
            "trigger",
            "result_schema",
            "evidence_required",
        }:
            raise GraphError("Invalid interceptor definition")
        for key in ("id", "handler", "version"):
            if not isinstance(handler.get(key), str) or not handler[key]:
                raise GraphError(f"Interceptor requires {key}")
        if handler["id"] in seen:
            raise GraphError("Duplicate interceptor id")
        seen.add(handler["id"])
        if (
            not isinstance(handler.get("target_type"), str)
            or handler.get("target_type") not in types
            or handler.get("trigger") != "dependency_changed"
        ):
            raise GraphError("Interceptor requires registered target_type and dependency_changed")
        obligations = handler.get("evidence_required", [])
        if (
            not isinstance(obligations, list)
            or any(not isinstance(x, str) or not x for x in obligations)
            or len(obligations) != len(set(obligations))
        ):
            raise GraphError("evidence_required must contain unique nonempty strings")
        if "result_schema" in handler:
            _check_json_schema(handler["result_schema"])


def _relocate(schema: Any, prefix: str) -> Any:
    if isinstance(schema, dict):
        return {
            key: prefix + value[1:] if key in {"$ref", "$dynamicRef"} else _relocate(value, prefix)
            for key, value in schema.items()
        }
    if isinstance(schema, list):
        return [_relocate(value, prefix) for value in schema]
    return copy.deepcopy(schema)


def apply_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Typed full-replacement updates; no untyped properties escape hatch."""
    validate_schema(schema)
    alternatives: list[dict[str, Any]] = []
    definitions: dict[str, Any] = {}
    for index, (name, definition) in enumerate(sorted(schema["node_types"].items())):
        key = f"node_{index}"
        definitions[key] = _relocate(definition, f"#/$defs/{key}")
        fields = {
            "id": ID,
            "type": {"const": name},
            "properties": {"allOf": [{"type": "object"}, {"$ref": f"#/$defs/{key}"}]},
        }
        node = _object(fields, list(fields))
        alternatives.append(_object({"op": {"const": "create_node"}, "node": node}, ["op", "node"]))
        alternatives.append(_object({"op": {"const": "update_node"}, **fields}, ["op", *fields]))
    for index, (name, relation) in enumerate(sorted(schema["relations"].items())):
        key = f"edge_{index}"
        definitions[key] = _relocate(
            relation.get("properties", {"type": "object", "additionalProperties": False}),
            f"#/$defs/{key}",
        )
        fields = {
            "id": ID,
            "type": {"const": name},
            "source": ID,
            "target": ID,
            "properties": {"allOf": [{"type": "object"}, {"$ref": f"#/$defs/{key}"}]},
        }
        required = ["id", "type", "source", "target"]
        alternatives.append(
            _object(
                {"op": {"const": "create_edge"}, "edge": _object(fields, required)}, ["op", "edge"]
            )
        )
        alternatives.append(_object({"op": {"const": "update_edge"}, **fields}, ["op", *required]))
    for kind in ("node", "edge"):
        alternatives.append(_object({"op": {"const": f"delete_{kind}"}, "id": ID}, ["op", "id"]))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": definitions,
        **_object(
            {
                "expected_revision": {"type": "integer", "minimum": 0},
                "changes": {
                    "type": "array",
                    "items": {"oneOf": alternatives} if schema["node_types"] else False,
                },
            },
            ["expected_revision", "changes"],
        ),
    }


APPLY_OUTPUT_SCHEMA = _object(
    {
        "revision": {"type": "integer", "minimum": 0},
        "applied_changes": {"type": "array", "items": {"type": "object"}},
        "invalidations": {
            "type": "array",
            "items": _object(
                {
                    "node_id": ID,
                    "paths": {"type": "array", "items": {"type": "array", "items": ID}},
                    "triggering_revision": {"type": "integer", "minimum": 0},
                    "component_id": ID,
                    "component": {"type": "array", "items": ID, "minItems": 1},
                },
                ["node_id", "paths", "triggering_revision", "component_id", "component"],
            ),
        },
    },
    ["revision", "applied_changes", "invalidations"],
)


def compile_schema(document: dict[str, Any]) -> dict[str, Any]:
    """Normalize the concise authoring form without embedding an ontology."""
    if "node_types" in document:
        validate_schema(document)
        return copy.deepcopy(document)
    if set(document) - {"schema", "nodes", "edges", "invariants", "interceptors"}:
        raise GraphError("Unknown concise schema fields")
    if not isinstance(document.get("schema"), str):
        raise GraphError("Concise schema requires schema version string")
    nodes, edges = document.get("nodes"), document.get("edges", {})
    if not isinstance(nodes, dict) or not isinstance(edges, dict):
        raise GraphError("Concise schema nodes and edges must be mappings")

    def property_schema(value: Any) -> Any:
        if isinstance(value, str):
            if value not in {"string", "number", "integer", "boolean", "object", "array", "null"}:
                raise GraphError(f"Unsupported concise property type: {value}")
            return {"type": value}
        if isinstance(value, (dict, bool)):
            return copy.deepcopy(value)
        raise GraphError("Property type must be a primitive type name or JSON Schema")

    compiled_nodes: dict[str, Any] = {}
    for name, definition in nodes.items():
        if not isinstance(definition, dict):
            raise GraphError("Concise node definitions must be objects")
        properties = definition.get("properties", {})
        if not isinstance(properties, dict):
            raise GraphError("Concise properties must be a mapping")
        compiled_nodes[name] = {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(properties),
            **copy.deepcopy(definition),
            "properties": {key: property_schema(value) for key, value in properties.items()},
        }
    compiled_edges: dict[str, Any] = {}
    for name, definition in edges.items():
        if not isinstance(definition, dict) or set(definition) - {
            "from",
            "to",
            "impact",
            "cardinality",
            "properties",
        }:
            raise GraphError("Invalid concise edge definition")
        relation = {
            key: copy.deepcopy(value)
            for key, value in definition.items()
            if key not in {"from", "to"}
        }
        for source, target in (("from", "source"), ("to", "target")):
            endpoint = definition.get(source)
            relation[target] = [endpoint] if isinstance(endpoint, str) else endpoint
        compiled_edges[name] = relation
    result = {
        "version": document["schema"],
        "node_types": compiled_nodes,
        "relations": compiled_edges,
        "invariants": copy.deepcopy(document.get("invariants", [])),
        "interceptors": copy.deepcopy(document.get("interceptors", [])),
    }
    validate_schema(result)
    return result
