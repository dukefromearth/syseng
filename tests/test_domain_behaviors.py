"""Table-driven domain contracts through the public graph API (no private mocks)."""

from copy import deepcopy

import pytest

from typed_graph.domain.engine import apply_operations, compute_impact, validate_graph
from typed_graph.domain.schema import GraphError, apply_input_schema, validate_schema


def schema():
    return {
        "version": "1",
        "node_types": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
        "relations": {
            "uses": {"source": ["Item"], "target": ["Item"], "impact": "target_to_source"}
        },
    }


def node(identifier):
    return {"id": identifier, "type": "Item", "properties": {"name": identifier}}


def edge(identifier, source, target):
    return {"id": identifier, "type": "uses", "source": source, "target": target}


@pytest.mark.parametrize(
    "changes",
    [
        [{"op": "create_node", "node": node("a")}],
        [{"op": "update_node", "id": "a", "type": "Item", "properties": {"name": 1}}],
        [{"op": "create_edge", "edge": edge("x", "a", "missing")}],
        [{"op": "delete_node", "id": "missing"}],
        [{"op": "delete_node", "id": "b"}],
        [{"op": "raw_sql", "sql": "DROP TABLE nodes"}],
    ],
)
def test_rejected_batches_leave_inputs_unchanged(changes):
    nodes, edges = [node("a"), node("b")], [edge("x", "a", "b")]
    before = deepcopy((nodes, edges))
    with pytest.raises(GraphError):
        apply_operations(schema(), nodes, edges, changes)
    assert (nodes, edges) == before


@pytest.mark.parametrize(
    "constraint",
    [
        {"invariants": [{"kind": "unique", "node_type": "Item", "property": "name"}]},
        {"invariants": [{"kind": "requires_edge", "node_type": "Item", "relation": "uses"}]},
        {
            "relations": {
                "uses": {
                    "source": ["Item"],
                    "target": ["Item"],
                    "impact": "none",
                    "cardinality": {"out_max": 0},
                }
            }
        },
    ],
)
def test_declared_constraints(constraint):
    model_schema = {**schema(), **constraint}
    nodes = [node("a"), {**node("b"), "properties": {"name": "a"}}]
    with pytest.raises(GraphError):
        validate_graph(model_schema, nodes, [edge("x", "a", "b")])


def test_deleted_dependency_and_cycle_retain_provenance():
    model_schema = schema()
    nodes = [node("a"), node("b"), node("c")]
    edges = [edge("ab", "a", "b"), edge("ba", "b", "a"), edge("bc", "b", "c")]
    new_nodes, new_edges, changed = apply_operations(
        model_schema,
        nodes,
        edges,
        [{"op": "delete_edge", "id": "bc"}, {"op": "delete_node", "id": "c"}],
    )
    impact = compute_impact(
        model_schema, model_schema, nodes, edges, new_nodes, new_edges, changed, 2
    )
    assert [item["node_id"] for item in impact] == ["a", "b"]
    assert ["c", "b", "a"] in impact[0]["paths"]
    assert all(item["triggering_revision"] == 2 for item in impact)


@pytest.mark.parametrize(
    "patch",
    [
        {"invariants": [{"kind": "python", "node_type": "Item", "expression": "1"}]},
        {"node_types": {"Item": {"$ref": "https://example.com/schema"}}},
        {"relations": {"uses": {"source": ["Unknown"], "target": ["Item"], "impact": "none"}}},
    ],
)
def test_unsupported_schema_is_rejected(patch):
    with pytest.raises(GraphError):
        validate_schema({**schema(), **patch})


def test_local_defs_survive_dynamic_tool_compilation():
    model_schema = schema()
    model_schema["node_types"]["Item"] = {
        "type": "object",
        "$defs": {"word": {"type": "string"}},
        "properties": {"name": {"$ref": "#/$defs/word"}},
        "required": ["name"],
    }
    compiled = apply_input_schema(model_schema)
    assert compiled["properties"]["changes"]["items"]["oneOf"]
    result = apply_operations(model_schema, [], [], [{"op": "create_node", "node": node("a")}])
    assert result[0] == [node("a")]


def test_empty_registry_bootstraps_but_rejects_mutations():
    from jsonschema import Draft202012Validator

    empty = {"version": "0", "node_types": {}, "relations": {}}
    validate_graph(empty, [], [])
    compiled = apply_input_schema(empty)
    Draft202012Validator.check_schema(compiled)
    assert compiled["properties"]["changes"]["items"] is False
    with pytest.raises(GraphError):
        apply_operations(empty, [], [], [{"op": "create_node", "node": node("a")}])


@pytest.mark.parametrize(
    "definition",
    [
        {"$ref": "https://example.test/schema"},
        {"$ref": "#word", "$anchor": "word"},
        {"$dynamicRef": "#/$defs/word"},
        {"$id": "https://example.test/schema", "type": "object"},
    ],
)
def test_unsupported_reference_forms_fail_closed(definition):
    with pytest.raises(GraphError):
        validate_schema({**schema(), "node_types": {"Item": definition}})


@pytest.mark.parametrize(
    "changes",
    [
        [{"op": "update_node", "id": "a", "type": "Item", "properties": {"name": "a"}}],
        [
            {"op": "create_node", "node": node("temporary")},
            {"op": "delete_node", "id": "temporary"},
        ],
        [
            {"op": "update_node", "id": "a", "type": "Item", "properties": {"name": "changed"}},
            {"op": "update_node", "id": "a", "type": "Item", "properties": {"name": "a"}},
        ],
    ],
)
def test_final_state_noops_have_no_invalidations(changes):
    nodes, edges, changed = apply_operations(schema(), [node("a")], [], changes)
    assert nodes == [node("a")]
    assert edges == []
    assert changed == []


def test_undeclared_edge_properties_are_closed():
    with pytest.raises(GraphError):
        apply_operations(
            schema(),
            [node("a"), node("b")],
            [],
            [
                {
                    "op": "create_edge",
                    "edge": {**edge("ab", "a", "b"), "properties": {"undeclared": "value"}},
                }
            ],
        )
    with pytest.raises(GraphError):
        validate_graph(
            schema(),
            [node("a"), node("b")],
            [{**edge("ab", "a", "b"), "properties": {"undeclared": "value"}}],
        )


def test_scc_condensation_order_and_cycle_members_are_explicit():
    nodes = [node("a"), node("b"), node("c"), node("d")]
    edges = [edge("ab", "a", "b"), edge("ba", "b", "a"), edge("bc", "b", "c"), edge("cd", "c", "d")]
    impact = compute_impact(schema(), schema(), nodes, edges, nodes, edges, ["d"], 3)
    assert [item["node_id"] for item in impact] == ["d", "c", "a", "b"]
    assert impact[-1]["component_id"] == "a"
    assert impact[-1]["component"] == ["a", "b"]
    assert impact[-1]["paths"] == [["d", "c", "b"]]


def test_concise_schema_compiles_arbitrary_types_and_requires_declared_properties():
    from typed_graph.domain.schema import compile_schema

    compiled = compile_schema(
        {
            "schema": "architecture/v1",
            "nodes": {
                "Widget": {"properties": {"name": "string", "count": "integer"}},
                "Bucket": {"properties": {"label": "string"}, "required": []},
            },
            "edges": {"contains": {"from": "Bucket", "to": "Widget", "impact": "target_to_source"}},
        }
    )
    assert compiled["version"] == "architecture/v1"
    assert compiled["node_types"]["Widget"]["required"] == ["count", "name"]
    assert compiled["relations"]["contains"]["source"] == ["Bucket"]
    validate_graph(
        compiled,
        [
            {"id": "b", "type": "Bucket", "properties": {}},
            {"id": "w", "type": "Widget", "properties": {"name": "W", "count": 1}},
        ],
        [{"id": "bw", "type": "contains", "source": "b", "target": "w"}],
    )
    with pytest.raises(GraphError):
        validate_graph(compiled, [{"id": "w", "type": "Widget", "properties": {"name": "W"}}], [])
