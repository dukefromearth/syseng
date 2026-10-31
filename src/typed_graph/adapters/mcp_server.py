"""MCP transport adapter. SDK negotiation is retained; never spoof protocol versions."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anyio
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    ListenHandler,
    ResourceUpdated,
    ToolsListChanged,
)

from typed_graph.adapters.external_handlers import ExternalHandlers
from typed_graph.adapters.workspace import open_service
from typed_graph.application.service import GraphService
from typed_graph.domain.schema import RESULT_SCHEMA, apply_input_schema

JSON = dict[str, Any]
RESOURCE_PATTERN = re.compile(
    r"graph://model/(?:schema|nodes/[^/]+|(?:revisions|impact|assessments)/[0-9]+)\Z"
)


def object_schema(properties: JSON, required: list[str] | None = None) -> JSON:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def tool_schemas(schema: JSON) -> dict[str, JSON]:
    integer = {"type": "integer", "minimum": 0}
    string = {"type": "string", "minLength": 1}
    limit = {"type": "integer", "minimum": 1, "maximum": 1000}
    result = RESULT_SCHEMA
    return {
        "index_model": object_schema({}),
        "get_graph_schema": object_schema({}),
        "search_graph": object_schema({"text": {"type": "string"}, "type": string, "limit": limit}),
        "query_graph": object_schema({"type": string, "where": {"type": "object"}, "limit": limit}),
        "trace_path": object_schema(
            {
                "source": string,
                "target": string,
                "relation": {"enum": sorted(schema.get("relations", {}))}
                if schema.get("relations")
                else {"type": "string"},
                "mode": {"enum": ["semantic", "dependency"]},
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            ["source", "target"],
        ),
        "apply_changes": apply_input_schema(schema),
        "detect_changes": object_schema({}),
        "get_assessments": object_schema({"revision": integer}),
        "compare_graphs": object_schema(
            {"from_revision": integer, "to_revision": integer}, ["from_revision", "to_revision"]
        ),
        "submit_assessment": object_schema(
            {"revision": integer, "interceptor_id": string, "target_id": string, "result": result},
            ["revision", "interceptor_id", "target_id", "result"],
        ),
    }


REVISION = {"type": "integer", "minimum": 0}
STRINGS = {"type": "array", "items": {"type": "string"}}
NODE = object_schema(
    {"id": {"type": "string"}, "type": {"type": "string"}, "properties": {"type": "object"}},
    ["id", "type", "properties"],
)
IMPACT = object_schema(
    {
        "node_id": {"type": "string"},
        "paths": {"type": "array", "items": STRINGS},
        "triggering_revision": REVISION,
        "component": STRINGS,
        "component_id": {"type": "string"},
    },
    ["node_id", "paths", "triggering_revision"],
)
APPLY_OUTPUT_SCHEMA = object_schema(
    {
        "revision": REVISION,
        "applied_changes": {"type": "array", "items": {"type": "object"}},
        "invalidations": {"type": "array", "items": IMPACT},
    },
    ["revision", "applied_changes", "invalidations"],
)
DIFF = object_schema(
    {"added": STRINGS, "removed": STRINGS, "updated": STRINGS}, ["added", "removed", "updated"]
)
ASSESSMENT = {
    "type": "object",
    "properties": {
        "revision": REVISION,
        "interceptor_id": {"type": "string"},
        "target_id": {"type": "string"},
        "state": {"enum": ["pending", "completed"]},
        "stale": {"type": "boolean"},
        "result": RESULT_SCHEMA,
    },
    "required": ["revision", "interceptor_id", "target_id", "state", "stale", "result"],
}
OUTPUT_SCHEMAS = {
    "index_model": APPLY_OUTPUT_SCHEMA,
    "apply_changes": APPLY_OUTPUT_SCHEMA,
    "get_graph_schema": object_schema(
        {"revision": REVISION, "schema": {"type": "object"}}, ["revision", "schema"]
    ),
    "search_graph": object_schema(
        {"revision": REVISION, "nodes": {"type": "array", "items": NODE}}, ["revision", "nodes"]
    ),
    "query_graph": object_schema(
        {"revision": REVISION, "nodes": {"type": "array", "items": NODE}}, ["revision", "nodes"]
    ),
    "trace_path": object_schema({"revision": REVISION, "path": STRINGS}, ["revision", "path"]),
    "detect_changes": object_schema(
        {"revision": REVISION, "changed_nodes": STRINGS, "schema_changed": {"type": "boolean"}},
        ["revision", "changed_nodes", "schema_changed"],
    ),
    "get_assessments": object_schema(
        {"revision": REVISION, "assessments": {"type": "array", "items": ASSESSMENT}},
        ["revision", "assessments"],
    ),
    "submit_assessment": object_schema({"assessment": ASSESSMENT}, ["assessment"]),
    "compare_graphs": object_schema(
        {
            "from_revision": REVISION,
            "to_revision": REVISION,
            "schema_changed": {"type": "boolean"},
            "nodes": DIFF,
            "edges": DIFF,
        },
        ["from_revision", "to_revision", "schema_changed", "nodes", "edges"],
    ),
}


def create_server(
    service: GraphService, *, subscriptions: bool = False, handlers: ExternalHandlers | None = None
) -> Server[Any]:
    """Bind one workspace; notifications are opt-in and restricted to graph resources."""
    bus = InMemorySubscriptionBus()
    listener = ListenHandler(bus, max_subscriptions=64, max_buffered_events=256)
    lock = asyncio.Lock()

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name,
                    description=name.replace("_", " "),
                    input_schema=inputs,
                    output_schema=OUTPUT_SCHEMAS[name],
                )
                for name, inputs in tool_schemas(service.schema).items()
            ]
        )

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        async with lock:
            # A disconnect cannot release serialization while a commit/handler is running.
            with anyio.CancelScope(shield=True):
                try:
                    schemas = tool_schemas(service.schema)
                    if params.name not in schemas:
                        raise ValueError("Unknown tool")
                    arguments = params.arguments or {}
                    Draft202012Validator(schemas[params.name]).validate(arguments)
                    before_schema = json.dumps(service.schema, sort_keys=True)
                    before_revision = service.revision
                    changed_ids: set[str] = set()
                    if params.name == "index_model":
                        preview = await anyio.to_thread.run_sync(
                            service.dispatch, "detect_changes", {}
                        )
                        changed_ids.update(preview["changed_nodes"])
                    if params.name == "apply_changes":
                        for change in arguments["changes"]:
                            if change["op"] in {"delete_node", "update_node"}:
                                changed_ids.add(change["id"])
                            elif change["op"] == "create_node":
                                changed_ids.add(change["node"]["id"])
                    result = await anyio.to_thread.run_sync(
                        service.dispatch, params.name, arguments
                    )
                    if handlers and params.name in {"index_model", "apply_changes"}:
                        await execute_pending(service, handlers)
                    output_schema = OUTPUT_SCHEMAS[params.name]
                    Draft202012Validator(output_schema).validate(result)
                    if subscriptions:
                        if before_schema != json.dumps(service.schema, sort_keys=True):
                            await bus.publish(ToolsListChanged())
                            await bus.publish(ResourceUpdated("graph://model/schema"))
                        if (
                            before_revision != service.revision
                            or params.name == "submit_assessment"
                        ):
                            event_revision = arguments.get("revision", service.revision)
                            for segment in (
                                ("assessments",)
                                if params.name == "submit_assessment"
                                else ("revisions", "impact", "assessments")
                            ):
                                await bus.publish(
                                    ResourceUpdated(f"graph://model/{segment}/{event_revision}")
                                )
                            changed_ids.update(
                                item["node_id"] for item in result.get("invalidations", [])
                            )
                            for node_id in sorted(changed_ids):
                                await bus.publish(
                                    ResourceUpdated(
                                        f"graph://model/nodes/{quote(node_id, safe='')}"
                                    )
                                )
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps(result))],
                        structured_content=result,
                    )
                except (ValueError, KeyError, OSError) as error:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=str(error))], is_error=True
                    )
                except Exception as error:
                    # Schema errors are domain diagnostics, not transport failures.
                    from jsonschema.exceptions import ValidationError

                    if isinstance(error, ValidationError):
                        return types.CallToolResult(
                            content=[types.TextContent(type="text", text=error.message)],
                            is_error=True,
                        )
                    raise

        raise RuntimeError("MCP request interrupted before result")

    async def read_resource(
        ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        if not RESOURCE_PATTERN.fullmatch(params.uri):
            raise ValueError("Unknown graph resource")
        async with lock:
            result = await anyio.to_thread.run_sync(service.resource, params.uri)
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=params.uri, mime_type="application/json", text=json.dumps(result)
                )
            ]
        )

    async def list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    name="Graph schema", uri="graph://model/schema", mime_type="application/json"
                )
            ]
        )

    async def list_templates(ctx: Any, params: Any) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    name=kind,
                    uri_template=f"graph://model/{kind}/{{{parameter}}}",
                    mime_type="application/json",
                )
                for kind, parameter in [
                    ("nodes", "id"),
                    ("revisions", "revision"),
                    ("impact", "revision"),
                    ("assessments", "revision"),
                ]
            ]
        )

    async def listen(
        ctx: Any, params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        for uri in params.notifications.resource_subscriptions or []:
            if not RESOURCE_PATTERN.fullmatch(uri):
                raise ValueError("Only graph resource subscriptions are permitted")
        return await listener(ctx, params)

    @asynccontextmanager
    async def lifespan(server: Server[Any]) -> AsyncIterator[None]:
        try:
            if handlers:
                await execute_pending(service, handlers)
            yield
        finally:
            listener.close()

    return Server(
        "typed-reactive-graph",
        lifespan=lifespan,
        version="0.1.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_read_resource=read_resource,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        on_subscriptions_listen=listen if subscriptions else None,
    )


async def execute_pending(service: GraphService, handlers: ExternalHandlers) -> None:
    pending = (await anyio.to_thread.run_sync(service.dispatch, "get_assessments", {}))[
        "assessments"
    ]
    definitions = {i["id"]: i for i in service.schema.get("interceptors", [])}
    for assessment in pending:
        handler = definitions[assessment["interceptor_id"]]["handler"]
        if assessment["state"] != "pending" or handler not in handlers.handlers:
            continue
        arguments = {key: assessment[key] for key in ("revision", "interceptor_id", "target_id")}
        try:
            arguments["result"] = await anyio.to_thread.run_sync(
                handlers.execute, handler, assessment["context"]
            )
            await anyio.to_thread.run_sync(service.dispatch, "submit_assessment", arguments)
        except Exception as error:
            await anyio.to_thread.run_sync(
                service.record_handler_failure,
                assessment["revision"],
                assessment["interceptor_id"],
                assessment["target_id"],
                f"Handler failed: {type(error).__name__}",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--subscriptions", action="store_true")
    parser.add_argument(
        "--handlers", type=Path, help="Trusted operator JSON: handlers and allowed_executables"
    )
    args = parser.parse_args()
    service = open_service(args.workspace)
    handlers = None
    if args.handlers:
        config = json.loads(args.handlers.read_text())
        handlers = ExternalHandlers(config["handlers"], config["allowed_executables"])
    server = create_server(service, subscriptions=args.subscriptions, handlers=handlers)

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
