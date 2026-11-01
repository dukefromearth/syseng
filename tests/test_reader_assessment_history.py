"""Unrelated commits retain visible assessment provenance without inventing validity."""

import json

import pytest

from typed_graph.adapters.workspace import open_service
from typed_graph.application.specification import project_specification


@pytest.mark.parametrize("initial_result", [None, "pass", "fail"])
def test_reader_retains_stale_assessments_and_newer_revision_supersedes_them(
    tmp_path, initial_result
):
    source = tmp_path / "model"
    source.mkdir()
    (source / "graph.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {"Reviewed": {"type": "object"}, "Note": {"type": "object"}},
                    "relations": {},
                    "interceptors": [
                        {
                            "id": "review",
                            "target_type": "Reviewed",
                            "handler": "pending",
                            "version": "1",
                            "trigger": "dependency_changed",
                            "evidence_required": ["proof"],
                        }
                    ],
                },
                "nodes": [{"id": "a", "type": "Reviewed", "properties": {"name": "Original"}}],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    try:
        service.dispatch("index_model", {})
        if initial_result is not None:
            service.dispatch(
                "submit_assessment",
                {
                    "revision": 1,
                    "interceptor_id": "review",
                    "target_id": "a",
                    "result": {
                        "status": initial_result,
                        "findings": [{"summary": "Original recorded finding"}],
                        "evidence": [{"obligation": "proof", "uri": "urn:test:original"}],
                    },
                },
            )
        original = service.store.specification_state().assessments[0]
        service.dispatch(
            "apply_changes",
            {
                "expected_revision": 1,
                "changes": [
                    {
                        "op": "create_node",
                        "node": {"id": "unrelated", "type": "Note", "properties": {}},
                    }
                ],
            },
        )
        state = service.store.specification_state()
        assert state.snapshot.revision == 2
        assert state.assessments == [original]
        document = project_specification(state)
        assert "stale" in document.markdown
        assert "current revision" not in document.markdown
        # The tool's revision-specific contract is not silently broadened by the reader.
        assert service.dispatch("get_assessments", {})["assessments"] == []
        service.dispatch(
            "apply_changes",
            {
                "expected_revision": 2,
                "changes": [
                    {
                        "op": "update_node",
                        "id": "a",
                        "type": "Reviewed",
                        "properties": {"name": "Changed"},
                    }
                ],
            },
        )
        newer = service.store.specification_state().assessments
        assert len(newer) == 1
        assert newer[0].revision == 3
        assert newer[0].state == "pending"
        assert newer[0].result.status == "indeterminate"
        assert not newer[0].result.evidence
        # A result arriving late for the old revision cannot displace this pending review.
        service.dispatch(
            "submit_assessment",
            {
                "revision": 1,
                "interceptor_id": "review",
                "target_id": "a",
                "result": {
                    "status": "pass",
                    "findings": [],
                    "evidence": [{"obligation": "proof", "uri": "urn:test:late"}],
                },
            },
        )
        assert service.store.specification_state().assessments == newer
    finally:
        service.store.close()
