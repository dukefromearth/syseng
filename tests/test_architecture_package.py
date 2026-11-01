"""Optional architecture behavior over real MCP transports and atomic graph publication."""

from __future__ import annotations

import copy
import json
import sys

import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from typed_graph.adapters.mcp_server import create_server
from typed_graph.adapters.workspace import open_service
from typed_graph.architecture.models import PACKAGE_VERSION, ROLE_CATALOG, Role
from typed_graph.architecture.schema import architecture_schema
from typed_graph.architecture.tools import TOOL_CATALOG
from typed_graph.domain.models import RelationDefinition, dump_wire


def properties(name, **extra):
    return {"name": name, "description": f"Meaning of {name}", **extra}


def node(identity, role, **extra):
    return {
        "op": "create_node",
        "node": {
            "id": identity,
            "type": role,
            "properties": properties(identity, **extra),
        },
    }


def edge(identity, relation, source, target):
    return {
        "op": "create_edge",
        "edge": {
            "id": identity,
            "type": relation,
            "source": source,
            "target": target,
        },
    }


def bootstrap(workspace, schema=None):
    (workspace / "model").mkdir()
    source = workspace / "model" / "model.json"
    source.write_text(
        json.dumps(
            {
                "schema": dump_wire(schema or architecture_schema()),
                "nodes": [],
                "edges": [],
            }
        )
    )
    return source


def system_request(revision, identity="S1"):
    return {
        "expected_revision": revision,
        "id": identity,
        "system": properties(identity),
        "responsibility": properties(f"{identity} responsibility"),
        "contract": properties(f"{identity} contract", version="1"),
    }


@pytest.mark.parametrize("transport", ["inprocess", "stdio"])
async def test_semantic_tool_catalog_and_all_five_atomic_authoring_operations(tmp_path, transport):
    bootstrap(tmp_path)
    service = open_service(tmp_path)
    server = (
        create_server(service)
        if transport == "inprocess"
        else StdioServerParameters(
            command=sys.executable,
            args=["-m", "typed_graph.adapters.mcp_server", str(tmp_path)],
        )
    )
    async with Client(server, read_timeout_seconds=30) as client:
        before = await client.list_tools()
        assert not set(TOOL_CATALOG).intersection(tool.name for tool in before.tools)
        indexed = await client.call_tool("index_model", {})
        assert not indexed.is_error
        tools = (await client.list_tools(cache_mode="refresh")).tools
        assert set(TOOL_CATALOG).issubset(tool.name for tool in tools)
        define_schema = next(tool.input_schema for tool in tools if tool.name == "define_system")
        canonical = ROLE_CATALOG[Role.SYSTEM].model_json_schema()
        definitions = canonical.pop("$defs", {})
        assert define_schema["$defs"]["BaseProperties"] == canonical
        assert all(define_schema["$defs"][name] == value for name, value in definitions.items())
        calls = [
            ("define_concept", {"id": "meaning", "concept": properties("Meaning")}),
            ("add_layer", {"id": "L1", "layer": properties("Semantic state", rank=1)}),
            (
                "apply_changes",
                {
                    "changes": [
                        node("environment", "Environment"),
                        node("capability", "Capability"),
                        node("invariant", "Invariant"),
                    ]
                },
            ),
            (
                "define_boundary",
                {
                    "id": "boundary",
                    "boundary": properties("Boundary"),
                    "environment": "environment",
                    "layers": ["L1"],
                    "capabilities": ["capability"],
                },
            ),
            (
                "define_system",
                {
                    key: value
                    for key, value in {
                        **system_request(0),
                        "concerns": ["meaning"],
                        "invariants": ["invariant"],
                        "capabilities": ["capability"],
                    }.items()
                    if key != "expected_revision"
                },
            ),
            (
                "propose_binding",
                {
                    "id": "binding",
                    "binding": properties("Candidate", lifecycle="candidate"),
                    "contract": "S1-contract",
                    "boundaries": ["boundary"],
                    "capabilities": ["capability"],
                    "invariants": ["invariant"],
                },
            ),
        ]
        for revision, (name, arguments) in enumerate(calls, start=1):
            result = await client.call_tool(name, {"expected_revision": revision, **arguments})
            assert not result.is_error, result
            assert result.structured_content["revision"] == revision + 1
            output = next(tool.output_schema for tool in tools if tool.name == name)
            Draft202012Validator(output).validate(result.structured_content)
        state = (await client.call_tool("query_graph", {"limit": 1000})).structured_content
        assert state["revision"] == 7 and len(state["nodes"]) == 10
        system = (
            await client.call_tool("compare_graphs", {"from_revision": 5, "to_revision": 6})
        ).structured_content
        assert system["nodes"]["added"] == ["S1", "S1-contract", "S1-responsibility"]
        assert len(system["edges"]["added"]) == 5
        pending = (await client.call_tool("get_assessments", {})).structured_content["assessments"]
        assert len(pending) == 1
        assert pending[0]["state"] == "pending"
        assert pending[0]["result"]["status"] == "indeterminate"
        refusal = await client.call_tool(
            "submit_assessment",
            {
                "revision": 7,
                "interceptor_id": "binding-conformance",
                "target_id": "binding",
                "result": {"status": "pass", "findings": [], "evidence": []},
            },
        )
        assert refusal.is_error
    service.store.close()


@pytest.fixture
def authored(tmp_path):
    source = bootstrap(tmp_path)
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    service.dispatch(
        "define_concept",
        {"expected_revision": 1, "id": "meaning", "concept": properties("Meaning")},
    )
    service.dispatch("define_system", system_request(2))
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 3,
            "changes": [
                node("boundary", "Boundary"),
                node("p1", "Phase"),
                node("p2", "Phase"),
                node("domain", "Ontology", kind="domain"),
                node("system", "Ontology", kind="system"),
                node("realization", "Ontology", kind="realization"),
                node("technology", "TechnologyCandidate"),
            ],
        },
    )
    service.dispatch(
        "propose_binding",
        {
            "expected_revision": 4,
            "id": "binding",
            "binding": properties("Candidate", lifecycle="candidate"),
            "contract": "S1-contract",
            "boundaries": ["boundary"],
        },
    )
    yield service, source
    service.store.close()


def invalid_cases():
    missing_version = system_request(5, "S2")
    del missing_version["contract"]["version"]
    return [
        ("orphan system", "apply_changes", {"changes": [node("orphan", "System")]}),
        (
            "wrong contract owner",
            "apply_changes",
            {"changes": [edge("bad", "specified_by", "S1", "S1-contract")]},
        ),
        (
            "unowned responsibility",
            "apply_changes",
            {"changes": [{"op": "delete_edge", "id": "owns:S1:S1-responsibility"}]},
        ),
        (
            "claimed verification",
            "apply_changes",
            {
                "changes": [
                    {
                        "op": "update_node",
                        "id": "binding",
                        "type": "Binding",
                        "properties": properties("Candidate", lifecycle="verified"),
                    }
                ]
            },
        ),
        (
            "duplicate meaning",
            "define_concept",
            {"id": "duplicate", "concept": properties("Meaning")},
        ),
        (
            "bad boundary reference",
            "define_boundary",
            {"id": "new-boundary", "boundary": properties("Boundary"), "environment": "meaning"},
        ),
        ("unversioned contract", "define_system", missing_version),
        (
            "next cycle",
            "apply_changes",
            {"changes": [edge("p12", "next", "p1", "p2"), edge("p21", "next", "p2", "p1")]},
        ),
        (
            "next role confusion",
            "apply_changes",
            {"changes": [node("step", "ScenarioStep"), edge("pstep", "next", "p1", "step")]},
        ),
        (
            "reversed ontology",
            "apply_changes",
            {"changes": [edge("backwards", "constrains", "system", "domain")]},
        ),
        (
            "technology in domain",
            "apply_changes",
            {"changes": [edge("technology-leak", "includes", "domain", "technology")]},
        ),
        (
            "presentation metadata",
            "define_concept",
            {"id": "layout", "concept": properties("Layout", section="Overview")},
        ),
    ]


@pytest.mark.parametrize(
    "label,tool,arguments",
    invalid_cases(),
    ids=lambda value: value if isinstance(value, str) else None,
)
async def test_semantic_and_generic_mcp_reject_architecture_fallacies_atomically(
    authored, label, tool, arguments
):
    service, _ = authored
    before = service.store.current()
    async with Client(create_server(service), read_timeout_seconds=30) as client:
        result = await client.call_tool(tool, {**arguments, "expected_revision": 5})
        assert result.is_error, label
        after = (await client.call_tool("get_graph_schema", {})).structured_content
        assert after["revision"] == 5
    assert service.store.current() == before
    reopened = open_service(service.store.root)
    assert reopened.store.current() == before
    reopened.store.close()


def test_system_child_identity_collision_has_no_partial_commit(authored):
    service, _ = authored
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 5,
            "changes": [node("S2-contract", "BehavioralContract", version="1")],
        },
    )
    before = service.store.current()
    with pytest.raises(ValueError):
        service.dispatch("define_system", system_request(6, "S2"))
    assert service.store.current() == before
    assert "S2" not in {node.id for node in before.nodes}


@pytest.mark.parametrize("tamper", ["role", "relation", "invariant", "evidence"])
def test_import_cannot_weaken_registered_package(authored, tamper):
    service, source = authored
    payload = json.loads(source.read_text())
    schema = payload["schema"]
    if tamper == "role":
        schema["node_types"]["System"]["additionalProperties"] = True
    elif tamper == "relation":
        schema["relations"]["specified_by"]["source"] = ["System"]
    elif tamper == "invariant":
        schema["invariants"] = []
    else:
        schema["interceptors"][0]["evidence_required"] = []
    source.write_text(json.dumps(payload))
    before = service.store.current()
    with pytest.raises(ValueError):
        service.dispatch("index_model", {})
    assert service.store.current() == before


def test_independence_requires_distinct_alternatives_for_one_unchanged_contract(authored):
    service, _ = authored
    service.dispatch("define_system", system_request(5, "S2"))
    service.dispatch(
        "propose_binding",
        {
            "expected_revision": 6,
            "id": "other",
            "binding": properties("Other"),
            "contract": "S2-contract",
            "boundaries": ["boundary"],
        },
    )
    base = [
        node("objective", "Objective"),
        node("comparison", "IndependenceExample"),
        edge("objective-link", "demonstrates_objective", "comparison", "objective"),
        edge("contract-link", "holds_contract", "comparison", "S1-contract"),
        edge("first", "compares_binding", "comparison", "binding"),
    ]
    for target in ["binding", "other"]:
        before = service.store.current()
        with pytest.raises(ValueError):
            service.dispatch(
                "apply_changes",
                {
                    "expected_revision": 7,
                    "changes": [*base, edge("second", "compares_binding", "comparison", target)],
                },
            )
        assert service.store.current() == before
    service.dispatch(
        "propose_binding",
        {
            "expected_revision": 7,
            "id": "alternative",
            "binding": properties("Alternative"),
            "contract": "S1-contract",
            "boundaries": ["boundary"],
        },
    )
    result = service.dispatch(
        "apply_changes",
        {
            "expected_revision": 8,
            "changes": [*base, edge("second", "compares_binding", "comparison", "alternative")],
        },
    )
    assert result["revision"] == 9


async def test_arbitrary_domain_predicate_and_new_concepts_compile_after_mcp_authoring(tmp_path):
    from typed_graph.architecture.compiler import compile_architecture

    relation = RelationDefinition.model_validate(
        {"source": ["DomainConcept"], "target": ["DomainConcept"], "impact": "both"}
    )
    bootstrap(tmp_path, architecture_schema(domain_relations={"absorbs": relation}))
    service = open_service(tmp_path)
    async with Client(create_server(service), read_timeout_seconds=30) as client:
        assert not (await client.call_tool("index_model", {})).is_error
        result = await client.call_tool(
            "apply_changes",
            {
                "expected_revision": 1,
                "changes": [
                    node("novel-model", "ArchitectureModel", version="1"),
                    node("absorber", "DomainConcept"),
                    node("radiation", "DomainConcept"),
                    edge("ab", "absorbs", "absorber", "radiation"),
                    edge("ba", "absorbs", "radiation", "absorber"),
                ],
            },
        )
        assert not result.is_error
        compiled = compile_architecture(service.store.specification_state())
        assert "absorbs" in compiled.markdown
        assert "absorber" in compiled.markdown and "radiation" in compiled.markdown
        added = await client.call_tool(
            "define_concept",
            {
                "expected_revision": 2,
                "id": "unseen",
                "concept": properties("Entirely new meaning"),
            },
        )
        assert not added.is_error
        refreshed = compile_architecture(service.store.specification_state())
        assert "Entirely new meaning" in refreshed.markdown
        assert refreshed.node_count == compiled.node_count + 1
        assert refreshed.state_digest != compiled.state_digest
    service.store.close()


@pytest.mark.parametrize("version", ["architecture/v1", "architecture/v999", "my-model/v1"])
def test_generic_version_names_are_not_retroactively_reserved(tmp_path, version):
    source = bootstrap(tmp_path)
    payload = {
        "schema": {
            "version": version,
            "node_types": {"ArchitectureModel": {"type": "object"}},
            "relations": {},
        },
        "nodes": [],
        "edges": [],
    }
    source.write_text(json.dumps(payload))
    service = open_service(tmp_path)
    assert service.dispatch("index_model", {})["revision"] == 1
    assert not set(TOOL_CATALOG).intersection(service.tool_catalog)
    service.store.close()


def test_package_registration_marker_is_explicit_and_schema_contracts_have_no_layout_fields():
    assert PACKAGE_VERSION == "typed-graph/architecture/v1"
    schema = architecture_schema()
    assert schema.version == PACKAGE_VERSION
    for definition in schema.node_types.values():
        assert not {"section", "order", "status", "verified"}.intersection(definition["properties"])
    copied = copy.deepcopy(schema)
    assert copied == schema
