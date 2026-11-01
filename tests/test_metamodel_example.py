"""The published example is authored via actual tools and rendered as a specification."""

import json
import subprocess
import sys
from pathlib import Path

from typed_graph.adapters.spec_server import render_specification
from typed_graph.adapters.workspace import WorkspaceRepository
from typed_graph.application.specification import PresentationProfile, project_specification
from typed_graph.domain.models import dump_wire


def test_metamodel_tool_authoring_and_profile_render(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    example = root / "examples" / "architectural_metamodel"
    workspace = tmp_path / "metamodel"
    result = subprocess.run(
        [sys.executable, str(example / "author.py"), str(workspace)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    receipt = json.loads(result.stdout)
    authored = json.loads((example / "source.json").read_text())
    assert (receipt["revision"], receipt["nodes"], receipt["edges"]) == (
        2,
        len(authored["nodes"]),
        len(authored["edges"]),
    )
    transcript = json.loads((workspace / "mcp-transcript.json").read_text())
    assert receipt["tool_calls"] == len(transcript)
    assert {
        "index_model",
        "apply_changes",
        "get_graph_schema",
        "query_graph",
        "get_assessments",
        "trace_path",
        "compare_graphs",
    } <= {call["tool"] for call in transcript}
    repository = WorkspaceRepository(workspace)
    try:
        state = repository.specification_state()
        assert sorted(
            [dump_wire(node) for node in state.snapshot.nodes], key=lambda item: item["id"]
        ) == sorted(authored["nodes"], key=lambda item: item["id"])
        assert sorted(
            [dump_wire(edge) for edge in state.snapshot.edges], key=lambda item: item["id"]
        ) == sorted(authored["edges"], key=lambda item: item["id"])
        specified_by = state.snapshot.schema_definition.relations["specified_by"]
        assert specified_by.source == ["Responsibility"]
        assert specified_by.target == ["Contract"]
        nodes = {node.id: node for node in state.snapshot.nodes}
        links = [edge for edge in state.snapshot.edges if edge.type == "specified_by"]
        assert links
        assert all(
            nodes[edge.source].type == "Responsibility" and nodes[edge.target].type == "Contract"
            for edge in links
        )
        profile = PresentationProfile.model_validate_json(
            (example / "presentation.json").read_text()
        )
        rendered = render_specification(project_specification(state, profile))
        assert rendered.title == "Architectural Metamodel v1.0"
        assert [entry.label for entry in rendered.outline if entry.level == 3][:5] == [
            "Domain",
            "Systems",
            "Realization",
            "Example",
            "Governance",
        ]
        assert len(state.assessments) == 3
        assert all(not item.result.evidence for item in state.assessments)
        assert "indeterminate" in rendered.html
        assert "appendix" in rendered.markdown.lower()
        labels = [entry.label for entry in rendered.outline]
        assert labels.index("Specification") < next(
            index for index, label in enumerate(labels) if "appendix" in label.lower()
        )
    finally:
        repository.close()
