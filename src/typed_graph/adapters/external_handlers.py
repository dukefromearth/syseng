"""Explicitly enabled MCP subprocess handlers; no model-selected process invocation.

This is process isolation, NOT an operating-system security sandbox. Operators must
trust allowlisted executables and provision an OS sandbox for untrusted handlers.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from referencing import Registry


class ExternalHandlers:
    """Operator-owned configuration is deliberately separate from graph schema."""

    def __init__(self, handlers: dict[str, Any], allowed_executables: list[str]) -> None:
        self.handlers = handlers
        self.allowed = {str(Path(item).resolve(strict=True)) for item in allowed_executables}
        for handler in handlers.values():
            command = Path(handler["command"])
            if not command.is_absolute() or str(command.resolve(strict=True)) not in self.allowed:
                raise ValueError("Handler executable must be absolute and operator-allowlisted")
            if not isinstance(handler.get("tool"), str):
                raise ValueError("Handler tool name is required")
            timeout = handler.get("timeout", 30)
            if not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
                raise ValueError("Handler timeout must be within (0, 300] seconds")

    def execute(self, handler_id: str, context: dict[str, Any]) -> dict[str, Any]:
        if handler_id not in self.handlers:
            raise ValueError("External handler is not enabled by the operator")
        config = self.handlers[handler_id]

        async def invoke() -> dict[str, Any]:
            async with asyncio.timeout(config.get("timeout", 30)):
                with tempfile.TemporaryDirectory(prefix="typed-graph-handler-") as cwd:
                    params = StdioServerParameters(
                        command=config["command"],
                        args=config.get("args", []),
                        cwd=cwd,
                        env={"HOME": cwd, "TMPDIR": cwd},
                    )
                    async with Client(
                        params, read_timeout_seconds=config.get("timeout", 30)
                    ) as client:
                        listed = await client.list_tools()
                        matches = [tool for tool in listed.tools if tool.name == config["tool"]]
                        if len(matches) != 1:
                            raise ValueError(
                                "Configured handler tool must be advertised exactly once"
                            )
                        tool = matches[0]
                        arguments = {"context": context}
                        # An empty registry refuses remote-reference retrieval.
                        Draft202012Validator.check_schema(tool.input_schema)
                        Draft202012Validator(tool.input_schema, registry=Registry()).validate(
                            arguments
                        )
                        result = await client.call_tool(config["tool"], arguments)
                        if result.is_error or not isinstance(result.structured_content, dict):
                            raise ValueError("Handler failed or returned no structured result")
                        if tool.output_schema is None:
                            raise ValueError("External handler must advertise an output schema")
                        Draft202012Validator.check_schema(tool.output_schema)
                        Draft202012Validator(tool.output_schema, registry=Registry()).validate(
                            result.structured_content
                        )
                        return result.structured_content

        return asyncio.run(invoke())
