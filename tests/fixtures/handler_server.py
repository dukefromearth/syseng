"""Real external MCP handler process for integration behavior tests."""

import asyncio
import json
import sys
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server


async def call(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pass"
    if mode == "timeout":
        await asyncio.sleep(10)
    result = {
        "status": "pass",
        "findings": [],
        "evidence": [{"obligation": "proof", "uri": "urn:test:external"}],
    }
    if mode == "missing_evidence":
        result["evidence"] = []
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result))], structured_content=result
    )


async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="assess", input_schema={"type": "object"}, output_schema={"type": "object"}
            )
        ]
    )


async def run() -> None:
    server: Server[Any] = Server("test-handler", on_call_tool=call, on_list_tools=list_tools)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


asyncio.run(run())
