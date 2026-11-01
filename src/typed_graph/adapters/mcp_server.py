"""MCP transport adapter. SDK negotiation is retained; never spoof protocol versions."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from jsonschema.exceptions import ValidationError
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
from typed_graph.application.contracts import (
    DETECT_CHANGES,
    GET_ASSESSMENTS,
    INDEX_MODEL,
    SUBMIT_ASSESSMENT,
    TOOL_CATALOG,
    ApplyRequest,
    AssessmentsResult,
    DetectResult,
    SubmitAssessmentRequest,
    request_schema,
    response_schema,
    validate_request,
    validate_response,
)
from typed_graph.application.service import GraphService
from typed_graph.domain.models import (
    ApplyResult,
    CreateNode,
    DeleteNode,
    GraphSchema,
    JsonObject,
    UpdateNode,
    dump_wire,
)
from typed_graph.domain.resources import ResourceKind, ResourceURI


def tool_schemas(schema: JsonObject) -> dict[str, JsonObject]:
    return {name: request_schema(name, schema) for name in TOOL_CATALOG}


OUTPUT_SCHEMAS = {name: response_schema(name) for name in TOOL_CATALOG}


def create_server(
    service: GraphService, *, subscriptions: bool = False, handlers: ExternalHandlers | None = None
) -> Server[Any]:
    """Bind one workspace; notifications are opt-in and restricted to graph resources."""
    bus = InMemorySubscriptionBus()
    listener = ListenHandler(bus, max_subscriptions=64, max_buffered_events=256)
    lock = asyncio.Lock()

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        catalog = service.tool_catalog
        schema = service.schema
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name,
                    description=name.replace("_", " "),
                    input_schema=request_schema(name, schema, catalog),
                    output_schema=response_schema(name, catalog),
                )
                for name in catalog
            ]
        )

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        async with lock:
            # A disconnect cannot release serialization while a commit/handler is running.
            with anyio.CancelScope(shield=True):
                try:
                    arguments = params.arguments or {}
                    catalog = service.tool_catalog
                    request = validate_request(params.name, arguments, service.schema, catalog)
                    before_schema = json.dumps(service.schema, sort_keys=True)
                    before_revision = service.revision
                    changed_ids: set[str] = set()
                    if params.name == INDEX_MODEL.name:
                        preview_wire = await anyio.to_thread.run_sync(
                            service.dispatch, DETECT_CHANGES.name, {}
                        )
                        preview = DetectResult.model_validate(preview_wire)
                        changed_ids.update(preview.changed_nodes)
                    if isinstance(request, ApplyRequest):
                        for change in request.changes:
                            if isinstance(change, (DeleteNode, UpdateNode)):
                                changed_ids.add(change.id)
                            elif isinstance(change, CreateNode):
                                changed_ids.add(change.node.id)
                    result = await anyio.to_thread.run_sync(
                        service.dispatch, params.name, arguments
                    )
                    response = validate_response(params.name, result, catalog)
                    if handlers and isinstance(response, ApplyResult):
                        await execute_pending(service, handlers)
                    if subscriptions:
                        if before_schema != json.dumps(service.schema, sort_keys=True):
                            await bus.publish(ToolsListChanged())
                            await bus.publish(ResourceUpdated(str(ResourceURI.schema_resource())))
                        if before_revision != service.revision or isinstance(
                            request, SubmitAssessmentRequest
                        ):
                            event_revision = (
                                request.revision
                                if isinstance(request, SubmitAssessmentRequest)
                                else service.revision
                            )
                            kinds = (
                                (ResourceKind.ASSESSMENTS,)
                                if isinstance(request, SubmitAssessmentRequest)
                                else (
                                    ResourceKind.REVISION,
                                    ResourceKind.IMPACT,
                                    ResourceKind.ASSESSMENTS,
                                )
                            )
                            for kind in kinds:
                                await bus.publish(
                                    ResourceUpdated(
                                        str(ResourceURI.revision_resource(kind, event_revision))
                                    )
                                )
                            if isinstance(response, ApplyResult):
                                changed_ids.update(item.node_id for item in response.invalidations)
                            for node_id in sorted(changed_ids):
                                await bus.publish(ResourceUpdated(str(ResourceURI.node(node_id))))
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps(result))],
                        structured_content=result,
                    )
                except (ValueError, KeyError, OSError, ValidationError) as error:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=str(error))], is_error=True
                    )

        raise RuntimeError("MCP request interrupted before result")

    async def read_resource(
        ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        ResourceURI.parse(params.uri)
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
                    name="Graph schema",
                    uri=str(ResourceURI.schema_resource()),
                    mime_type="application/json",
                )
            ]
        )

    async def list_templates(ctx: Any, params: Any) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    name=kind,
                    uri_template=template,
                    mime_type="application/json",
                )
                for kind, template in ResourceURI.templates()
            ]
        )

    async def listen(
        ctx: Any, params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        for uri in params.notifications.resource_subscriptions or []:
            ResourceURI.parse(uri)
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
    pending_wire = await anyio.to_thread.run_sync(service.dispatch, GET_ASSESSMENTS.name, {})
    pending = AssessmentsResult.model_validate(pending_wire)
    definitions = {i.id: i for i in GraphSchema.model_validate(service.schema).interceptors}
    for assessment in pending.assessments:
        handler = definitions[assessment.interceptor_id].handler
        if assessment.state != "pending" or handler not in handlers.handlers:
            continue
        try:
            result = await anyio.to_thread.run_sync(handlers.execute, handler, assessment.context)
            arguments = SubmitAssessmentRequest(
                revision=assessment.revision,
                interceptor_id=assessment.interceptor_id,
                target_id=assessment.target_id,
                result=result,
            )
            await anyio.to_thread.run_sync(
                service.dispatch, SUBMIT_ASSESSMENT.name, dump_wire(arguments)
            )
        except Exception as error:
            await anyio.to_thread.run_sync(
                service.record_handler_failure,
                assessment.revision,
                assessment.interceptor_id,
                assessment.target_id,
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
