"""Import user-authored readable schemas and Markdown, then reconcile tool edits."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from typed_graph.adapters.workspace import open_service
from typed_graph.domain.schema import apply_input_schema


def test_concise_yaml_and_markdown_compile_typed_tools(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "schema.yaml").write_text("""
schema: architecture/v1
nodes:
  Capability:
    properties:
      name: string
      description: string
  Boundary:
    properties:
      name: string
edges:
  provides:
    from: Boundary
    to: Capability
    impact: target_to_source
""")
    (model / "notes.md").write_text("""
# Human notes ignored by the parser
```graph
nodes:
  - id: capability
    type: Capability
    properties: {name: Authorize, description: Payment authorization}
  - id: boundary
    type: Boundary
    properties: {name: Payments}
edges:
  - {id: provides, type: provides, source: boundary, target: capability}
```
""")
    service = open_service(tmp_path)
    assert service.dispatch("index_model", {})["revision"] == 1
    arguments = {
        "expected_revision": 1,
        "changes": [
            {
                "op": "update_node",
                "id": "capability",
                "type": "Capability",
                "properties": {"name": "Authorize", "description": "Changed description"},
            }
        ],
    }
    Draft202012Validator(apply_input_schema(service.schema)).validate(arguments)
    result = service.dispatch("apply_changes", arguments)
    assert [item["node_id"] for item in result["invalidations"]] == ["capability", "boundary"]


def test_noop_import_refreshes_three_way_baseline(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    path = model / "model.json"
    document = {
        "schema": {
            "version": "1",
            "node_types": {
                "Thing": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            },
            "relations": {},
        },
        "nodes": [{"id": "a", "type": "Thing", "properties": {"name": "initial"}}],
        "edges": [],
    }
    path.write_text(json.dumps(document))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "Thing",
                    "properties": {"name": "same"},
                }
            ],
        },
    )
    document["nodes"][0]["properties"]["name"] = "same"
    path.write_text(json.dumps(document))
    assert service.dispatch("index_model", {})["revision"] == 2
    document["nodes"][0]["properties"]["name"] = "next"
    path.write_text(json.dumps(document))
    assert service.dispatch("index_model", {})["revision"] == 3


def test_property_equality_distinguishes_missing_null_and_value(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {
                        "Thing": {
                            "type": "object",
                            "properties": {"optional": {"type": ["string", "null"]}},
                        }
                    },
                    "relations": {},
                },
                "nodes": [
                    {"id": "missing", "type": "Thing", "properties": {}},
                    {"id": "null", "type": "Thing", "properties": {"optional": None}},
                    {"id": "value", "type": "Thing", "properties": {"optional": "present"}},
                ],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    for where, expected in [
        ({}, ["missing", "null", "value"]),
        ({"optional": None}, ["null"]),
        ({"optional": "present"}, ["value"]),
        ({"optional": "absent"}, []),
        ({"unknown": None}, []),
    ]:
        result = service.dispatch("query_graph", {"where": where})
        assert [node["id"] for node in result["nodes"]] == expected
