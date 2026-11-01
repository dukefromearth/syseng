"""Graph-authored views through public mutations, projection and safe HTTP rendering."""

import json
from html.parser import HTMLParser

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from typed_graph.adapters.spec_server import render_specification
from typed_graph.adapters.workspace import open_service
from typed_graph.application.specification import PresentationProfile, project_specification


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.opened = []
        self.closed = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.opened.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        self.closed.append(tag)


@pytest.fixture
def graph(tmp_path):
    (tmp_path / "model").mkdir()
    model = {
        "schema": {
            "version": "views/v1",
            "node_types": {
                kind: {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "section": {"type": "string"},
                        "status": {"type": "string"},
                        "statements": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                }
                for kind in ["Unfamiliar", "NewConcept"]
            },
            "relations": {
                "connects": {
                    "source": ["Unfamiliar"],
                    "target": ["Unfamiliar"],
                    "impact": "none",
                    "properties": {
                        "type": "object",
                        "properties": {"reason": {"type": "string"}},
                        "additionalProperties": False,
                    },
                }
            },
        },
        "nodes": [
            {
                "id": identity,
                "type": "Unfamiliar",
                "properties": {"name": identity.upper(), "section": "Overview"},
            }
            for identity in ["a", "b", "c"]
        ],
        "edges": [
            {"id": left + right, "type": "connects", "source": left, "target": right}
            for left, right in [("a", "b"), ("b", "c"), ("c", "a")]
        ],
    }
    (tmp_path / "model" / "model.json").write_text(json.dumps(model))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    yield service
    service.store.close()


def profile(**changes):
    return PresentationProfile.model_validate(
        {
            "group_property": "section",
            "collapse_nodes": True,
            "collapse_schema": True,
            "diagrams": [{"id": "overview", "title": "Connections", "node_types": ["Unfamiliar"]}],
            **changes,
        }
    )


def test_graph_changes_update_diagrams_and_new_concepts_need_no_presentation_edits(graph):
    selected = profile()
    before = project_specification(graph.store.specification_state(), selected)
    assert before.diagrams[0].node_ids == ["a", "b", "c"]
    assert before.diagrams[0].edge_ids == ["ab", "bc", "ca"]
    assert before.diagrams[0].source.startswith("flowchart LR\n")
    assert before.markdown.count("```mermaid") == 1
    graph.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {"op": "delete_edge", "id": "ab"},
                {
                    "op": "create_node",
                    "node": {
                        "id": "novel",
                        "type": "NewConcept",
                        "properties": {"name": "New meaning"},
                    },
                },
            ],
        },
    )
    after = project_specification(graph.store.specification_state(), selected)
    assert after.diagrams[0].edge_ids == ["bc", "ca"]
    assert "New meaning" in after.markdown
    assert "Unspecified group" in after.markdown
    assert after.state_digest != before.state_digest
    assert after.node_count == 4
    rendered = render_specification(after)
    elements = Elements(rendered.html)
    details = [attrs for tag, attrs in elements.opened if tag == "details"]
    assert len(details) == 5  # Four node records plus the schema appendix.
    assert elements.closed.count("details") == len(details)
    assert elements.closed.count("summary") == len(details)
    assert {attrs["data-section-id"] for attrs in details} == {d.id for d in after.disclosures}
    assert all("open" not in attrs for attrs in details)
    assert len([tag for tag, _ in elements.opened if tag == "figure"]) == 1


def test_bounded_diagrams_declare_omissions_without_dropping_document_content(graph):
    selected = profile(
        diagrams=[
            {
                "id": "bounded",
                "title": "Small view",
                "max_nodes": 2,
                "max_edges": 1,
            }
        ]
    )
    projected = project_specification(graph.store.specification_state(), selected)
    diagram = projected.diagrams[0]
    assert diagram.node_ids == ["a", "b"]
    assert diagram.edge_ids == ["ab"]
    assert diagram.omitted_node_count == 1
    assert diagram.omitted_edge_count == 2
    assert "1 selected nodes and 2 selected relationships omitted" in projected.markdown
    assert any(entry.label == "C" for entry in projected.outline)


def test_only_generated_diagrams_execute_and_untrusted_labels_cannot_create_grammar(graph):
    hostile = '"]\nclick x "https://evil.invalid"\n%%{init: {"securityLevel":"loose"}}%%'
    body = (
        "```mermaid\nflowchart LR\na --> b\n```\n\n"
        "<details open><summary>Forged</summary></details>"
    )
    graph.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "Unfamiliar",
                    "properties": {"name": hostile, "description": body},
                }
            ],
        },
    )
    projected = project_specification(graph.store.specification_state(), profile())
    source = projected.diagrams[0].source
    assert "%%{" not in source
    assert 'click x "https://' not in source
    assert "#34;" in source and "#37;" in source
    assert len(source.splitlines()) == 7  # Header, 3 node declarations, 3 real edges.
    rendered = render_specification(projected)
    elements = Elements(rendered.html)
    assert len([tag for tag, _ in elements.opened if tag == "figure"]) == 1
    assert len([tag for tag, _ in elements.opened if tag == "details"]) == 4
    assert not any("open" in attrs for tag, attrs in elements.opened if tag == "details")
    assert "flowchart LR\na --&gt; b" in rendered.html
    assert "&lt;details open&gt;" in rendered.html
    # No renderer or projector normalization mutates the canonical authored text.
    assert graph.resource("graph://model/nodes/a")["node"]["properties"]["description"] == body


@pytest.mark.parametrize("placement", [None, "Overview", "Missing group"])
def test_diagram_placement_and_collection_order_are_deterministic(graph, placement):
    diagram = {"id": "view", "title": "Selected graph", "node_ids": ["a", "c"], "direction": "TB"}
    if placement is not None:
        diagram["placement_group"] = placement
    selected = profile(diagrams=[diagram])
    state = graph.store.specification_state()
    projected = project_specification(state, selected)
    reversed_state = state.model_copy(
        update={
            "snapshot": state.snapshot.model_copy(
                update={
                    "nodes": list(reversed(state.snapshot.nodes)),
                    "edges": list(reversed(state.snapshot.edges)),
                }
            )
        }
    )
    assert project_specification(reversed_state, selected) == projected
    assert projected.diagrams[0].node_ids == ["a", "c"]
    assert projected.diagrams[0].edge_ids == ["ca"]
    assert projected.diagrams[0].source.startswith("flowchart TB")
    assert projected.markdown.count("Selected graph\n") == 1
    if placement == "Overview":
        assert projected.markdown.index("### Overview") < projected.markdown.index(
            "### Selected graph"
        )
    else:
        assert projected.markdown.index("Selected graph\n") < projected.markdown.index(
            "### Overview"
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_nodes", 0),
        ("max_nodes", 61),
        ("max_edges", 121),
        ("max_edges", True),
        ("direction", "sideways"),
        ("node_ids", "a"),
        ("unknown", 1),
        ("relation_path", []),
        ("relation_path", ["connects"]),
        ("relation_path", ["connects", "connects", "connects"]),
    ],
)
def test_view_runtime_and_generated_schema_reject_same_invalid_inputs(field, value):
    raw = {"diagrams": [{"id": "x", "title": "X", field: value}]}
    assert list(Draft202012Validator(PresentationProfile.model_json_schema()).iter_errors(raw))
    with pytest.raises(ValidationError):
        PresentationProfile.model_validate(raw)


def test_disclosure_is_presentation_only_and_changes_the_reader_digest(graph):
    state = graph.store.specification_state()
    expanded = project_specification(state, PresentationProfile())
    collapsed = project_specification(
        state, PresentationProfile(collapse_nodes=True, collapse_schema=True)
    )
    assert expanded.markdown == collapsed.markdown
    assert expanded.state_digest != collapsed.state_digest
    assert expanded.revision == collapsed.revision
    assert expanded.assessment_digest == collapsed.assessment_digest
    assert not expanded.disclosures
    assert len(collapsed.disclosures) == 4


def test_reading_view_groups_relations_and_keeps_body_facts_and_candidate_status(graph):
    graph.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "Unfamiliar",
                    "properties": {
                        "name": "A",
                        "description": "Opening prose",
                        "statements": ["First fact", "Second fact"],
                    },
                },
                {
                    "op": "update_node",
                    "id": "b",
                    "type": "Unfamiliar",
                    "properties": {
                        "name": "B",
                        "status": "candidate",
                    },
                },
                {
                    "op": "create_edge",
                    "edge": {
                        "id": "ac",
                        "type": "connects",
                        "source": "a",
                        "target": "c",
                        "properties": {"reason": "Explicit edge metadata"},
                    },
                },
            ],
        },
    )
    selected = PresentationProfile(
        compact_relationships=True,
        compact_properties=True,
        body_properties=["description", "statements"],
        show_body_labels=False,
        show_type_metadata=False,
        show_projection_metadata=False,
    )
    result = project_specification(graph.store.specification_state(), selected)
    record = result.markdown.split("#### A\n")[1].split("#### B\n")[0]
    assert record.count("**Outgoing · connects:**") == 1
    assert record.count("**Incoming · connects:**") == 1
    assert "[B](#" in record and "[C](#" in record
    assert "Explicit edge metadata" in record
    assert "edge ` ac `" in record
    assert "Opening prose" in record and "- First fact" in record and "- Second fact" in record
    assert "**description**" not in record and "**statements**" not in record
    assert "Registered type:" not in record and "**Type:**" not in record
    assert "Graph revision:" not in result.markdown
    assert "**status:** candidate" in result.markdown
    assert result.revision == 2 and result.node_count == 3


def test_two_hop_diagram_projects_only_real_paths_with_provenance_and_bounds(graph):
    graph.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "create_edge",
                    "edge": {
                        "id": "ab-duplicate",
                        "type": "connects",
                        "source": "a",
                        "target": "b",
                    },
                }
            ],
        },
    )
    selected = profile(
        diagrams=[
            {
                "id": "paths",
                "title": "Two steps",
                "relation_path": ["connects", "connects"],
                "max_edges": 2,
            }
        ]
    )
    projected = project_specification(graph.store.specification_state(), selected)
    view = projected.diagrams[0]
    assert [(path.source, path.via, path.target) for path in view.paths] == [
        ("a", "b", "c"),
        ("b", "c", "a"),
    ]
    assert view.paths[0].edge_ids == ["ab", "bc"]
    assert view.paths[1].edge_ids == ["bc", "ca"]
    assert view.edge_ids == ["ab", "bc", "ca"]
    assert view.omitted_path_count == 1
    assert view.source.count(" -->|") == 2
    assert '-->|"B"|' in view.source and '-->|"C"|' in view.source
    assert "1 relationship paths between displayed nodes omitted" in projected.markdown
    # Filters select endpoints, not the intermediate node that labels the path.
    endpoints = profile(
        diagrams=[
            {
                "id": "path",
                "title": "Selected endpoints",
                "node_ids": ["a", "c"],
                "relation_path": ["connects", "connects"],
            }
        ]
    )
    filtered = project_specification(graph.store.specification_state(), endpoints).diagrams[0]
    assert filtered.node_ids == ["a", "c"]
    assert [(path.source, path.via, path.target) for path in filtered.paths] == [("a", "b", "c")]
    missing = profile(
        diagrams=[
            {
                "id": "absent",
                "title": "No invented path",
                "relation_path": ["connects", "missing"],
            }
        ]
    )
    absent = project_specification(graph.store.specification_state(), missing).diagrams[0]
    assert not absent.paths and not absent.edge_ids and " -->|" not in absent.source


def test_labels_keep_ordinary_unicode_and_only_escape_mermaid_control_characters(graph):
    graph.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "Unfamiliar",
                    "properties": {
                        "name": "Domain · Meaning / ordinary_name",
                    },
                }
            ],
        },
    )
    view = project_specification(graph.store.specification_state(), profile()).diagrams[0]
    assert "Domain · Meaning / ordinary_name" in view.source
    assert "#183;" not in view.source
