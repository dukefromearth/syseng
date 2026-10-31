"""A user's architecture vocabulary is data, with an end-to-end dependency chain."""

import json
from pathlib import Path

from typed_graph.adapters.workspace import open_service


def test_declared_capability_to_system_impact_chain(tmp_path: Path) -> None:
    types = ["Capability", "Boundary", "Binding", "Contract", "System"]
    nodes = [{"id": kind.lower(), "type": kind, "properties": {"name": kind}} for kind in types]
    relations = {}
    edges = []
    for index, relation in enumerate(["provides", "binds", "requires", "governs"]):
        relations[relation] = {
            "source": [types[index + 1]],
            "target": [types[index]],
            "impact": "target_to_source",
        }
        edges.append(
            {
                "id": relation,
                "type": relation,
                "source": types[index + 1].lower(),
                "target": types[index].lower(),
            }
        )
    document = {
        "schema": {
            "version": "architecture/v1",
            "node_types": {
                kind: {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
                for kind in types
            },
            "relations": relations,
            "interceptors": [
                {
                    "id": "system-review",
                    "target_type": "System",
                    "handler": "pending",
                    "version": "1",
                    "trigger": "dependency_changed",
                    "evidence_required": ["system-contract"],
                }
            ],
        },
        "nodes": nodes,
        "edges": edges,
    }
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "architecture.json").write_text(json.dumps(document))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    result = service.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "capability",
                    "type": "Capability",
                    "properties": {"name": "Changed capability"},
                }
            ],
        },
    )
    assert [impact["node_id"] for impact in result["invalidations"]] == [
        kind.lower() for kind in types
    ]
    assert result["invalidations"][-1]["paths"] == [[kind.lower() for kind in types]]
    assessment = service.dispatch("get_assessments", {})["assessments"][0]
    assert assessment["target_id"] == "system"
    assert assessment["context"]["changes"][0]["id"] == "capability"
    assert assessment["context"]["handler_version"] == "1"
    assert assessment["context"]["invocation_id"]
