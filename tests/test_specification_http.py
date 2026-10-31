"""Real loopback HTTP/SSE behavior against independently committed authored workspaces."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from typed_graph.adapters.workspace import open_service
from typed_graph.application.service import GraphService


def author_reader_model(workspace: Path) -> GraphService:
    (workspace / "model").mkdir()
    (workspace / "model" / "spec.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {
                        "Document": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "body": {"type": "string"}},
                            "required": ["name", "body"],
                            "additionalProperties": False,
                        }
                    },
                    "relations": {},
                    "interceptors": [
                        {
                            "id": "review",
                            "target_type": "Document",
                            "handler": "pending",
                            "version": "1",
                            "trigger": "dependency_changed",
                            "evidence_required": ["proof"],
                        }
                    ],
                },
                "nodes": [
                    {
                        "id": "doc",
                        "type": "Document",
                        "properties": {
                            "name": "Reader example",
                            "body": (
                                "A **living** specification.\n\n## Authored heading\n\n"
                                "<script>window.pwned=true</script>\n\n"
                                "![tracking pixel](https://example.invalid/pixel)\n\n"
                                "[unsafe](javascript:alert(1))"
                            ),
                        },
                    }
                ],
                "edges": [],
            }
        )
    )
    service = open_service(workspace)
    service.dispatch("index_model", {})
    return service


@pytest_asyncio.fixture
async def reader(
    tmp_path: Path,
) -> AsyncIterator[tuple[str, GraphService, Path, subprocess.Popen[bytes]]]:
    service = author_reader_model(tmp_path)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "typed_graph.adapters.spec_server",
                str(tmp_path),
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            async with httpx2.AsyncClient(trust_env=False, timeout=2) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        pytest.fail((tmp_path / "server.log").read_text())
                    try:
                        if (await client.get(base + "/api/specification")).status_code == 200:
                            break
                    except httpx2.ConnectError:
                        pass
                    await asyncio.sleep(0.05)
                else:
                    pytest.fail("Reader did not become ready")
            yield base, service, tmp_path, process
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            service.store.close()


async def next_event(lines: AsyncIterator[str], wanted: str) -> dict[str, Any]:
    event = ""
    data = ""
    async with asyncio.timeout(5):
        async for line in lines:
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
            elif line == "" and data:
                if event == wanted:
                    return json.loads(data)
                event, data = "", ""
    raise AssertionError("SSE stream ended without expected event")


async def test_reader_assets_projection_sanitization_and_read_only_boundary(
    reader: tuple[str, GraphService, Path, subprocess.Popen[bytes]],
) -> None:
    base, _, _, _ = reader
    async with httpx2.AsyncClient(trust_env=False, base_url=base) as client:
        page = await client.get("/")
        assert page.status_code == 200 and 'id="outline"' in page.text
        assert "img-src 'none'" in page.headers["content-security-policy"]
        assert (await client.get("/app.js")).status_code == 200
        assert (await client.get("/styles.css")).status_code == 200
        spec = (await client.get("/api/specification")).json()
        assert spec["revision"] == 1 and spec["node_count"] == 1
        assert "<strong>living</strong>" in spec["html"]
        assert "<script" not in spec["html"] and "<img" not in spec["html"]
        assert "tracking pixel" in spec["html"] and 'href="javascript:' not in spec["html"]
        assert all(f'id="{entry["id"]}"' in spec["html"] for entry in spec["outline"])
        downloaded = await client.get("/specification.md")
        assert downloaded.text == spec["markdown"]
        assert "attachment" in downloaded.headers["content-disposition"]
        assert (await client.post("/api/specification", json={})).status_code == 405
        assert (await client.get("/.graph/manifest.json")).status_code == 404
        for host in ("evil.example", "localhost:bad", "localhost/path", "[broken"):
            assert (await client.get("/", headers={"Host": host})).status_code == 403
        assert (
            await client.get("/", headers={"Origin": "https://evil.example"})
        ).status_code == 403


async def test_sse_cross_process_revision_assessment_noop_and_reconnect(
    reader: tuple[str, GraphService, Path, subprocess.Popen[bytes]],
) -> None:
    base, _, workspace, _ = reader

    async def mcp_write(name: str, arguments: dict[str, Any]) -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(workspace)]
        )
        async with Client(params) as client:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result

    async with httpx2.AsyncClient(trust_env=False, base_url=base, timeout=7) as client:
        async with client.stream("GET", "/events") as stream:
            lines = stream.aiter_lines()
            original = await next_event(lines, "specification")
            await mcp_write(
                "apply_changes",
                {
                    "expected_revision": 1,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": "doc",
                            "type": "Document",
                            "properties": {
                                "name": "Updated reader",
                                "body": "Updated through the canonical graph service.",
                            },
                        }
                    ],
                },
            )
            updated = await next_event(lines, "specification")
            assert updated["revision"] == 2 and "Updated reader" in updated["html"]
            assert original["state_digest"] != updated["state_digest"]
            await mcp_write(
                "submit_assessment",
                {
                    "revision": 2,
                    "interceptor_id": "review",
                    "target_id": "doc",
                    "result": {
                        "status": "pass",
                        "findings": [],
                        "evidence": [{"obligation": "proof", "uri": "urn:proof"}],
                    },
                },
            )
            assessed = await next_event(lines, "specification")
            assert assessed["revision"] == 2
            assert assessed["assessment_digest"] != updated["assessment_digest"]
            assert "pass" in assessed["markdown"]
            await mcp_write("apply_changes", {"expected_revision": 2, "changes": []})
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(1.3):
                    await next_event(lines, "specification")
        async with client.stream(
            "GET", "/events", headers={"Last-Event-ID": original["state_digest"]}
        ) as stream:
            recovered = await next_event(stream.aiter_lines(), "specification")
            assert recovered["state_digest"] == assessed["state_digest"]


async def test_reader_recovers_from_transient_source_unavailability(
    reader: tuple[str, GraphService, Path, subprocess.Popen[bytes]],
) -> None:
    base, _, workspace, _ = reader
    manifest = workspace / ".graph" / "manifest.json"
    async with httpx2.AsyncClient(trust_env=False, base_url=base, timeout=7) as client:
        async with client.stream("GET", "/events") as stream:
            lines = stream.aiter_lines()
            initial = await next_event(lines, "specification")
            assert (await next_event(lines, "reader-status"))["state"] == "live"
            saved = manifest.read_bytes()
            manifest.write_text("not valid json")
            try:
                failure = await next_event(lines, "reader-status")
                assert failure["state"] == "error"
                assert (await client.get("/api/specification")).json()["state_digest"] == initial[
                    "state_digest"
                ]
            finally:
                manifest.write_bytes(saved)
            recovered = await next_event(lines, "reader-status")
            assert recovered["state"] == "live"


async def test_shutdown_is_bounded_with_live_sse(
    reader: tuple[str, GraphService, Path, subprocess.Popen[bytes]],
) -> None:
    base, _, workspace, process = reader
    async with httpx2.AsyncClient(trust_env=False, base_url=base, timeout=7) as client:
        async with client.stream("GET", "/events") as stream:
            lines = stream.aiter_lines()
            await next_event(lines, "specification")
            process.terminate()
            await asyncio.to_thread(process.wait, timeout=4)
            assert process.returncode in (0, -15)
            assert "Application shutdown complete" in (workspace / "server.log").read_text()
