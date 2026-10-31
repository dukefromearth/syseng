"""Path queries through actual authored files and the SQLite-backed service."""

import json

import pytest

from typed_graph.adapters.workspace import open_service


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"source": "a", "target": "c"}, ["a", "b", "c"]),
        ({"source": "c", "target": "a"}, []),
        ({"source": "c", "target": "a", "mode": "dependency"}, ["c", "b", "a"]),
        ({"source": "a", "target": "c", "mode": "dependency"}, []),
        ({"source": "a", "target": "c", "max_depth": 1}, []),
        ({"source": "a", "target": "a", "max_depth": 0}, ["a"]),
        ({"source": "a", "target": "c", "relation": "unconnected"}, []),
        ({"source": "c", "target": "a", "mode": "dependency", "relation": "uses"}, ["c", "b", "a"]),
    ],
)
def test_semantic_and_dependency_paths_are_distinct_and_bounded(tmp_path, arguments, expected):
    model = {
        "schema": {
            "version": "1",
            "node_types": {"Item": {"type": "object", "additionalProperties": False}},
            "relations": {
                name: {"source": ["Item"], "target": ["Item"], "impact": "target_to_source"}
                for name in ["uses", "unconnected"]
            },
        },
        "nodes": [{"id": name, "type": "Item", "properties": {}} for name in "abc"],
        "edges": [
            {"id": "ab", "type": "uses", "source": "a", "target": "b"},
            {"id": "bc", "type": "uses", "source": "b", "target": "c"},
        ],
    }
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "graph.json").write_text(json.dumps(model))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    assert service.dispatch("trace_path", arguments) == {"revision": 1, "path": expected}
