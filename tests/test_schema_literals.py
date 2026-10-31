"""Schema keywords are interpreted only at schema locations, not in user data."""

import json

import pytest
from jsonschema import Draft202012Validator

from typed_graph.adapters.workspace import open_service
from typed_graph.domain.schema import GraphError, apply_input_schema


def test_literal_keyword_names_survive_import_and_typed_apply(tmp_path):
    literal = {"$ref": "#/foo", "$id": "this is data"}
    schema = {
        "version": "1",
        "node_types": {
            "Item": {
                "type": "object",
                "$defs": {"word": {"type": "string"}},
                "properties": {
                    "$id": {"$ref": "#/$defs/word"},
                    "$ref": {"type": "object", "const": literal},
                    "enum": {"enum": [{"$ref": "https://literal.invalid"}]},
                },
                "required": ["$id", "$ref", "enum"],
                "additionalProperties": False,
                "default": literal,
                "examples": [literal],
            }
        },
        "relations": {},
    }
    model = {"schema": schema, "nodes": [], "edges": []}
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "input.json").write_text(json.dumps(model))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    properties = {"$id": "a", "$ref": literal, "enum": {"$ref": "https://literal.invalid"}}
    args = {
        "expected_revision": 1,
        "changes": [
            {"op": "create_node", "node": {"id": "a", "type": "Item", "properties": properties}}
        ],
    }
    compiled = apply_input_schema(service.schema)
    Draft202012Validator(compiled).validate(args)
    assert compiled["$defs"]["node_0"]["default"] == literal
    assert compiled["$defs"]["node_0"]["examples"] == [literal]
    assert compiled["$defs"]["node_0"]["properties"]["$ref"]["const"] == literal
    service.dispatch("apply_changes", args)
    assert (
        open_service(tmp_path).resource("graph://model/nodes/a")["node"]["properties"] == properties
    )


@pytest.mark.parametrize(
    "definition",
    [
        {"properties": {"$id": {"$ref": "https://example.invalid/schema"}}},
        {"$defs": {"$ref": {"$ref": "https://example.invalid/schema"}}},
        {"allOf": [{"$ref": "https://example.invalid/schema"}]},
        {"items": {"$ref": "https://example.invalid/schema"}},
        {"dependentSchemas": {"$id": {"$ref": "https://example.invalid/schema"}}},
        {"contentSchema": {"$ref": "https://example.invalid/schema"}},
    ],
)
def test_actual_remote_schema_references_fail_import(tmp_path, definition):
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "input.json").write_text(
        json.dumps(
            {
                "schema": {"version": "1", "node_types": {"Item": definition}, "relations": {}},
                "nodes": [],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    with pytest.raises(GraphError):
        service.dispatch("index_model", {})
    assert service.revision == 0


def test_local_reference_cannot_activate_remote_ref_hidden_in_literal(tmp_path):
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "input.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "relations": {},
                    "node_types": {
                        "Item": {
                            "$ref": "#/default",
                            "default": {"$ref": "https://example.invalid/hidden-schema"},
                        }
                    },
                },
                "nodes": [],
                "edges": [],
            }
        )
    )
    with pytest.raises(GraphError, match="schema-bearing"):
        open_service(tmp_path).dispatch("index_model", {})
