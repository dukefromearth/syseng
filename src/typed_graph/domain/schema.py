"""Compile the deliberately bounded graph vocabulary into JSON Schema."""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError as ModelValidationError

from typed_graph.domain.models import (
    ApplyChangesRequest,
    ApplyResult,
    AssessmentResult,
    GraphSchema,
    RequiresEdgeInvariant,
)


class GraphError(ValueError):
    """An authored graph or operation violates its declared contract."""


RESULT_SCHEMA = AssessmentResult.model_json_schema()


_SCHEMA_MAP_KEYWORDS = {"properties", "$defs", "patternProperties", "dependentSchemas"}
_SCHEMA_ARRAY_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SCHEMA_SINGLE_KEYWORDS = {
    "items",
    "additionalProperties",
    "contains",
    "unevaluatedItems",
    "unevaluatedProperties",
    "not",
    "if",
    "then",
    "else",
    "propertyNames",
    "contentSchema",
}


def _schema_children(schema: dict[str, Any]) -> list[Any]:
    children: list[Any] = []
    for key, value in schema.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            children.extend(value.values())
        elif key in _SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            children.extend(value)
        elif key in _SCHEMA_SINGLE_KEYWORDS:
            children.append(value)
    return children


def _check_json_schema(value: Any) -> None:
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise GraphError(f"Invalid JSON Schema: {exc.message}") from exc

    schema_locations: set[int] = set()
    references: list[str] = []

    def walk(item: Any) -> None:
        schema_locations.add(id(item))
        if not isinstance(item, dict):
            return
        if "$ref" in item:
            references.append(item["$ref"])
        for key, child in item.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or (child != "#" and not child.startswith("#/"))
            ):
                raise GraphError("Only document-local JSON Pointer references are supported")
            if key in {"$id", "$anchor", "$dynamicAnchor", "$dynamicRef"}:
                raise GraphError("Use local $defs, not resource IDs or dynamic/anchor references")
        for child in _schema_children(item):
            walk(child)

    walk(value)
    for reference in references:
        target = value
        if reference != "#":
            try:
                for token in reference[2:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    target = target[int(token)] if isinstance(target, list) else target[token]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise GraphError(f"Unresolved local schema reference: {reference}") from exc
        if id(target) not in schema_locations:
            raise GraphError("Local references must target schema-bearing keyword locations")


def validate_schema(schema: dict[str, Any]) -> None:
    """Validate canonical shape once, then the authored graph's semantic references."""
    try:
        model = GraphSchema.model_validate(schema)
    except ModelValidationError as exc:
        raise GraphError(f"Invalid graph schema: {exc}") from exc
    validate_typed_schema(model)


def validate_typed_schema(model: GraphSchema) -> None:
    """Semantic checks on an already validated canonical graph schema."""
    for definition in model.node_types.values():
        _check_json_schema(definition)
    for name, relation in model.relations.items():
        for endpoint in (relation.source, relation.target):
            if any(node_type not in model.node_types for node_type in endpoint):
                raise GraphError(f"Relation {name} references unknown endpoint type")
        cardinality = relation.cardinality
        if cardinality is not None:
            for direction in ("out", "in"):
                minimum = getattr(cardinality, f"{direction}_min")
                maximum = getattr(cardinality, f"{direction}_max")
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise GraphError("Cardinality minimum exceeds maximum")
        if "properties" in relation.model_fields_set:
            _check_json_schema(relation.properties)
    for invariant in model.invariants:
        if invariant.node_type not in model.node_types:
            raise GraphError("Invariant requires registered node_type")
        if isinstance(invariant, RequiresEdgeInvariant):
            required_relation = model.relations.get(invariant.relation)
            if required_relation is None:
                raise GraphError("requires_edge references unknown relation")
            endpoints = (
                required_relation.source
                if invariant.direction == "out"
                else required_relation.target
            )
            if invariant.node_type not in endpoints:
                raise GraphError("requires_edge node_type is incompatible with relation endpoint")
            if required_relation.cardinality is not None:
                maximum = (
                    required_relation.cardinality.out_max
                    if invariant.direction == "out"
                    else required_relation.cardinality.in_max
                )
                if maximum is not None and invariant.min > maximum:
                    raise GraphError("requires_edge minimum exceeds relation cardinality maximum")
    seen: set[str] = set()
    for interceptor in model.interceptors:
        if interceptor.id in seen:
            raise GraphError("Duplicate interceptor id")
        seen.add(interceptor.id)
        if interceptor.target_type not in model.node_types:
            raise GraphError("Interceptor requires registered target_type")
        if len(interceptor.evidence_required) != len(set(interceptor.evidence_required)):
            raise GraphError("evidence_required must contain unique identifiers")
        if "result_schema" in interceptor.model_fields_set:
            _check_json_schema(interceptor.result_schema)


def _relocate(schema: Any, prefix: str) -> Any:
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    result = copy.deepcopy(schema)
    for key, value in schema.items():
        if key in {"$ref", "$dynamicRef"}:
            result[key] = prefix + value[1:]
        elif key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            result[key] = {name: _relocate(child, prefix) for name, child in value.items()}
        elif key in _SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            result[key] = [_relocate(child, prefix) for child in value]
        elif key in _SCHEMA_SINGLE_KEYWORDS:
            result[key] = _relocate(value, prefix)
    return result


def apply_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Specialize canonical operation schemas with registered types and property contracts."""
    validate_schema(schema)
    model = GraphSchema.model_validate(schema)
    result = ApplyChangesRequest.model_json_schema()
    definitions = result["$defs"]
    alternatives: list[dict[str, Any]] = []
    for index, (name, definition) in enumerate(sorted(schema["node_types"].items())):
        key = f"node_{index}"
        definitions[key] = _relocate(definition, f"#/$defs/{key}")
        properties = {"allOf": [{"type": "object"}, {"$ref": f"#/$defs/{key}"}]}
        node = copy.deepcopy(definitions["Node"])
        node["properties"]["type"] = {"const": name, "type": "string"}
        node["properties"]["properties"] = properties
        create = copy.deepcopy(definitions["CreateNode"])
        create["properties"]["node"] = node
        update = copy.deepcopy(definitions["UpdateNode"])
        update["properties"]["type"] = {"const": name, "type": "string"}
        update["properties"]["properties"] = properties
        alternatives.extend((create, update))
    for index, (name, relation) in enumerate(sorted(model.relations.items())):
        key = f"edge_{index}"
        definitions[key] = _relocate(
            relation.property_schema,
            f"#/$defs/{key}",
        )
        properties = {"allOf": [{"type": "object"}, {"$ref": f"#/$defs/{key}"}]}
        edge = copy.deepcopy(definitions["Edge"])
        edge["properties"]["type"] = {"const": name, "type": "string"}
        edge["properties"]["properties"] = properties
        create = copy.deepcopy(definitions["CreateEdge"])
        create["properties"]["edge"] = edge
        update = copy.deepcopy(definitions["UpdateEdge"])
        update["properties"]["type"] = {"const": name, "type": "string"}
        update["properties"]["properties"] = properties
        alternatives.extend((create, update))
    alternatives.extend(copy.deepcopy(definitions[kind]) for kind in ("DeleteNode", "DeleteEdge"))
    result["properties"]["changes"]["items"] = (
        {"oneOf": alternatives} if schema["node_types"] else False
    )
    result["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return result


APPLY_OUTPUT_SCHEMA = ApplyResult.model_json_schema()


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
