"""Impossible declared obligations fail at publication, before any instance is authored."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.client import Client

from typed_graph.adapters.mcp_server import create_server
from typed_graph.adapters.workspace import open_service


@pytest.mark.parametrize(
    "node_type,direction,minimum,maximum,accepted",
    [
        ("Owner", "out", 1, 1, True),
        ("Promise", "in", 1, 1, True),
        ("Promise", "out", 1, 1, False),
        ("Owner", "in", 1, 1, False),
        ("Owner", "out", 2, 1, False),
        ("Promise", "in", 2, 1, False),
    ],
)
async def test_schema_publication_checks_obligation_endpoint_and_cardinality(
    tmp_path: Path,
    node_type: str,
    direction: str,
    minimum: int,
    maximum: int,
    accepted: bool,
) -> None:
    source = tmp_path / "model"
    source.mkdir()
    (source / "graph.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {"Owner": {"type": "object"}, "Promise": {"type": "object"}},
                    "relations": {
                        "owns": {
                            "source": ["Owner"],
                            "target": ["Promise"],
                            "impact": "target_to_source",
                            "cardinality": {"out_max": maximum, "in_max": maximum},
                        }
                    },
                    "invariants": [
                        {
                            "kind": "requires_edge",
                            "node_type": node_type,
                            "relation": "owns",
                            "direction": direction,
                            "min": minimum,
                        }
                    ],
                },
                "nodes": [],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    async with Client(create_server(service)) as client:
        result = await client.call_tool("index_model", {})
        assert result.is_error is not accepted
        state = await client.call_tool("get_graph_schema", {})
        assert state.structured_content["revision"] == int(accepted)
    reopened = open_service(tmp_path)
    assert reopened.revision == int(accepted)
