"""Public behavioral contracts for canonical meaning authoring and coherent compilation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client

from typed_graph.adapters.spec_server import render_specification
from typed_graph.adapters.workspace import WorkspaceRepository
from typed_graph.architecture.compiler import compile_architecture
from typed_graph.architecture.models import PACKAGE_VERSION, Role
from typed_graph.domain.models import dump_wire


async def test_platform_semantic_tools_compile_without_layout_and_preserve_single_source(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    example = root / "examples" / "presentation_transformation"
    workspace = tmp_path / "platform"
    process = subprocess.run(
        [sys.executable, str(example / "author.py"), str(workspace)],
        text=True,
        capture_output=True,
        check=True,
        timeout=240,
    )
    receipt = json.loads(process.stdout)
    authored = json.loads((example / "source.json").read_text())
    transcript = json.loads((workspace / "mcp-transcript.json").read_text())
    assert receipt["revision"] > 2
    assert receipt["nodes"] == len(authored["nodes"])
    assert receipt["edges"] == len(authored["edges"])
    assert receipt["completed_assessments"] == 0
    assert receipt["implementation_or_performance_proven"] is False
    assert receipt["semantic_tool_calls"] > 5
    assert {
        "define_concept",
        "define_system",
        "add_layer",
        "define_boundary",
        "propose_binding",
    } <= {item["tool"] for item in transcript}
    assert len(receipt["rejected_fallacies"]) >= 10
    assert sum(call["is_error"] for call in transcript) == len(receipt["rejected_fallacies"])
    assert authored["schema"]["version"] == PACKAGE_VERSION
    assert not (example / "presentation.json").exists()
    assert not any(node["type"].startswith("spec.") for node in authored["nodes"])
    assert all(
        not {"section", "order", "status"} & node["properties"].keys() for node in authored["nodes"]
    )
    repository = WorkspaceRepository(workspace)
    try:
        state = repository.specification_state()
        assert sorted(
            [dump_wire(node) for node in state.snapshot.nodes], key=lambda n: n["id"]
        ) == sorted(authored["nodes"], key=lambda n: n["id"])
        assert sorted(
            [dump_wire(edge) for edge in state.snapshot.edges], key=lambda e: e["id"]
        ) == sorted(authored["edges"], key=lambda e: e["id"])
        assert len([node for node in state.snapshot.nodes if node.type == Role.SYSTEM]) == 4
        assert len([node for node in state.snapshot.nodes if node.type == Role.BINDING]) == 6
        assert all(
            node.properties["version"] == "1.0"
            for node in state.snapshot.nodes
            if node.type in {Role.MODEL, Role.CONTRACT, Role.EXCHANGE}
        )
        assert all(
            item.result.status == "indeterminate" and not item.result.evidence
            for item in state.assessments
        )
        by_id = {node["id"]: node for node in authored["nodes"]}
        assert by_id["phone-feed"]["properties"]["scope"] == "future"
        assert by_id["phase-7"]["properties"]["scope"] == "future"
        assert by_id["P9"]["properties"]["priority"] == "future"
        rendered = render_specification(compile_architecture(state))
        assert rendered.title == "Presentation Transformation Platform"
        for fact in (
            "0.5 ms",
            "7.8 ms",
            "120 FPS",
            "candidate",
            "indeterminate",
            "Counterfactual",
            "phone",
            "Performance",
        ):
            assert fact in rendered.html
        headings = [entry.label for entry in rendered.outline if entry.level == 2]
        assert headings[:7] == [
            "1. Unified metamodel",
            "2. Domain ontology",
            "3. System ontology",
            "4. Realization ontology",
            "5. Cross-model relationships",
            "6. Demonstrating independence",
            "7. Model invariants",
        ]
        assert "<details" in rendered.html and "```mermaid" in rendered.markdown
        assert "C1" in rendered.markdown and "C5" in rendered.markdown
        assert (
            "No capability availability or contract conformance is yet established"
            not in rendered.markdown
        )
        assert "All realization candidates remain unverified" not in rendered.markdown
    finally:
        repository.close()

    schema_before = (workspace / "model" / "schema.json").read_bytes()
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(workspace)]
    )
    async with Client(parameters, read_timeout_seconds=120) as client:
        # An entirely new architectural concept needs neither a layout node nor a
        # profile/schema/compiler edit: its semantic role determines its reading place.
        applied = await client.call_tool(
            "define_concept",
            {
                "expected_revision": receipt["revision"],
                "id": "entirely-new",
                "concept": {
                    "name": "Previously unknown concept",
                    "description": "Visible without reader edits",
                },
            },
        )
        assert not applied.is_error
        revision = applied.structured_content["revision"]
        for identity in ("C3", "A05", "F11", "S3-responsibility"):
            node = by_id[identity]
            replacement = f"Canonical amendment for {identity}"
            changed = await client.call_tool(
                "apply_changes",
                {
                    "expected_revision": revision,
                    "changes": [
                        {
                            "op": "update_node",
                            **node,
                            "properties": {
                                **node["properties"],
                                "description": replacement,
                            },
                        }
                    ],
                },
            )
            assert not changed.is_error
            revision = changed.structured_content["revision"]
            impacts = {
                item["node_id"]: item for item in changed.structured_content["invalidations"]
            }
            if identity in {"C3", "F11"}:
                assert "S3" in impacts and "B3" in impacts
            if identity == "A05":
                # This reference-workload criterion must not become a universal S3
                # contract or silently constrain the engine/compositor alternatives.
                assert "B3" in impacts
                assert not {"S3", "B3-engine", "B3-compositor"} & impacts.keys()
            if identity != "S3-responsibility":
                assert any(
                    path[0] == identity and path[-1] == "B3" for path in impacts["B3"]["paths"]
                )
    assert (workspace / "model" / "schema.json").read_bytes() == schema_before
    repository = WorkspaceRepository(workspace)
    try:
        rendered = render_specification(compile_architecture(repository.specification_state()))
        assert "Previously unknown concept" in rendered.html
        assert "Visible without reader edits" in rendered.html
        assert rendered.html.count("Canonical amendment for A05") >= 2
        assert rendered.html.count("Canonical amendment for S3-responsibility") >= 2
        assert by_id["A05"]["properties"]["description"] not in rendered.html
    finally:
        repository.close()
