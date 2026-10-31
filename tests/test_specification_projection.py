"""Specification behavior through real authored imports, revisions and assessments."""

import json
from pathlib import Path

import pytest

from typed_graph.adapters.workspace import open_service
from typed_graph.application.specification import (
    PresentationProfile,
    SpecificationState,
    project_specification,
)


def boot(path):
    model = {
        "schema": {
            "version": "spec/v1",
            "node_types": {
                "UnfamiliarType": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "settings": {"type": "object"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                }
            },
            "relations": {
                "depends": {
                    "source": ["UnfamiliarType"],
                    "target": ["UnfamiliarType"],
                    "impact": "target_to_source",
                }
            },
            "invariants": [{"kind": "unique", "node_type": "UnfamiliarType", "property": "name"}],
            "interceptors": [
                {
                    "id": "review",
                    "target_type": "UnfamiliarType",
                    "handler": "pending",
                    "version": "handler/v1",
                    "trigger": "dependency_changed",
                    "evidence_required": ["conformance"],
                }
            ],
        },
        "nodes": [
            {
                "id": "b",
                "type": "UnfamiliarType",
                "properties": {
                    "name": "Second",
                    "description": "## Authored heading\n\n**Authored emphasis**",
                },
            },
            {
                "id": "a",
                "type": "UnfamiliarType",
                "properties": {
                    "name": "First | <unsafe>\n# not a heading",
                    "settings": {"z": True, "a": [1, 2]},
                },
            },
        ],
        "edges": [{"id": "ab", "type": "depends", "source": "a", "target": "b"}],
    }
    (path / "model").mkdir()
    (path / "model" / "model.json").write_text(json.dumps(model))
    service = open_service(path)
    service.dispatch("index_model", {})
    return service


def test_projection_is_stable_under_collection_order_and_uses_no_fixed_ontology(tmp_path):
    service = boot(tmp_path)
    state = service.store.specification_state()
    first = project_specification(state)
    reversed_state = SpecificationState(
        snapshot=state.snapshot.model_copy(
            update={
                "nodes": list(reversed(state.snapshot.nodes)),
                "edges": list(reversed(state.snapshot.edges)),
            }
        ),
        assessments=list(reversed(state.assessments)),
    )
    assert project_specification(reversed_state) == first
    assert first.node_count == 2
    assert first.edge_count == 1
    assert "UnfamiliarType" in first.markdown
    assert "spec/v1" in first.markdown
    assert "depends" in first.markdown
    assert "conformance" in first.markdown
    assert "handler/v1" in first.markdown
    assert "unique" in first.markdown
    assert "Authored emphasis" in first.markdown
    assert "No findings recorded" in first.markdown
    assert "No evidence recorded" in first.markdown
    assert "System" not in first.markdown
    assert "Contract" not in first.markdown
    assert "\\| \\<unsafe\\> \\# not a heading" in first.markdown


def test_generated_heading_lines_and_identity_survive_authored_headings_and_label_changes(tmp_path):
    service = boot(tmp_path)
    first = project_specification(service.store.specification_state())
    lines = first.markdown.splitlines()
    assert len({entry.id for entry in first.outline}) == len(first.outline)
    for entry in first.outline:
        assert lines[entry.line].startswith("#" * entry.level + " ")
    assert next(entry for entry in first.outline if entry.label == "Authored heading").level == 5
    first_ids = [entry.id for entry in first.outline if entry.label != "Authored heading"]
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "b",
                    "type": "UnfamiliarType",
                    "properties": {"name": "Renamed", "description": "New body"},
                }
            ],
        },
    )
    second = project_specification(service.store.specification_state())
    assert [entry.id for entry in second.outline] == first_ids
    assert second.revision == 2
    assert second.state_digest != first.state_digest
    assert "Renamed" in second.markdown


def test_assessment_update_changes_document_digest_without_graph_revision(tmp_path):
    service = boot(tmp_path)
    before = project_specification(service.store.specification_state())
    service.dispatch(
        "submit_assessment",
        {
            "revision": 1,
            "interceptor_id": "review",
            "target_id": "a",
            "result": {
                "status": "pass",
                "findings": [{"summary": "Observed constraint holds"}],
                "evidence": [{"obligation": "conformance", "uri": "artifact://run-42"}],
            },
        },
    )
    after = project_specification(service.store.specification_state())
    assert before.revision == after.revision == 1
    assert before.assessment_digest != after.assessment_digest
    assert before.state_digest != after.state_digest
    assert "Observed constraint holds" in after.markdown
    assert "artifact://run-42" in after.markdown
    assert "completed" in after.markdown
    assert "Assessment revision:" in after.markdown
    assert "target fingerprint:" in after.markdown
    assert "invocation:" in after.markdown


def test_empty_graph_is_useful_and_projector_does_not_change_authored_state(tmp_path):
    service = open_service(tmp_path)
    state = service.store.specification_state()
    before = state.model_dump(mode="json")
    result = project_specification(state)
    assert "No specification nodes have been authored yet" in result.markdown
    assert "No node types are registered" in result.markdown
    assert result.node_count == result.edge_count == 0
    assert state.model_dump(mode="json") == before
    assert service.revision == 0


@pytest.mark.parametrize(
    "profile",
    [
        PresentationProfile(title="Domain handbook"),
        PresentationProfile(title="Another | <title>", label_properties=[], body_properties=[]),
    ],
)
def test_presentation_profile_changes_projection_not_graph(tmp_path, profile):
    service = boot(tmp_path)
    baseline = project_specification(service.store.specification_state())
    custom = project_specification(service.store.specification_state(), profile)
    assert custom.title == profile.title
    assert custom.revision == baseline.revision
    assert custom.assessment_digest == baseline.assessment_digest
    assert custom.state_digest != baseline.state_digest
    assert service.revision == 1


def test_real_example_can_be_projected_without_another_source_of_truth(tmp_path):
    (tmp_path / "model").mkdir()
    example = Path(__file__).parents[1] / "examples" / "model.json"
    (tmp_path / "model" / "model.json").write_text(example.read_text())
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    result = project_specification(service.store.specification_state())
    assert result.node_count == 5
    assert "Authorization contract" in result.markdown
    assert "Idempotency key is required" in result.markdown


@pytest.mark.parametrize(
    "body",
    [
        "```python\nprint('unclosed')",
        "~~~text\n<hostile>\n```\n# still inside tilde fence",
        "   ````python\n```\n## still inside longer fence",
        "```text\n    ```\n### four-space closer is code",
        "```text\n``` not-a-closing-fence\n<script>alert(1)</script>",
        "```text\n~~~\n```\n~~~new unmatched tilde\n# code",
        "```invalid`info\nAn invalid opener is ordinary text.",
        "```text\n`````\nThis already closed successfully.",
    ],
)
def test_body_fence_normalization_preserves_downstream_headings_and_authored_graph(tmp_path, body):
    from markdown_it import MarkdownIt

    service = boot(tmp_path)
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "UnfamiliarType",
                    "properties": {"name": "First", "description": body},
                }
            ],
        },
    )
    state = service.store.specification_state()
    projection = project_specification(state)
    tokens = MarkdownIt("commonmark", {"html": False}).parse(projection.markdown)
    actual_headings = {
        (token.map[0], int(token.tag[1:]))
        for token in tokens
        if token.type == "heading_open" and token.map is not None
    }
    for heading in projection.outline:
        assert (heading.line, heading.level) in actual_headings
    assert any(entry.label == "Second" for entry in projection.outline)
    assert (
        next(node for node in state.snapshot.nodes if node.id == "a").properties["description"]
        == body
    )
    assert service.resource("graph://model/nodes/a")["node"]["properties"]["description"] == body
    assert project_specification(state) == projection


def test_authored_content_precedes_appendix_and_relationships_link_friendly_labels(tmp_path):
    service = boot(tmp_path)
    result = project_specification(service.store.specification_state())
    assert result.markdown.index("## Specification") < result.markdown.index(
        "## Schema reference appendix"
    )
    authored = result.markdown.split("## Schema reference appendix")[0]
    assert "| name |" not in authored
    assert "| settings |" in authored
    second = next(entry for entry in result.outline if entry.label == "Second")
    assert f"[Second](#{second.id})" in authored
    assert "(` b `)" in authored


@pytest.mark.parametrize(
    "body,labels,levels",
    [
        ("## Purpose\n\n### Detail", ["Purpose", "Detail"], [5, 6]),
        ("# Purpose\n\n### Detail\n\n## Other", ["Purpose", "Detail", "Other"], [5, 6, 6]),
        ("Purpose\n=======\n\nDetail\n------", ["Purpose", "Detail"], [5, 6]),
        ("```\n# Code, not outline\n```\n\n## Actual", ["Actual"], [5]),
    ],
)
def test_authored_heading_hierarchy_is_nested_under_node_and_outline_is_parser_aligned(
    tmp_path,
    body,
    labels,
    levels,
):
    from markdown_it import MarkdownIt

    service = boot(tmp_path)
    service.dispatch(
        "apply_changes",
        {
            "expected_revision": 1,
            "changes": [
                {
                    "op": "update_node",
                    "id": "a",
                    "type": "UnfamiliarType",
                    "properties": {"name": "First", "description": body},
                }
            ],
        },
    )
    result = project_specification(service.store.specification_state())
    headings = [entry for entry in result.outline if entry.label in labels]
    assert [entry.label for entry in headings] == labels
    assert [entry.level for entry in headings] == levels
    tokens = MarkdownIt("commonmark", {"html": False}).parse(result.markdown)
    parsed = {
        (token.map[0], int(token.tag[1:]))
        for token in tokens
        if token.type == "heading_open" and token.map is not None
    }
    assert all((entry.line, entry.level) in parsed for entry in result.outline)
    assert not any(entry.label == "Code, not outline" for entry in result.outline)


def test_example_array_requirements_render_as_readable_bullets_not_json(tmp_path):
    (tmp_path / "model").mkdir()
    example = Path(__file__).parents[1] / "examples" / "model.json"
    (tmp_path / "model" / "model.json").write_text(example.read_text())
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    result = project_specification(service.store.specification_state())
    assert "- Idempotency key is required" in result.markdown
    assert "- No duplicate authorization on retry" in result.markdown
    assert '["Idempotency key is required"' not in result.markdown


def test_generic_presentation_groups_order_novel_ontology_without_hiding_metadata(tmp_path):
    node_types = {
        name: {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "section": {"type": "string"},
                "order": {"type": "integer"},
            },
            "required": ["name"],
        }
        for name in ["ShapeOne", "ShapeTwo"]
    }
    records = [
        ("z", "ShapeOne", "Basics", 9007199254740993, "Alphabetically first, numerically later"),
        ("a", "ShapeOne", "Basics", 9007199254740992, "Numerically earlier"),
        ("b", "ShapeTwo", "Basics", 0, "Second type despite zero order"),
        ("r", "ShapeTwo", "Review", 9, "First group"),
        ("x", "ShapeOne", "Appendix", 0, "Unknown group"),
    ]
    nodes = [
        {
            "id": identifier,
            "type": node_type,
            "properties": {"name": label, "section": section, "order": order},
        }
        for identifier, node_type, section, order, label in records
    ]
    nodes.append({"id": "u", "type": "ShapeOne", "properties": {"name": "Missing group"}})
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.json").write_text(
        json.dumps(
            {
                "schema": {"version": "novel/v1", "node_types": node_types, "relations": {}},
                "nodes": nodes,
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    profile = PresentationProfile(
        group_property="section",
        group_order=["Review", "Basics"],
        type_order=["ShapeOne", "ShapeTwo"],
        order_property="order",
    )
    result = project_specification(service.store.specification_state(), profile)
    outline = result.outline[
        : next(
            index
            for index, entry in enumerate(result.outline)
            if entry.label == "Schema reference appendix"
        )
    ]
    assert [entry.label for entry in outline if entry.level == 3] == [
        "Review",
        "Basics",
        "Appendix",
        "Unspecified group",
    ]
    assert [entry.label for entry in outline if entry.level == 4] == [
        "First group",
        "Numerically earlier",
        "Alphabetically first, numerically later",
        "Second type despite zero order",
        "Unknown group",
        "Missing group",
    ]
    authored = result.markdown.split("## Schema reference appendix")[0]
    assert "| section |" in authored
    assert "| order |" in authored
    assert "Registered type:" in authored
    assert service.revision == 1


def test_hidden_presentation_properties_do_not_hide_semantic_status_or_change_source(tmp_path):
    properties = {
        "name": "Visible heading",
        "layout_bucket": "Phase One",
        "layout_rank": 3,
        "status": "draft",
        "internal_notes": "Hidden authored prose.",
        "tags": ["Hidden authored tag."],
    }
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.json").write_text(
        json.dumps(
            {
                "schema": {
                    "version": "1",
                    "relations": {},
                    "node_types": {
                        "NovelEntity": {
                            "type": "object",
                            "properties": {
                                key: {
                                    "type": "array"
                                    if isinstance(value, list)
                                    else "integer"
                                    if isinstance(value, int)
                                    else "string"
                                }
                                for key, value in properties.items()
                            },
                        }
                    },
                },
                "nodes": [{"id": "entry", "type": "NovelEntity", "properties": properties}],
                "edges": [],
            }
        )
    )
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    profile = PresentationProfile(
        group_property="layout_bucket",
        order_property="layout_rank",
        body_properties=["internal_notes"],
        hidden_properties=["layout_bucket", "layout_rank", "internal_notes", "tags", "name"],
    )
    state = service.store.specification_state()
    before = state.model_dump(mode="json")
    result = project_specification(state, profile)
    authored, appendix = result.markdown.split("## Schema reference appendix")
    assert "#### Visible heading" in authored
    assert "### Phase One" in authored
    assert "| status | ` draft ` |" in authored
    assert "| layout\\_bucket |" not in authored
    assert "| layout\\_rank |" not in authored
    assert "Hidden authored prose" not in result.markdown
    assert "Hidden authored tag" not in result.markdown
    assert "layout\\_bucket" in appendix
    assert "layout\\_rank" in appendix
    assert state.model_dump(mode="json") == before
    assert service.resource("graph://model/nodes/entry")["node"]["properties"] == properties


def test_reading_profile_leads_with_authored_prose_and_preserves_meaning_and_provenance(tmp_path):
    from markdown_it import MarkdownIt

    intro_id, detail_id = "internal-purpose-9328", "internal-detail-9328"
    model = {
        "schema": {
            "version": "reading/v1",
            "node_types": {"Narrative": {"type": "object"}},
            "relations": {
                "relates": {
                    "source": ["Narrative"],
                    "target": ["Narrative"],
                    "impact": "target_to_source",
                    "properties": {"type": "object"},
                }
            },
            "interceptors": [
                {
                    "id": "review",
                    "target_type": "Narrative",
                    "handler": "pending",
                    "version": "review/v2",
                    "trigger": "dependency_changed",
                    "evidence_required": ["observed"],
                }
            ],
        },
        "nodes": [
            {
                "id": intro_id,
                "type": "Narrative",
                "properties": {
                    "name": "Readable specification",
                    "description": "Authored opening prose.\n\n## Scope\n\nScope text.",
                    "status": "candidate",
                },
            },
            {
                "id": detail_id,
                "type": "Narrative",
                "properties": {
                    "name": "Supporting element",
                    "description": "Detailed authored prose.",
                    "status": "candidate",
                    "facts": ["A stated fact"],
                },
            },
        ],
        "edges": [
            {
                "id": "internal-edge-9328",
                "type": "relates",
                "source": intro_id,
                "target": detail_id,
                "properties": {"reason": "Authored relationship meaning"},
            }
        ],
    }
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.json").write_text(json.dumps(model))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    service.dispatch(
        "submit_assessment",
        {
            "revision": 1,
            "interceptor_id": "review",
            "target_id": detail_id,
            "result": {
                "status": "fail",
                "findings": [{"reason": "Not demonstrated"}],
                "evidence": [{"obligation": "observed", "uri": "artifact://review/evidence"}],
            },
        },
    )
    state = service.store.specification_state()
    source_before = state.model_dump(mode="json")
    profile = PresentationProfile(
        document_node=intro_id,
        include_identifiers=False,
        compact_properties=True,
        compact_relationships=True,
        body_first=True,
        show_body_labels=False,
        show_empty_assessments=False,
    )
    result = project_specification(state, profile)
    assert result.title == "Readable specification"
    assert result.markdown.startswith("# Readable specification\n\nAuthored opening prose.")
    assert result.markdown.count("# Readable specification\n") == 1
    assert "#### Readable specification" not in result.markdown
    assert "**description**" not in result.markdown
    assert "| Property | Authored value |" not in result.markdown
    assert "| Edge identity |" not in result.markdown
    assert "**status:** candidate" in result.markdown
    assert "- A stated fact" in result.markdown
    assert "Authored relationship meaning" in result.markdown
    assert "→ relates →" in result.markdown
    assert "No assessments recorded for this node" not in result.markdown
    assert intro_id not in result.markdown
    assert detail_id not in result.markdown
    assert "internal-edge-9328" not in result.markdown
    assert "target fingerprint:" not in result.markdown
    assert "invocation:" not in result.markdown
    for meaning in [
        "pending",
        "fail",
        "review/v2",
        "Assessment revision:",
        "Not demonstrated",
        "artifact://review/evidence",
        "observed",
    ]:
        assert meaning in result.markdown
    assert result.markdown.index("Authored opening prose.") < result.markdown.index(
        "Graph revision:"
    )
    assert result.outline[0].level == 1
    assert f"](#{result.outline[0].id})" in result.markdown
    assert next(item for item in result.outline if item.label == "Scope").level == 2
    parsed = {
        (token.map[0], int(token.tag[1:]))
        for token in MarkdownIt("commonmark", {"html": False}).parse(result.markdown)
        if token.type == "heading_open" and token.map is not None
    }
    assert all((item.line, item.level) in parsed for item in result.outline)
    assert state.model_dump(mode="json") == source_before
    assert service.revision == 1


def test_missing_document_node_uses_profile_title_and_keeps_all_authored_nodes(tmp_path):
    service = boot(tmp_path)
    state = service.store.specification_state()
    profile = PresentationProfile(document_node="not-present", title="Fallback title")
    result = project_specification(state, profile)
    assert result.title == "Fallback title"
    assert result.markdown.startswith("# Fallback title")
    assert len([item for item in result.outline if item.level == 4]) == 2


def test_summary_tables_follow_real_outgoing_paths_deduplicate_and_bound_cycles(tmp_path):
    from typed_graph.application.specification import SummaryColumn, SummaryTableProfile

    model = {
        "schema": {
            "version": "1",
            "node_types": {name: {"type": "object"} for name in ["Entry", "Detail", "Rule"]},
            "relations": {
                "has": {"source": ["Entry"], "target": ["Detail"], "impact": "target_to_source"},
                "requires": {"source": ["Detail"], "target": ["Rule"], "impact": "none"},
                "feedback": {"source": ["Rule"], "target": ["Entry"], "impact": "none"},
            },
        },
        "nodes": [
            {"id": "r2", "type": "Entry", "properties": {"name": "Two", "section": "Collection"}},
            {"id": "r1", "type": "Entry", "properties": {"name": "One", "section": "Collection"}},
            {
                "id": "d2",
                "type": "Detail",
                "properties": {
                    "name": "D2",
                    "description": "Second detail",
                    "section": "Collection",
                },
            },
            {
                "id": "d1",
                "type": "Detail",
                "properties": {
                    "name": "D1",
                    "description": "First detail",
                    "section": "Collection",
                },
            },
            {
                "id": "c",
                "type": "Rule",
                "properties": {
                    "name": "C",
                    "description": "Constraint meaning",
                    "section": "Rules",
                },
            },
        ],
        "edges": [
            {"id": "r1d1", "type": "has", "source": "r1", "target": "d1"},
            {"id": "r1d2", "type": "has", "source": "r1", "target": "d2"},
            {"id": "d1c", "type": "requires", "source": "d1", "target": "c"},
            {"id": "d2c", "type": "requires", "source": "d2", "target": "c"},
            {"id": "cr1", "type": "feedback", "source": "c", "target": "r1"},
        ],
    }
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.json").write_text(json.dumps(model))
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    profile = PresentationProfile(
        group_property="section",
        summary_tables=[
            SummaryTableProfile(
                group="Collection",
                row_type="Entry",
                title="Connectivity overview",
                columns=[
                    SummaryColumn(label="Element", link=True),
                    SummaryColumn(
                        label="Two hops", property="description", relation_path=["has", "requires"]
                    ),
                    SummaryColumn(
                        label="Bounded cycle",
                        property="description",
                        relation_path=["has", "requires", "feedback", "has"],
                    ),
                    SummaryColumn(label="Missing property", property="not_declared"),
                ],
            )
        ],
    )
    state = service.store.specification_state()
    source_before = state.model_dump(mode="json")
    result = project_specification(state, profile)
    summary_heading = next(item for item in result.outline if item.label == "Connectivity overview")
    next_heading = next(item for item in result.outline if item.line > summary_heading.line)
    table_text = "\n".join(result.markdown.splitlines()[summary_heading.line : next_heading.line])
    one = next(item for item in result.outline if item.label == "One")
    assert f"[One](#{one.id})" in table_text
    assert table_text.count("Constraint meaning") == 1
    assert "First detail; Second detail" in table_text
    assert "Not recorded" in table_text
    assert "[D1]" not in table_text
    assert "[D2]" not in table_text
    assert table_text.index("[One]") < table_text.index("[Two]")
    assert state.model_dump(mode="json") == source_before
    assert service.revision == 1


@pytest.mark.parametrize(
    "profile",
    [
        {"summary_tables": [{"group": "g", "row_type": "T", "title": "t", "columns": []}]},
        {
            "summary_tables": [
                {
                    "group": "g",
                    "row_type": "T",
                    "title": "t",
                    "columns": [{"label": "c"}] * 9,
                }
            ]
        },
        {
            "summary_tables": [
                {
                    "group": "g",
                    "row_type": "T",
                    "title": "t",
                    "columns": [{"label": "c", "relation_path": ["r"] * 5}],
                }
            ]
        },
        {
            "summary_tables": [
                {
                    "group": "g",
                    "row_type": "T",
                    "title": "t",
                    "columns": [{"label": "c"}],
                }
            ]
            * 9
        },
        {
            "summary_tables": [
                {
                    "group": "g",
                    "row_type": "T",
                    "title": "t",
                    "columns": [{"label": "c", "link": 1}],
                }
            ]
        },
    ],
)
def test_summary_profile_bounds_are_strict(profile):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PresentationProfile.model_validate(profile)
