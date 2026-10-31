"""Public MCP behavior with actual SDK transports, source files and SQLite."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.subscriptions import ResourceUpdated, ToolsListChanged
from mcp.shared.exceptions import MCPError

from typed_graph.adapters.mcp_server import create_server
from typed_graph.adapters.workspace import open_service


def author(workspace: Path, *, handler: str = "pending") -> Path:
    model = workspace / "model"
    model.mkdir()
    path = model / "graph.json"
    path.write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {
                        "Thing": {
                            "type": "object",
                            "properties": {"label": {"type": "string"}},
                            "required": ["label"],
                            "additionalProperties": False,
                        }
                    },
                    "relations": {
                        "needs": {
                            "source": ["Thing"],
                            "target": ["Thing"],
                            "impact": "target_to_source",
                        }
                    },
                    "interceptors": [
                        {
                            "id": "check",
                            "target_type": "Thing",
                            "handler": handler,
                            "version": "1",
                            "trigger": "dependency_changed",
                            "evidence_required": ["proof"],
                        }
                    ],
                },
                "nodes": [
                    {"id": "a", "type": "Thing", "properties": {"label": "a"}},
                    {"id": "b", "type": "Thing", "properties": {"label": "b"}},
                ],
                "edges": [{"id": "ab", "type": "needs", "source": "a", "target": "b"}],
            }
        )
    )
    return path


@pytest.mark.parametrize("transport", ["inprocess", "stdio"])
async def test_mcp_workflow(tmp_path: Path, transport: str) -> None:
    author(tmp_path)
    server = (
        create_server(open_service(tmp_path))
        if transport == "inprocess"
        else StdioServerParameters(
            command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(tmp_path)]
        )
    )
    async with Client(server, read_timeout_seconds=10) as client:
        assert client.protocol_version == "2026-07-28"
        listed = await client.list_tools()
        assert {t.name for t in listed.tools} == {
            "index_model",
            "get_graph_schema",
            "search_graph",
            "query_graph",
            "trace_path",
            "apply_changes",
            "detect_changes",
            "get_assessments",
            "compare_graphs",
            "submit_assessment",
        }
        indexed = await client.call_tool("index_model", {})
        assert not indexed.is_error, indexed
        assert indexed.structured_content["revision"] == 1
        listed = await client.list_tools(cache_mode="refresh")
        apply_schema = next(t for t in listed.tools if t.name == "apply_changes").input_schema
        assert '"const": "Thing"' in json.dumps(apply_schema)
        cases = [
            (
                {
                    "expected_revision": 1,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": "b",
                            "type": "Thing",
                            "properties": {"label": 7},
                        }
                    ],
                },
                True,
            ),
            ({"expected_revision": 0, "changes": [{"op": "delete_node", "id": "b"}]}, True),
            (
                {
                    "expected_revision": 1,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": "b",
                            "type": "Thing",
                            "properties": {"label": "updated"},
                        }
                    ],
                },
                False,
            ),
        ]
        for arguments, error in cases:
            result = await client.call_tool("apply_changes", arguments)
            assert result.is_error is error, result
        queried = await client.call_tool("query_graph", {"where": {"label": "updated"}})
        assert [n["id"] for n in queried.structured_content["nodes"]] == ["b"]
        unsafe = await client.call_tool("query_graph", {"sql": "DROP TABLE nodes"})
        assert unsafe.is_error
        resource = await client.read_resource("graph://model/impact/2")
        assert {i["node_id"] for i in json.loads(resource.contents[0].text)["impact"]} == {"a", "b"}
        pending = await client.call_tool("get_assessments", {})
        assert len(pending.structured_content["assessments"]) == 2
        result = await client.call_tool(
            "submit_assessment",
            {
                "revision": 2,
                "target_id": "a",
                "interceptor_id": "check",
                "result": {"status": "pass", "findings": [], "evidence": []},
            },
        )
        assert result.is_error
        result = await client.call_tool(
            "submit_assessment",
            {
                "revision": 2,
                "target_id": "a",
                "interceptor_id": "check",
                "result": {
                    "status": "pass",
                    "findings": [],
                    "evidence": [{"obligation": "proof", "uri": "urn:test:proof"}],
                },
            },
        )
        assert not result.is_error, result


async def test_subscriptions_schema_refresh_and_filtered_resources(tmp_path: Path) -> None:
    source = author(tmp_path)
    server = create_server(open_service(tmp_path), subscriptions=True)
    async with Client(server, read_timeout_seconds=10) as client:
        async with client.listen(
            tools_list_changed=True, resource_subscriptions=["graph://model/schema"]
        ) as subscription:
            assert subscription.honored.tools_list_changed
            result = await client.call_tool("index_model", {})
            assert not result.is_error, result
            events = [await asyncio.wait_for(anext(subscription), 2) for _ in range(2)]
            assert any(isinstance(e, ToolsListChanged) for e in events)
            assert any(
                isinstance(e, ResourceUpdated) and e.uri == "graph://model/schema" for e in events
            )
            changed = json.loads(source.read_text())
            changed["schema"]["node_types"]["Other"] = {"type": "object"}
            source.write_text(json.dumps(changed))
            result = await client.call_tool("index_model", {})
            assert not result.is_error, result
            events = [await asyncio.wait_for(anext(subscription), 2) for _ in range(2)]
            assert all(
                isinstance(e, ToolsListChanged) or e.uri == "graph://model/schema" for e in events
            )
            listed = await client.list_tools(cache_mode="refresh")
            assert '"const": "Other"' in json.dumps(
                next(t.input_schema for t in listed.tools if t.name == "apply_changes")
            )


@pytest.mark.parametrize(
    "mode,expected",
    [("pass", "pass"), ("missing_evidence", "indeterminate"), ("timeout", "indeterminate")],
)
async def test_external_handler_real_transport(tmp_path: Path, mode: str, expected: str) -> None:
    from typed_graph.adapters.external_handlers import ExternalHandlers

    author(tmp_path, handler="external")
    handlers = ExternalHandlers(
        {
            "external": {
                "command": sys.executable,
                "args": [str(Path(__file__).parent / "fixtures" / "handler_server.py"), mode],
                "tool": "assess",
                "timeout": 0.6 if mode == "timeout" else 10,
            }
        },
        [sys.executable],
    )
    async with Client(
        create_server(open_service(tmp_path), handlers=handlers), read_timeout_seconds=20
    ) as client:
        indexed = await client.call_tool("index_model", {})
        assert not indexed.is_error, indexed
        assessments = (await client.call_tool("get_assessments", {})).structured_content[
            "assessments"
        ]
        assert len(assessments) == 2
        assert all(
            a["result"]["status"] == expected and a["state"] == "completed" for a in assessments
        )
        if expected == "pass":
            assert all(
                a["result"]["evidence"][0]["uri"] == "urn:test:external" for a in assessments
            )


async def test_external_handler_disabled_by_default(tmp_path: Path) -> None:
    author(tmp_path, handler="external")
    async with Client(create_server(open_service(tmp_path))) as client:
        await client.call_tool("index_model", {})
        assessments = (await client.call_tool("get_assessments", {})).structured_content[
            "assessments"
        ]
        assert all(a["state"] == "pending" for a in assessments)


@pytest.mark.parametrize(
    "enabled,uri", [(False, "graph://model/schema"), (True, "file:///etc/passwd")]
)
async def test_subscription_opt_in_and_uri_boundary(
    tmp_path: Path, enabled: bool, uri: str
) -> None:
    author(tmp_path)
    async with Client(
        create_server(open_service(tmp_path), subscriptions=enabled), read_timeout_seconds=2
    ) as client:
        with pytest.raises(MCPError):
            async with client.listen(resource_subscriptions=[uri]):
                pytest.fail("unsupported subscription was accepted")


async def test_subscription_filter_and_reconnect(tmp_path: Path) -> None:
    author(tmp_path)
    async with Client(create_server(open_service(tmp_path), subscriptions=True)) as client:
        await client.call_tool("index_model", {})
        async with client.listen(resource_subscriptions=["graph://model/schema"]) as subscription:
            changed = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": 1,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": "a",
                            "type": "Thing",
                            "properties": {"label": "new"},
                        }
                    ],
                },
            )
            assert not changed.is_error
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(anext(subscription), 0.1)
        async with client.listen(resource_subscriptions=["graph://model/nodes/a"]) as subscription:
            changed = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": 2,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": "a",
                            "type": "Thing",
                            "properties": {"label": "newer"},
                        }
                    ],
                },
            )
            assert not changed.is_error
            event = await asyncio.wait_for(anext(subscription), 2)
            assert isinstance(event, ResourceUpdated) and event.uri == "graph://model/nodes/a"


def test_external_executable_must_be_operator_allowlisted() -> None:
    from typed_graph.adapters.external_handlers import ExternalHandlers

    with pytest.raises(ValueError, match="allowlisted"):
        ExternalHandlers({"external": {"command": sys.executable, "tool": "assess"}}, [])


async def test_pending_handlers_resume_at_startup(tmp_path: Path) -> None:
    from typed_graph.adapters.external_handlers import ExternalHandlers

    author(tmp_path, handler="external")
    original = open_service(tmp_path)
    original.dispatch("index_model", {})
    assert all(
        a["state"] == "pending" for a in original.dispatch("get_assessments", {})["assessments"]
    )
    handlers = ExternalHandlers(
        {
            "external": {
                "command": sys.executable,
                "args": [str(Path(__file__).parent / "fixtures" / "handler_server.py"), "pass"],
                "tool": "assess",
                "timeout": 10,
            }
        },
        [sys.executable],
    )
    async with Client(create_server(open_service(tmp_path), handlers=handlers)) as client:
        assessments = (await client.call_tool("get_assessments", {})).structured_content[
            "assessments"
        ]
        assert all(
            a["state"] == "completed" and a["result"]["status"] == "pass" for a in assessments
        )


async def test_deleted_node_and_historical_assessment_notifications(tmp_path: Path) -> None:
    author(tmp_path)
    async with Client(create_server(open_service(tmp_path), subscriptions=True)) as client:
        await client.call_tool("index_model", {})
        async with client.listen(resource_subscriptions=["graph://model/nodes/b"]) as subscription:
            result = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": 1,
                    "changes": [
                        {"op": "delete_edge", "id": "ab"},
                        {"op": "delete_node", "id": "b"},
                    ],
                },
            )
            assert not result.is_error, result
            event = await asyncio.wait_for(anext(subscription), 2)
            assert isinstance(event, ResourceUpdated) and event.uri == "graph://model/nodes/b"
        async with client.listen(
            resource_subscriptions=["graph://model/assessments/1"]
        ) as subscription:
            result = await client.call_tool(
                "submit_assessment",
                {
                    "revision": 1,
                    "interceptor_id": "check",
                    "target_id": "b",
                    "result": {"status": "fail", "findings": [], "evidence": []},
                },
            )
            assert not result.is_error and result.structured_content["assessment"]["stale"]
            event = await asyncio.wait_for(anext(subscription), 2)
            assert isinstance(event, ResourceUpdated) and event.uri == "graph://model/assessments/1"


async def test_encoded_node_identity_resource_and_notification(tmp_path: Path) -> None:
    author(tmp_path)
    uri = "graph://model/nodes/team%2Fservice"
    async with Client(create_server(open_service(tmp_path), subscriptions=True)) as client:
        await client.call_tool("index_model", {})
        async with client.listen(resource_subscriptions=[uri]) as subscription:
            result = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": 1,
                    "changes": [
                        {
                            "op": "create_node",
                            "node": {
                                "id": "team/service",
                                "type": "Thing",
                                "properties": {"label": "slash"},
                            },
                        }
                    ],
                },
            )
            assert not result.is_error
            event = await asyncio.wait_for(anext(subscription), 2)
            assert isinstance(event, ResourceUpdated) and event.uri == uri
            resource = await client.read_resource(uri)
            assert json.loads(resource.contents[0].text)["node"]["id"] == "team/service"
