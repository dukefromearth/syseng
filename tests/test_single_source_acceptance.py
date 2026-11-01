"""Contract acceptance through every advertised tool and actual persisted workspaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from typed_graph.adapters.mcp_server import create_server
from typed_graph.adapters.workspace import open_service


def author_novel_ontology(workspace: Path) -> None:
    model = workspace / "model"
    model.mkdir()
    definition = {
        "$defs": {"designation": {"type": "string", "minLength": 2}},
        "type": "object",
        "properties": {"designation": {"$ref": "#/$defs/designation"}},
        "required": ["designation"],
        "additionalProperties": False,
    }
    document = {
        "schema": {
            "version": "novel-ontology",
            "node_types": {"MycelialChamber": definition},
            "relations": {
                "feeds_spores_into": {
                    "source": ["MycelialChamber"],
                    "target": ["MycelialChamber"],
                    "impact": "source_to_target",
                    "properties": {
                        "type": "object",
                        "properties": {"flow": {"type": "integer", "minimum": 1}},
                        "required": ["flow"],
                        "additionalProperties": False,
                    },
                }
            },
            "interceptors": [
                {
                    "id": "spore-audit",
                    "target_type": "MycelialChamber",
                    "handler": "operator-only",
                    "version": "1",
                    "trigger": "dependency_changed",
                    "evidence_required": ["microscopy"],
                }
            ],
        },
        "nodes": [
            {"id": name, "type": "MycelialChamber", "properties": {"designation": name}}
            for name in ["north", "south"]
        ],
        "edges": [
            {
                "id": "hypha",
                "type": "feeds_spores_into",
                "source": "north",
                "target": "south",
                "properties": {"flow": 2},
            }
        ],
    }
    (model / "fungal.json").write_text(json.dumps(document))


@pytest.mark.parametrize("transport", ["inprocess", "stdio"])
async def test_every_discovered_tool_and_authored_only_ontology(
    tmp_path: Path, transport: str
) -> None:
    author_novel_ontology(tmp_path)
    server = (
        create_server(open_service(tmp_path))
        if transport == "inprocess"
        else StdioServerParameters(
            command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(tmp_path)]
        )
    )
    async with Client(server, read_timeout_seconds=10) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        exercised: set[str] = set()

        async def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            Draft202012Validator(tools[name].input_schema).validate(arguments)
            response = await client.call_tool(name, arguments)
            assert not response.is_error, (name, response)
            result = response.structured_content
            assert isinstance(result, dict), (name, response)
            assert tools[name].output_schema is not None, name
            Draft202012Validator(tools[name].output_schema).validate(result)
            exercised.add(name)
            return result

        assert (await invoke("index_model", {}))["revision"] == 1
        tools = {tool.name: tool for tool in (await client.list_tools(cache_mode="refresh")).tools}
        assert "MycelialChamber" in json.dumps(tools["apply_changes"].input_schema)
        assert "feeds_spores_into" in json.dumps(tools["apply_changes"].input_schema)
        assert (await invoke("get_graph_schema", {}))["schema"]["version"] == "novel-ontology"
        assert len((await invoke("search_graph", {"text": "north"}))["nodes"]) == 1
        queried = await invoke("query_graph", {"where": {"designation": "south"}})
        assert [node["id"] for node in queried["nodes"]] == ["south"]
        traced = await invoke(
            "trace_path", {"source": "north", "target": "south", "mode": "dependency"}
        )
        assert traced["path"] == ["north", "south"]
        detected = await invoke("detect_changes", {})
        assert detected["changed_nodes"] == []
        assert detected["preview_revision"] == 2
        assert "impact" in detected
        applied = await invoke(
            "apply_changes",
            {
                "expected_revision": 1,
                "changes": [
                    {
                        "op": "update_node",
                        "id": "north",
                        "type": "MycelialChamber",
                        "properties": {"designation": "north-updated"},
                    }
                ],
            },
        )
        assert applied["revision"] == 2
        assert {item["node_id"] for item in applied["invalidations"]} == {"north", "south"}
        compared = await invoke("compare_graphs", {"from_revision": 1, "to_revision": 2})
        assert compared["nodes"]["updated"] == ["north"]
        assert len((await invoke("get_assessments", {"revision": 2}))["assessments"]) == 2
        submitted = await invoke(
            "submit_assessment",
            {
                "revision": 2,
                "interceptor_id": "spore-audit",
                "target_id": "north",
                "result": {
                    "status": "pass",
                    "findings": [],
                    "evidence": [{"obligation": "microscopy", "uri": "urn:lab:sample-1"}],
                },
            },
        )
        assert submitted["assessment"]["state"] == "completed"
        assert exercised == set(tools), "Every advertised tool needs a public behavior scenario"
        for uri in [
            "graph://model/schema",
            "graph://model/nodes/north",
            "graph://model/revisions/2",
            "graph://model/impact/2",
            "graph://model/assessments/2",
        ]:
            resource = await client.read_resource(uri)
            assert json.loads(resource.contents[0].text)

    restarted = open_service(tmp_path)
    found = restarted.dispatch("query_graph", {"type": "MycelialChamber"})
    assert found["revision"] == 2
    assert found["nodes"][0]["properties"]["designation"] == "north-updated"
    historical = restarted.dispatch("compare_graphs", {"from_revision": 1, "to_revision": 2})
    assert historical["edges"] == {"added": [], "removed": [], "updated": []}
    assessments = restarted.dispatch("get_assessments", {"revision": 2})["assessments"]
    assert next(a for a in assessments if a["target_id"] == "north")["result"]["status"] == "pass"


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("query_graph", {"limit": True}),
        ("query_graph", {"type": None}),
        ("search_graph", {"type": None}),
        ("get_assessments", {"revision": None}),
        ("trace_path", {"source": "north", "target": "south", "relation": None}),
        ("trace_path", {"source": "north", "target": "south", "relation": "undeclared"}),
        ("query_graph", {"limit": "2"}),
        ("search_graph", {"limit": False}),
        ("search_graph", {"text": 3}),
        ("trace_path", {"source": "north", "target": "south", "max_depth": True}),
        ("get_assessments", {"revision": True}),
        ("compare_graphs", {"from_revision": "1", "to_revision": 1}),
        ("get_graph_schema", {"unexpected": True}),
        ("index_model", {"unexpected": True}),
        ("apply_changes", {"expected_revision": True, "changes": []}),
        (
            "apply_changes",
            {
                "expected_revision": 1,
                "changes": [
                    {
                        "op": "create_node",
                        "node": {
                            "id": "temporary",
                            "type": "MycelialChamber",
                            "properties": {"designation": 42},
                        },
                    },
                    {"op": "delete_node", "id": "temporary"},
                ],
            },
        ),
        (
            "submit_assessment",
            {
                "revision": 1,
                "interceptor_id": "spore-audit",
                "target_id": "north",
                "result": {
                    "status": "indeterminate",
                    "findings": [],
                    "evidence": [{"obligation": "", "uri": "urn:sample"}],
                },
            },
        ),
        (
            "submit_assessment",
            {
                "revision": 1,
                "interceptor_id": "spore-audit",
                "target_id": "north",
                "result": {
                    "status": "indeterminate",
                    "findings": [],
                    "evidence": [{"obligation": "microscopy", "uri": "urn:sample", "x": 1}],
                },
            },
        ),
    ],
)
async def test_strict_input_contract_is_identical_across_public_entrypoints(
    tmp_path: Path, name: str, arguments: dict[str, Any]
) -> None:
    author_novel_ontology(tmp_path)
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    with pytest.raises(ValueError):
        service.dispatch(name, arguments)
    async with Client(create_server(service), read_timeout_seconds=10) as client:
        tool = next(tool for tool in (await client.list_tools()).tools if tool.name == name)
        assert not Draft202012Validator(tool.input_schema).is_valid(arguments)
        rejected = await client.call_tool(name, arguments)
        assert rejected.is_error, (name, arguments, rejected)
    assert service.revision == 1
