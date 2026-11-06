"""Thin bridge: discovers/invokes the real MCP server through stdio."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "call"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("arguments", nargs="?", help="JSON object; omit or use '-' to read stdin")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).with_name("experiment-output")
    )
    args = parser.parse_args()
    if args.action == "call" and not args.name:
        parser.error("call requires a tool name")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            str(Path(__file__).with_name("server.py").resolve()),
            "--output-dir",
            str(args.output_dir.resolve()),
        ],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if args.action == "list":
                result = await session.list_tools()
            else:
                arguments = json.loads(
                    sys.stdin.read() if args.arguments in (None, "-") else args.arguments
                )
                if not isinstance(arguments, dict):
                    parser.error("arguments must be a JSON object")
                result = await session.call_tool(args.name, arguments)
            print(result.model_dump_json(indent=2, exclude_none=True))
            if getattr(result, "isError", False):
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
