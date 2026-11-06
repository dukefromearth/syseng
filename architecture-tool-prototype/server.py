"""Small local stdio MCP server. No model invocation or implicit design advice."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ProductBoundary(StrictModel):
    name: str = Field(description="Name of the system of interest")
    intended_experience: str = Field(description="Desired outcome in solution-independent terms")
    scope: str = Field(description="What is within the product boundary")
    exclusions: list[str] = Field(description="What is outside the product boundary")
    external_dependencies: list[str] = Field(
        description="External systems or environmental dependencies"
    )
    open_questions: list[str] = Field(
        description="Unresolved questions affecting the product boundary"
    )


class ConstituentSystem(StrictModel):
    name: str = Field(description="Constituent system identity")
    responsibility: str = Field(description="Cohesive responsibility")
    boundary: str = Field(description="Owned and excluded concerns")
    independence: str = Field(description="Rationale for independent realization")


class Interface(StrictModel):
    source: str = Field(description="Source system name")
    target: str = Field(description="Target system name")
    exchange: str = Field(description="Information, material, or energy exchanged")


class SystemDecomposition(StrictModel):
    system_of_interest: str = Field(description="Name of the product or system being decomposed")
    systems: list[ConstituentSystem] = Field(
        description="Independently realizable constituent systems"
    )
    interfaces: list[Interface] = Field(description="Interfaces between systems")
    research_basis: list[str] = Field(
        description=(
            "Findings supporting the decomposition; distinguish assumptions from established "
            "knowledge and do not fabricate sources"
        )
    )
    open_questions: list[str] = Field(
        description="Unresolved questions that could change the decomposition"
    )


DEFINITIONS = {
    "define_product_boundary": (
        ProductBoundary,
        "Define the system of interest, intended experience, and product boundary "
        "for conceptual design.",
    ),
    "decompose_system": (
        SystemDecomposition,
        "Research and propose a conceptual architecture for the system of interest through "
        "system decomposition, separation of concerns, high cohesion, and loose coupling. "
        "Identify independently realizable constituent systems and their interfaces.",
    ),
}


def build_server(output_dir: Path) -> Server:
    output_dir.mkdir(parents=True, exist_ok=True)
    server = Server("architecture-tool-prototype")
    lock = asyncio.Lock()

    def log(event):
        with (output_dir / "calls.jsonl").open("a") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name=name, description=description, inputSchema=model.model_json_schema())
            for name, (model, description) in DEFINITIONS.items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        async with lock:
            event = {
                "call_id": str(uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
                "tool": name,
                "arguments": arguments,
            }
            log({**event, "status": "received"})
            try:
                if name not in DEFINITIONS:
                    raise ValueError(f"Unknown tool: {name}")
                model = DEFINITIONS[name][0].model_validate(arguments)
                latest = output_dir / f"{name}.latest.json"
                revision = json.loads(latest.read_text())["revision"] + 1 if latest.exists() else 1
                result = {
                    "tool": name,
                    "revision": revision,
                    "call_id": event["call_id"],
                    "timestamp": event["timestamp"],
                    "data": model.model_dump(),
                }
                revision_path = output_dir / f"{name}.r{revision:04d}.json"
                revision_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                latest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                log(
                    {
                        **event,
                        "status": "persisted",
                        "revision": revision,
                        "result_path": str(revision_path),
                    }
                )
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                    structuredContent=result,
                )
            except (ValidationError, ValueError) as exc:
                log({**event, "status": "rejected", "error": str(exc)})
                return CallToolResult(
                    isError=True, content=[TextContent(type="text", text=str(exc))]
                )

    return server


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    server = build_server(args.output_dir.resolve())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
