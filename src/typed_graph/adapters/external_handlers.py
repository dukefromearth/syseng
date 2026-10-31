"""Explicitly enabled MCP subprocess handlers; no model-selected process invocation.

This is process isolation, NOT an operating-system security sandbox. Operators must
trust allowlisted executables and provision an OS sandbox for untrusted handlers.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from pydantic import Field
from referencing import Registry

from typed_graph.domain.models import (
    AssessmentResult,
    Identifier,
    ImpactContext,
    StrictModel,
    dump_wire,
)


class HandlerConfig(StrictModel):
    command: Identifier
    args: list[str] = Field(default_factory=list)
    tool: Identifier
    timeout: Annotated[int | float, Field(gt=0, le=300)] = 30


class ExternalHandlers:
    """Operator-owned configuration is deliberately separate from graph schema."""

    def __init__(self, handlers: Mapping[str, object], allowed_executables: list[str]) -> None:
        self.handlers = {
            key: HandlerConfig.model_validate(value) for key, value in handlers.items()
        }
        self.allowed = {str(Path(item).resolve(strict=True)) for item in allowed_executables}
        for handler in self.handlers.values():
            command = Path(handler.command)
            if not command.is_absolute() or str(command.resolve(strict=True)) not in self.allowed:
                raise ValueError("Handler executable must be absolute and operator-allowlisted")

    def execute(self, handler_id: str, context: ImpactContext) -> AssessmentResult:
        if handler_id not in self.handlers:
            raise ValueError("External handler is not enabled by the operator")
        config = self.handlers[handler_id]

        async def invoke() -> AssessmentResult:
            async with asyncio.timeout(config.timeout):
                with tempfile.TemporaryDirectory(prefix="typed-graph-handler-") as cwd:
                    params = StdioServerParameters(
                        command=config.command,
                        args=config.args,
                        cwd=cwd,
                        env={"HOME": cwd, "TMPDIR": cwd},
                    )
                    async with Client(params, read_timeout_seconds=config.timeout) as client:
                        listed = await client.list_tools()
                        matches = [tool for tool in listed.tools if tool.name == config.tool]
                        if len(matches) != 1:
                            raise ValueError(
                                "Configured handler tool must be advertised exactly once"
                            )
                        tool = matches[0]
                        arguments = {"context": dump_wire(context)}
                        # An empty registry refuses remote-reference retrieval.
                        Draft202012Validator.check_schema(tool.input_schema)
                        Draft202012Validator(tool.input_schema, registry=Registry()).validate(
                            arguments
                        )
                        result = await client.call_tool(config.tool, arguments)
                        if result.is_error or not isinstance(result.structured_content, dict):
                            raise ValueError("Handler failed or returned no structured result")
                        if tool.output_schema is None:
                            raise ValueError("External handler must advertise an output schema")
                        Draft202012Validator.check_schema(tool.output_schema)
                        Draft202012Validator(tool.output_schema, registry=Registry()).validate(
                            result.structured_content
                        )
                        return AssessmentResult.model_validate(
                            result.structured_content, strict=True
                        )

        return asyncio.run(invoke())
