"""Behavioral specification compilation through the real workspace application."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from typed_graph.adapters.spec_server import project_reader, render_specification
from typed_graph.adapters.workspace import open_service
from typed_graph.application.specification import SpecificationState
from typed_graph.architecture import compile_architecture
from typed_graph.architecture.models import OntologyKind, Relation, Role
from typed_graph.architecture.schema import (
    METAMODEL_RELATIONS,
    RELATION_CATALOG,
    architecture_schema,
)
from typed_graph.domain.models import dump_wire


def boot(path: Path):
    def node(identity, role, name, description, **properties):
        return {
            "id": identity,
            "type": role,
            "properties": {
                "name": name,
                "description": description,
                "statements": [],
                **properties,
            },
        }

    nodes = [
        node(
            "model", Role.MODEL, "An unfamiliar architecture", "A canonical purpose.", version="7"
        ),
        *[
            node(kind, Role.ONTOLOGY, kind.title(), "Independent meaning.", kind=kind)
            for kind in OntologyKind
        ],
        node("system", Role.SYSTEM, "Aster", "Not the responsibility source."),
        node(
            "responsibility", Role.RESPONSIBILITY, "Responsibility", "Own the canonical behavior."
        ),
        node("contract", Role.CONTRACT, "Contract", "Promised result", version="3"),
        node("concept", Role.CONCEPT, "Unfamiliar idea", "A meaning unique to this model."),
        node("criterion", Role.CRITERION, "Latency target", "A scoped acceptance target."),
        node("invariant", Role.INVARIANT, "Meaning must remain stable", "A domain constraint."),
        node("later", Role.PHASE, "Alphabetically first", "This occurs later."),
        node("earlier", Role.PHASE, "Z is first causally", "This occurs first."),
        node(
            "future",
            Role.REQUIREMENT,
            "Future behavior",
            "Not required in this release.",
            priority="future",
        ),
    ]
    edges = [
        {"id": f"edge-{index}", "type": relation, "source": source, "target": target}
        for index, (source, relation, target) in enumerate(
            [
                ("system", Relation.OWNS, "responsibility"),
                ("responsibility", Relation.SPECIFIED_BY, "contract"),
                ("responsibility", Relation.CONCERNS, "concept"),
                ("contract", Relation.DEFINED_IN_TERMS_OF, "concept"),
                ("invariant", Relation.CONSTRAINS_CONCEPT, "concept"),
                ("criterion", Relation.APPLIES_TO, "system"),
                ("future", Relation.APPLIES_TO, "system"),
                ("earlier", Relation.NEXT, "later"),
                ("domain", Relation.INCLUDES, "concept"),
                ("system", Relation.INCLUDES, "system"),
            ]
        )
    ]
    # Ontology and system must have distinct identities even when their labels overlap.
    nodes[2]["id"] = "system-ontology"
    edges[-1]["source"] = "system-ontology"
    (path / "model").mkdir()
    (path / "model" / "model.json").write_text(
        json.dumps(
            {
                "schema": dump_wire(architecture_schema()),
                "nodes": nodes,
                "edges": edges,
            }
        )
    )
    service = open_service(path)
    service.dispatch("index_model", {})
    return service


def test_fixed_document_joins_canonical_facts_and_keeps_graph_secondary(tmp_path):
    service = boot(tmp_path)
    try:
        state = service.store.specification_state()
        document = compile_architecture(state)
        headings = [entry.label for entry in document.outline if entry.level == 2]
        assert headings[:7] == [
            "1. Unified metamodel",
            "2. Domain ontology",
            "3. System ontology",
            "4. Realization ontology",
            "5. Cross-model relationships",
            "6. Demonstrating independence",
            "7. Model invariants",
        ]
        assert document.markdown.count("Own the canonical behavior") == 2
        assert "Not the responsibility source" not in document.markdown
        assert "Contract version: 3" in document.markdown
        assert "Version 7" in document.markdown
        assert "future" in document.markdown
        assert document.markdown.index("Z is first causally") < document.markdown.index(
            "Alphabetically first"
        )
        for relation in METAMODEL_RELATIONS:
            assert RELATION_CATALOG[relation].meaning in render_specification(document).html
            assert relation in document.diagrams[0].schema_relations
        assert "constrains concept" in document.markdown
        assert Relation.CONSTRAINS_CONCEPT in document.diagrams[0].schema_relations
        assert document.diagrams[0].schema_roles
        assert not document.diagrams[0].node_ids
        reader = project_reader(state, None)
        assert reader.title == "An unfamiliar architecture"
        assert "Not the responsibility source" in reader.inspector.markdown
        assert "Incoming" not in document.markdown
    finally:
        service.store.close()


@pytest.mark.parametrize("operation", ["update", "new-concept"])
def test_public_changes_update_compiled_facts_without_layout_edits(tmp_path, operation):
    service = boot(tmp_path)
    try:
        before = service.store.specification_state()
        if operation == "update":
            node = next(node for node in before.snapshot.nodes if node.id == "responsibility")
            change = {
                "op": "update_node",
                **dump_wire(node),
                "properties": {
                    **node.properties,
                    "description": "Revised canonical behavior.",
                },
            }
        else:
            change = {
                "op": "create_node",
                "node": {
                    "id": "novel",
                    "type": Role.CONCEPT,
                    "properties": {
                        "name": "Entirely new concept",
                        "description": "Visible without frontend edits.",
                    },
                },
            }
        service.dispatch(
            "apply_changes",
            {
                "expected_revision": before.snapshot.revision,
                "changes": [change],
            },
        )
        document = compile_architecture(service.store.specification_state())
        if operation == "update":
            assert document.markdown.count("Revised canonical behavior") == 2
            assert "Own the canonical behavior" not in document.markdown
        else:
            assert "Entirely new concept" in document.markdown
            assert "Visible without frontend edits" in document.markdown
    finally:
        service.store.close()


def test_collection_order_cannot_change_compiled_document_or_execute_authored_html(tmp_path):
    service = boot(tmp_path)
    try:
        state = service.store.specification_state()
        reversed_state = SpecificationState(
            snapshot=state.snapshot.model_copy(
                update={
                    "nodes": list(reversed(state.snapshot.nodes)),
                    "edges": list(reversed(state.snapshot.edges)),
                }
            ),
            assessments=list(reversed(state.assessments)),
        )
        assert compile_architecture(state) == compile_architecture(reversed_state)
        node = next(node for node in state.snapshot.nodes if node.id == "concept")
        service.dispatch(
            "apply_changes",
            {
                "expected_revision": state.snapshot.revision,
                "changes": [
                    {
                        "op": "update_node",
                        **dump_wire(node),
                        "properties": {
                            **node.properties,
                            "description": '<script>alert("no")</script>',
                        },
                    }
                ],
            },
        )
        rendered = render_specification(compile_architecture(service.store.specification_state()))
        assert "<script>" not in rendered.html
        assert "&lt;script&gt;" in rendered.html
    finally:
        service.store.close()


@pytest.mark.parametrize("registered", [False, True])
def test_only_explicit_registered_architecture_with_model_activates_reader(tmp_path, registered):
    schema = (
        dump_wire(architecture_schema())
        if registered
        else {
            "version": "unrelated/v1",
            "node_types": {
                "ArchitectureModel": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            },
            "relations": {},
        }
    )
    nodes = (
        []
        if registered
        else [
            {
                "id": "unrelated",
                "type": "ArchitectureModel",
                "properties": {"name": "Ordinary fact"},
            }
        ]
    )
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "source.json").write_text(
        json.dumps(
            {
                "schema": schema,
                "nodes": nodes,
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    try:
        service.dispatch("index_model", {})
        reader = project_reader(service.store.specification_state(), None)
        assert reader.title == "No architecture specification available"
        assert reader.inspector is not None
        if not registered:
            assert "Ordinary fact" in reader.inspector.markdown
    finally:
        service.store.close()
