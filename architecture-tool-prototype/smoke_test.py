"""Behavioral tests against a real subprocess over MCP stdio."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).with_name("server.py").resolve()
BOUNDARY = dict(
    name="Test system",
    intended_experience="Achieve the desired outcome",
    scope="Core outcome",
    exclusions=["Other outcomes"],
    external_dependencies=[],
    open_questions=[],
)
DECOMPOSITION = dict(
    system_of_interest="Test system",
    systems=[
        dict(
            name="Core",
            responsibility="Deliver outcome",
            boundary="Own core; exclude unrelated concerns",
            independence="Can be realized independently",
        )
    ],
    interfaces=[],
    research_basis=["Assumption: the core can be realized independently."],
    open_questions=[],
)


async def session_run(directory, restart=False):
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(SERVER), "--output-dir", str(directory)]
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            discovery = await session.list_tools()
            assert {t.name for t in discovery.tools} == {
                "define_product_boundary",
                "decompose_system",
            }
            for tool in discovery.tools:
                schema = tool.inputSchema
                assert schema["additionalProperties"] is False
                assert set(schema["required"]) == set(schema["properties"])
                assert all(p.get("description") for p in schema["properties"].values())
            result = await session.call_tool("define_product_boundary", BOUNDARY)
            assert not result.isError
            data = json.loads(result.content[0].text)
            assert data["revision"] == (3 if restart else 1)
            assert data["data"] == BOUNDARY
            if restart:
                return
            result = await session.call_tool("decompose_system", DECOMPOSITION)
            assert not result.isError
            assert json.loads(result.content[0].text)["data"] == DECOMPOSITION
            result = await session.call_tool(
                "define_product_boundary", {**BOUNDARY, "scope": "Revised scope"}
            )
            assert not result.isError and json.loads(result.content[0].text)["revision"] == 2
            for invalid in (
                {**BOUNDARY, "name": 42},
                {**BOUNDARY, "extra": "not allowed"},
                {k: v for k, v in BOUNDARY.items() if k != "scope"},
            ):
                assert (await session.call_tool("define_product_boundary", invalid)).isError
            invalid_nested = {
                **DECOMPOSITION,
                "systems": [{**DECOMPOSITION["systems"][0], "extra": True}],
            }
            assert (await session.call_tool("decompose_system", invalid_nested)).isError


async def main():
    directory = Path(tempfile.mkdtemp(prefix="architecture-smoke-"))
    await session_run(directory)
    await session_run(directory, restart=True)
    events = [json.loads(line) for line in (directory / "calls.jsonl").read_text().splitlines()]
    assert len([e for e in events if e["status"] == "received"]) == 8
    assert len([e for e in events if e["status"] == "persisted"]) == 4
    assert len([e for e in events if e["status"] == "rejected"]) == 4
    assert events[0]["arguments"] == BOUNDARY
    assert (
        json.loads((directory / "define_product_boundary.r0001.json").read_text())["data"]
        == BOUNDARY
    )
    assert (
        json.loads((directory / "define_product_boundary.latest.json").read_text())["revision"] == 3
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": str(directory),
                "checks": [
                    "MCP initialize/discovery",
                    "required described strict schema",
                    "both tool calls",
                    "exact input logging",
                    "revision history",
                    "strict validation rejection",
                    "restart persistence",
                ],
                "real_calls": 8,
                "persisted": 4,
                "rejected": 4,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
