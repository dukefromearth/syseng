"""Independent HTTP reader against a real separate MCP writer process."""

import asyncio
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


async def test_reader_crossprocess(tmp_path: Path) -> None:
    w = tmp_path
    (w / "model").mkdir()
    node_type = "Custom Ω | <img onerror=alert(1)>"
    evil = (
        "<script>alert(1)</script>"
        "\n\n[bad](javascript:alert(1)) ![track](https://evil.example/pixel)"
        "\n\n## Authored section\n\n| One | Two |\n| --- | --- |\n| yes | **bold** |"
    )
    props = {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "odd|field": {"type": "string"},
    }
    model = {
        "schema": {
            "version": "1",
            "node_types": {
                node_type: {
                    "type": "object",
                    "properties": props,
                    "additionalProperties": False,
                }
            },
            "relations": {},
            "interceptors": [
                {
                    "id": "proofcheck",
                    "target_type": node_type,
                    "handler": "pending",
                    "version": "1",
                    "trigger": "dependency_changed",
                    "evidence_required": ["proof"],
                }
            ],
        },
        "nodes": [
            {
                "id": 'a / Ω #"',
                "type": node_type,
                "properties": {
                    "title": "Hello [bad](javascript:alert(1))",
                    "body": evil,
                    "odd|field": "a | b ` `` <script>",
                },
            }
        ],
        "edges": [],
    }
    (w / "model" / "graph.json").write_text(json.dumps(model))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    base = f"http://127.0.0.1:{port}"
    stream_socket = None
    log = (w / "reader.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "typed_graph.adapters.spec_server", str(w), "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )

    def get(path="/api/specification", headers=None):
        with urllib.request.urlopen(
            urllib.request.Request(base + path, headers=headers or {}), timeout=4
        ) as r:
            return r.status, r.read(), r.headers

    def spec():
        return json.loads(get()[1])

    def wait_state(predicate):
        end = time.monotonic() + 6
        while time.monotonic() < end:
            value = spec()
            if predicate(value):
                return value
            time.sleep(0.1)
        raise AssertionError("reader did not reach desired state")

    try:
        for _ in range(70):
            try:
                initial = spec()
                break
            except Exception:
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("server failed " + (w / "reader.log").read_text())
        q = queue.Queue()
        stop = threading.Event()
        stream_socket = socket.create_connection(("127.0.0.1", port), timeout=20)
        stream_socket.sendall(
            (
                f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            ).encode()
        )

        def listen():
            try:
                with stream_socket.makefile("rb") as r:
                    while not stop.is_set():
                        line = r.readline().decode()
                        if not line:
                            break
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            if "state_digest" in event:
                                q.put(event)
            except Exception as e:
                q.put(e)

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        assert q.get(timeout=3)["state_digest"] == initial["state_digest"]
        async with Client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "typed_graph.adapters.mcp_server", str(w)],
                env=env,
            ),
            read_timeout_seconds=10,
        ) as client:

            async def call(name, args):
                result = await client.call_tool(name, args)
                assert not result.is_error, result
                return result.structured_content

            indexed = await call("index_model", {})
            r = indexed["revision"]
            a = wait_state(lambda x: x["revision"] == r)
            event = q.get(timeout=3)
            assert event["state_digest"] == a["state_digest"]
            assert a["node_count"] == 1 and "Custom" in a["markdown"]
            assert (
                "<script>" not in a["html"]
                and 'href="javascript:' not in a["html"]
                and "<img" not in a["html"]
            )
            assert "<table>" in a["html"] and "<strong>bold</strong>" in a["html"]
            assert get("/specification.md")[1].decode() == a["markdown"]
            anchors = {e["id"] for e in a["outline"]}
            assert all('id="' + anchor + '"' in a["html"] for anchor in anchors)
            update = {
                "expected_revision": r,
                "changes": [
                    {
                        "op": "update_node",
                        "id": model["nodes"][0]["id"],
                        "type": node_type,
                        "properties": {**model["nodes"][0]["properties"], "title": "New title"},
                    }
                ],
            }
            mutation = await call("apply_changes", update)
            r = mutation["revision"]
            b = wait_state(lambda x: x["revision"] == r)
            event = q.get(timeout=3)
            assert event["state_digest"] == b["state_digest"]
            assert anchors == {e["id"] for e in b["outline"]}
            invalid = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": r,
                    "changes": [
                        {
                            "op": "update_node",
                            "id": model["nodes"][0]["id"],
                            "type": node_type,
                            "properties": {"title": 1},
                        }
                    ],
                },
            )
            assert invalid.is_error
            await call("apply_changes", {**update, "expected_revision": r})
            await asyncio.sleep(1.5)
            assert spec()["state_digest"] == b["state_digest"]
            assert q.empty()
            await call(
                "submit_assessment",
                {
                    "revision": r,
                    "target_id": model["nodes"][0]["id"],
                    "interceptor_id": "proofcheck",
                    "result": {
                        "status": "pass",
                        "findings": [],
                        "evidence": [{"obligation": "proof", "uri": "javascript:alert(1)"}],
                    },
                },
            )
            c = wait_state(lambda x: x["state_digest"] != b["state_digest"])
            assert c["revision"] == r and c["assessment_digest"] != b["assessment_digest"]
            assert q.get(timeout=3)["state_digest"] == c["state_digest"]
            assert 'href="javascript:' not in c["html"]
            with urllib.request.urlopen(
                urllib.request.Request(
                    base + "/events", headers={"Last-Event-ID": initial["state_digest"]}
                ),
                timeout=3,
            ) as response:
                for line in response:
                    if line.startswith(b"data: "):
                        assert json.loads(line[6:])["state_digest"] == c["state_digest"]
                        break
        for path, headers, expected in [
            ("/", {"Host": "evil.example"}, 403),
            ("/", {"Host": "["}, 403),
            ("/", {"Host": "127.0.0.1:bad"}, 403),
            ("/", {"Host": "127.0.0.1/path"}, 403),
            ("/api/specification", {"Origin": "https://evil.example"}, 403),
            ("/api/specification", {"Origin": base}, 200),
            ("/../../etc/passwd", {}, 404),
            ("/?path=/etc/passwd", {}, 200),
        ]:
            try:
                status, body, h = get(path, headers)
            except urllib.error.HTTPError as e:
                status = e.code
            assert status == expected, (path, headers, status)
        req = urllib.request.Request(base + "/api/specification", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("POST accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 405
    finally:
        if stream_socket is not None:
            stop.set()
            stream_socket.shutdown(socket.SHUT_RDWR)
            stream_socket.close()
            thread.join(timeout=3)
        log.close()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise


def test_reader_shutdown_with_open_and_disconnected_streams(tmp_path: Path) -> None:
    """CLI termination remains bounded even when a browser leaves its SSE stream open."""
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    log = (tmp_path / "reader.log").open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "typed_graph.adapters.spec_server",
            str(tmp_path),
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    stream = None
    try:
        for _ in range(70):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/specification", timeout=1
                ):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise AssertionError((tmp_path / "reader.log").read_text())
        request = (
            f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        ).encode()
        for _ in range(24):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
                client.sendall(request)
                assert b"200 OK" in client.recv(1024)
        stream = socket.create_connection(("127.0.0.1", port), timeout=3)
        stream.sendall(request)
        assert b"200 OK" in stream.recv(1024)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/specification", timeout=3
        ) as result:
            assert result.status == 200
        process.terminate()
        process.wait(timeout=6)
    finally:
        if stream is not None:
            stream.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        log.close()
