"""Strict canonical contracts exercised through a durable workspace."""

import json

import pytest
from pydantic import ValidationError

from typed_graph.adapters.workspace import open_service
from typed_graph.domain.models import ApplyChangesRequest, ApplyResult, AssessmentResult, dump_wire
from typed_graph.domain.schema import APPLY_OUTPUT_SCHEMA, RESULT_SCHEMA


@pytest.mark.parametrize(
    "revision,change",
    [
        (True, {"op": "create_node", "node": {"id": "b", "type": "Item", "properties": {}}}),
        ("1", {"op": "create_node", "node": {"id": "b", "type": "Item", "properties": {}}}),
        (1.0, {"op": "create_node", "node": {"id": "b", "type": "Item", "properties": {}}}),
        (1, {"op": "create_node", "node": {"id": 7, "type": "Item", "properties": {}}}),
        (1, {"op": "create_node", "node": {"id": "b", "type": "Item", "properties": []}}),
        (1, {"op": "delete_node", "id": "a", "unexpected": True}),
        (1, {"op": "import"}),
    ],
)
def test_strict_mutation_boundary_never_coerces_or_commits(tmp_path, revision, change):
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "graph.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "node_types": {"Item": {"type": "object"}},
                    "relations": {},
                },
                "nodes": [{"id": "a", "type": "Item", "properties": {}}],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    before = service.resource("graph://model/revisions/1")
    with pytest.raises((ValueError, ValidationError)):
        service.dispatch("apply_changes", {"expected_revision": revision, "changes": [change]})
    assert service.revision == 1
    assert open_service(tmp_path).resource("graph://model/revisions/1") == before


def test_shared_models_generate_result_schemas_and_preserve_optional_wire_fields():
    assert RESULT_SCHEMA == AssessmentResult.model_json_schema()
    assert APPLY_OUTPUT_SCHEMA == ApplyResult.model_json_schema()
    request = ApplyChangesRequest.model_validate(
        {
            "expected_revision": 0,
            "changes": [
                {
                    "op": "create_edge",
                    "edge": {"id": "ab", "type": "uses", "source": "a", "target": "b"},
                }
            ],
        }
    )
    assert dump_wire(request) == {
        "expected_revision": 0,
        "changes": [
            {
                "op": "create_edge",
                "edge": {"id": "ab", "type": "uses", "source": "a", "target": "b"},
            }
        ],
    }


@pytest.mark.parametrize(
    "model_class,payload",
    [
        (
            "relation",
            {"source": ["Item"], "target": ["Item"], "impact": "none", "cardinality": None},
        ),
        (
            "relation",
            {"source": ["Item"], "target": ["Item"], "impact": "none", "properties": None},
        ),
        ("cardinality", {"out_max": None}),
        (
            "interceptor",
            {
                "id": "i",
                "target_type": "Item",
                "handler": "pending",
                "version": "1",
                "trigger": "dependency_changed",
                "result_schema": None,
            },
        ),
    ],
)
def test_omission_only_fields_reject_null_in_generated_and_runtime_contract(model_class, payload):
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as JsonValidationError

    from typed_graph.domain.models import Cardinality, Interceptor, RelationDefinition

    model = {
        "relation": RelationDefinition,
        "cardinality": Cardinality,
        "interceptor": Interceptor,
    }[model_class]
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    with pytest.raises(JsonValidationError):
        Draft202012Validator(model.model_json_schema()).validate(payload)
    optional_fields = {
        "relation": ["cardinality", "properties"],
        "cardinality": ["out_max", "out_min", "in_max", "in_min"],
        "interceptor": ["result_schema"],
    }
    properties = model.model_json_schema()["properties"]
    for field in optional_fields[model_class]:
        assert "default" not in properties[field]


def test_enum_contract_has_enum_internal_values_without_scalar_coercion():
    from typed_graph.domain.models import AssessmentStatus, ImpactDirection, RelationDefinition

    assert (
        AssessmentResult.model_validate({"status": "pass", "findings": [], "evidence": []}).status
        is AssessmentStatus.PASS
    )
    assert (
        RelationDefinition.model_validate(
            {"source": ["Item"], "target": ["Item"], "impact": "both"}
        ).impact
        is ImpactDirection.BOTH
    )
    for value in [True, 1, b"pass", "unknown"]:
        with pytest.raises(ValidationError):
            AssessmentResult.model_validate({"status": value, "findings": [], "evidence": []})
