"""Pure deterministic specification projection from the authoritative typed graph.

The Markdown is a view, never a separately editable model or an LLM interpretation.
Authored Markdown fields remain Markdown; HTML adapters must disable raw HTML.
An unclosed top-level fenced code block is closed at each body-field boundary
in the derived view only, so authored text cannot absorb subsequent sections.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Annotated

from markdown_it import MarkdownIt
from pydantic import Field, JsonValue

from typed_graph.domain.models import (
    Assessment,
    GraphSchema,
    Identifier,
    JsonObject,
    JsonSchema,
    Node,
    Omittable,
    Revision,
    Snapshot,
    StrictModel,
    dump_wire,
)


class SpecificationState(StrictModel):
    snapshot: Snapshot
    assessments: list[Assessment]


class SummaryColumn(StrictModel):
    label: Identifier
    property: Identifier = "name"
    relation_path: Annotated[list[Identifier], Field(max_length=4)] = Field(default_factory=list)
    link: bool = False


class SummaryTableProfile(StrictModel):
    group: Identifier
    row_type: Identifier
    title: Identifier
    columns: Annotated[list[SummaryColumn], Field(min_length=1, max_length=8)]


class PresentationProfile(StrictModel):
    title: Identifier = "Architectural specification"
    group_property: Omittable[Identifier] = None
    group_order: list[Identifier] = Field(default_factory=list)
    type_order: list[Identifier] = Field(default_factory=list)
    order_property: Omittable[Identifier] = None
    hidden_properties: list[Identifier] = Field(default_factory=list)
    document_node: Omittable[Identifier] = None
    include_identifiers: bool = True
    compact_properties: bool = False
    compact_relationships: bool = False
    body_first: bool = False
    show_body_labels: bool = True
    show_empty_assessments: bool = True
    summary_tables: Annotated[list[SummaryTableProfile], Field(max_length=8)] = Field(
        default_factory=list
    )
    label_properties: list[Identifier] = Field(default_factory=lambda: ["name", "title"])
    body_properties: list[Identifier] = Field(
        default_factory=lambda: ["description", "body", "markdown"]
    )


class OutlineEntry(StrictModel):
    id: Identifier
    label: str
    level: Annotated[int, Field(ge=1, le=6)]
    line: Annotated[int, Field(ge=0)]


class MarkdownSpecification(StrictModel):
    revision: Revision
    assessment_digest: Identifier
    state_digest: Identifier
    title: str
    markdown: str
    outline: list[OutlineEntry]
    node_count: Annotated[int, Field(ge=0)]
    edge_count: Annotated[int, Field(ge=0)]


def _canonical(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _anchor(identity: str) -> str:
    return f"spec-{_digest(identity)[:24]}"


def _text(value: str) -> str:
    # Generated labels cannot create Markdown structure, HTML, links, or table columns.
    return re.sub(
        r"([\\`*_{}\[\]()#+.!|<>~-])", r"\\\1", value.replace("\r", " ").replace("\n", " ")
    )


def _code(value: JsonValue) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    text = text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    runs = re.findall(r"`+", text)
    fence = "`" * (max(map(len, runs), default=0) + 1)
    return f"{fence} {text} {fence}"


def _body_lines(value: str) -> list[str]:
    """Close only an unmatched CommonMark fence; never mutate authored graph text."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    active_character: str | None = None
    active_length = 0
    for line in lines:
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match is None:
            continue
        fence, remainder = match.groups()
        if active_character is None:
            # A backtick opener's info string cannot itself contain a backtick.
            if fence[0] == "`" and "`" in remainder:
                continue
            active_character, active_length = fence[0], len(fence)
        elif (
            fence[0] == active_character
            and len(fence) >= active_length
            and not remainder.strip(" \t")
        ):
            active_character, active_length = None, 0
    if active_character is not None:
        lines.append(active_character * active_length)
    return lines


def _summary(schema: JsonSchema) -> str:
    if isinstance(schema, bool):
        return "Any JSON value allowed." if schema else "No JSON value allowed."
    pieces = []
    for keyword in sorted(schema):
        if keyword in {"properties", "$defs", "description", "title", "examples", "default"}:
            continue
        pieces.append(f"{_text(keyword)}: {_code(schema[keyword])}")
    if "description" in schema:
        pieces.append(_text(str(schema["description"])))
    return "; ".join(pieces) or "No additional assertions declared."


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.outline: list[OutlineEntry] = []

    def heading(self, label: str, level: int, identity: str) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")
        self.outline.append(
            OutlineEntry(
                id=_anchor(identity),
                label=label,
                level=level,
                line=len(self.lines),
            )
        )
        self.lines.extend([f"{'#' * level} {_text(label)}", ""])

    def body(self, value: str, identity: str, node_level: int = 4) -> None:
        lines = _body_lines(value)
        tokens = MarkdownIt("commonmark", {"html": False}).parse("\n".join(lines))
        headings = [
            (index, token)
            for index, token in enumerate(tokens)
            if token.type == "heading_open" and token.map is not None
        ]
        minimum = min((int(token.tag[1:]) for _, token in headings), default=1)
        for occurrence, (index, token) in enumerate(headings):
            assert token.map is not None
            start = token.map[0]
            inline = tokens[index + 1]
            level = min(6, node_level + 1 + int(token.tag[1:]) - minimum)
            # Keep authored inline Markdown but normalize its structural heading depth.
            lines[start] = f"{'#' * level} {inline.content}"
            if token.markup in {"=", "-"}:
                lines[start + 1] = ""
            label = (
                "".join(
                    child.content if child.type != "softbreak" else " "
                    for child in (inline.children or [])
                    if child.type in {"text", "code_inline", "softbreak", "html_inline"}
                )
                or inline.content
            )
            self.outline.append(
                OutlineEntry(
                    id=_anchor(f"{identity}:heading:{occurrence}"),
                    label=label,
                    level=level,
                    line=len(self.lines) + start,
                )
            )
        self.lines.extend(lines)
        self.lines.append("")

    def paragraph(self, text: str) -> None:
        self.lines.extend([text, ""])

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.lines.append("| " + " | ".join(headers) + " |")
        self.lines.append("| " + " | ".join("---" for _ in headers) + " |")
        self.lines.extend("| " + " | ".join(row) + " |" for row in rows)
        self.lines.append("")


def _schema_section(writer: _Writer, schema: GraphSchema) -> None:
    writer.heading("Schema reference appendix", 2, "schema")
    writer.paragraph(f"Schema version: {_code(schema.version)}.")
    if not schema.node_types:
        writer.paragraph("No node types are registered.")
    for name, definition in sorted(schema.node_types.items()):
        writer.heading(f"Type: {name}", 3, f"schema-type:{name}")
        writer.paragraph(_summary(definition))
        if isinstance(definition, dict):
            properties = definition.get("properties")
            required = definition.get("required", [])
            if isinstance(properties, dict) and properties:
                rows = []
                for key, value in sorted(properties.items()):
                    description = (
                        _summary(value) if isinstance(value, (dict, bool)) else _code(value)
                    )
                    rows.append(
                        [
                            _text(key),
                            "yes" if isinstance(required, list) and key in required else "no",
                            description,
                        ]
                    )
                writer.table(["Property", "Required", "Declared constraints"], rows)
    writer.heading("Relations", 3, "schema-relations")
    if schema.relations:
        rows = []
        for name, relation in sorted(schema.relations.items()):
            limits = (
                _code(dump_wire(relation.cardinality))
                if relation.cardinality is not None
                else "No bounds declared"
            )
            rows.append(
                [
                    _text(name),
                    ", ".join(map(_text, sorted(relation.source))),
                    ", ".join(map(_text, sorted(relation.target))),
                    _code(relation.impact.value),
                    limits,
                    _summary(relation.property_schema),
                ]
            )
        writer.table(
            [
                "Relation",
                "Source types",
                "Target types",
                "Impact",
                "Cardinality",
                "Edge properties",
            ],
            rows,
        )
    else:
        writer.paragraph("No relations are registered.")
    writer.heading("Invariants", 3, "schema-invariants")
    if schema.invariants:
        rows = [
            [_code(invariant.kind), _code(dump_wire(invariant))]
            for invariant in sorted(schema.invariants, key=lambda item: _canonical(dump_wire(item)))
        ]
        writer.table(["Invariant", "Declared constraint"], rows)
    else:
        writer.paragraph("No graph invariants are declared.")
    writer.heading("Interceptors", 3, "schema-interceptors")
    if schema.interceptors:
        writer.table(
            ["Interceptor", "Target type", "Trigger", "Handler / version", "Evidence obligations"],
            [
                [
                    _text(item.id),
                    _text(item.target_type),
                    _code(item.trigger),
                    f"{_code(item.handler)} / {_code(item.version)}",
                    ", ".join(_code(value) for value in sorted(item.evidence_required))
                    or "None declared",
                ]
                for item in sorted(schema.interceptors, key=lambda item: item.id)
            ],
        )
    else:
        writer.paragraph("No interceptors are declared.")


def _node_label(node: Node, profile: PresentationProfile) -> str:
    for property_name in profile.label_properties:
        value = node.properties.get(property_name)
        if isinstance(value, str) and value.strip():
            return value
    return node.id


def _presentation_groups(
    nodes: list[Node],
    profile: PresentationProfile,
) -> list[tuple[str, str, list[Node]]]:
    type_rank = {name: index for index, name in reversed(list(enumerate(profile.type_order)))}

    def node_order(node: Node) -> tuple[int, bool, int | float, str, str, str]:
        value = node.properties.get(profile.order_property) if profile.order_property else None
        numeric = type(value) in {int, float} and not (
            isinstance(value, float) and math.isnan(value)
        )
        number = value if isinstance(value, (int, float)) and numeric else 0
        return (
            type_rank.get(node.type, len(type_rank)),
            not numeric,
            number,
            node.type,
            _node_label(node, profile),
            node.id,
        )

    if profile.group_property is None:
        types = sorted(
            {node.type for node in nodes},
            key=lambda name: (type_rank.get(name, len(type_rank)), name),
        )
        return [
            (
                name,
                f"instance-type:{name}",
                sorted(
                    (node for node in nodes if node.type == name),
                    key=node_order
                    if profile.order_property or profile.type_order
                    else lambda node: node.id,
                ),
            )
            for name in types
        ]
    groups: dict[str | None, list[Node]] = {}
    for node in nodes:
        value = node.properties.get(profile.group_property)
        key = value if isinstance(value, str) else None
        groups.setdefault(key, []).append(node)
    rank = {name: index for index, name in reversed(list(enumerate(profile.group_order)))}
    return [
        (
            key if key else ("Empty group" if key == "" else "Unspecified group"),
            _canonical(["group", profile.group_property, key]),
            sorted(groups[key], key=node_order),
        )
        for key in sorted(
            groups,
            key=lambda value: (
                rank.get(value, len(rank)) if value is not None else len(rank),
                value is None,
                value or "",
            ),
        )
    ]


def _node_link(node: Node, profile: PresentationProfile) -> str:
    link = f"[{_text(_node_label(node, profile))}](#{_anchor(f'node:{node.id}')})"
    return f"{link} ({_code(node.id)})" if profile.include_identifiers else link


def _assessment_section(
    writer: _Writer,
    assessment: Assessment,
    revision: int,
    include_identifiers: bool = True,
) -> None:
    stale = assessment.revision != revision
    summary = (
        f"**{_text(assessment.interceptor_id)}** — {_code(assessment.result.status.value)} "
        f"({_code(assessment.state.value)}; {'stale' if stale else 'current revision'}). "
        f"Assessment revision: {_code(assessment.revision)}; handler version: "
        f"{_code(assessment.handler_version)}."
    )
    if include_identifiers:
        summary += (
            f" Target: {_code(assessment.target_id)}; target fingerprint: "
            f"{_code(assessment.target_fingerprint)}; invocation: "
            f"{_code(assessment.context.invocation_id)}."
        )
    writer.paragraph(summary)
    if assessment.framework_failure:
        writer.paragraph("The framework recorded a handler failure; this is not verification.")
    if assessment.result.findings:
        writer.table(
            ["Finding", "Recorded details"],
            [
                [str(index), _code(finding)]
                for index, finding in enumerate(assessment.result.findings, start=1)
            ],
        )
    else:
        writer.paragraph("No findings recorded.")
    if assessment.result.evidence:
        writer.table(
            ["Evidence obligation", "Recorded URI"],
            [
                [_text(evidence.obligation), _code(evidence.uri)]
                for evidence in sorted(
                    assessment.result.evidence, key=lambda item: (item.obligation, item.uri)
                )
            ],
        )
    else:
        writer.paragraph("No evidence recorded.")


def _summary_table(
    writer: _Writer,
    table: SummaryTableProfile,
    rows: list[Node],
    snapshot: Snapshot,
    identity: str,
) -> None:
    selected = [node for node in rows if node.type == table.row_type]
    if not selected:
        return
    node_map = {node.id: node for node in snapshot.nodes}
    adjacency: dict[tuple[str, str], set[str]] = {}
    for edge in snapshot.edges:
        adjacency.setdefault((edge.source, edge.type), set()).add(edge.target)

    def cell(row: Node, column: SummaryColumn) -> str:
        reached = {row.id}
        for relation in column.relation_path:
            reached = {
                target for source in reached for target in adjacency.get((source, relation), set())
            }
        values: list[str] = []
        for identifier in sorted(reached):
            node = node_map[identifier]
            if column.property not in node.properties:
                values.append("Not recorded")
                continue
            value = node.properties[column.property]
            displayed = _text(value) if isinstance(value, str) else _code(value)
            if column.link:
                displayed = f"[{displayed}](#{_anchor(f'node:{identifier}')})"
            values.append(displayed)
        return "; ".join(values) if values else "Not recorded"

    writer.heading(table.title, 4, identity)
    writer.table(
        [_text(column.label) for column in table.columns],
        [[cell(node, column) for column in table.columns] for node in selected],
    )


def _node_content(
    writer: _Writer,
    node: Node,
    snapshot: Snapshot,
    assessments: list[Assessment],
    profile: PresentationProfile,
    node_level: int,
) -> None:
    """One content rule for an introductory document node and regular node sections."""
    label = _node_label(node, profile)
    label_key = next(
        (
            key
            for key in profile.label_properties
            if isinstance(node.properties.get(key), str) and node.properties[key] == label
        ),
        None,
    )
    body_keys = {
        key for key in profile.body_properties if isinstance(node.properties.get(key), str)
    }
    values: JsonObject = {
        key: value
        for key, value in node.properties.items()
        if key not in body_keys and key != label_key and key not in profile.hidden_properties
    }

    def properties() -> None:
        if profile.include_identifiers:
            writer.paragraph(
                f"Node identity: {_code(node.id)}. Registered type: {_code(node.type)}."
            )
        elif not profile.compact_properties:
            writer.paragraph(f"Registered type: {_code(node.type)}.")
        scalar_values = {key: value for key, value in values.items() if not isinstance(value, list)}
        if profile.compact_properties:
            entries = [] if profile.include_identifiers else [f"**Type:** {_text(node.type)}"]
            entries.extend(
                f"**{_text(key)}:** " + (_text(value) if isinstance(value, str) else _code(value))
                for key, value in sorted(scalar_values.items())
            )
            if entries:
                writer.paragraph(" · ".join(entries))
        elif scalar_values:
            writer.table(
                ["Property", "Authored value"],
                [[_text(key), _code(value)] for key, value in sorted(scalar_values.items())],
            )
        for key, value in sorted(values.items()):
            if isinstance(value, list):
                writer.paragraph(f"**{_text(key)}**")
                if value:
                    writer.lines.extend(
                        "- " + (_text(item) if isinstance(item, str) else _code(item))
                        for item in value
                    )
                    writer.lines.append("")
                else:
                    writer.paragraph("Empty list.")

    def body() -> None:
        selected = [
            key
            for key in dict.fromkeys(profile.body_properties)
            if key in body_keys and key not in profile.hidden_properties
        ]
        for key in selected:
            if profile.show_body_labels or len(selected) > 1:
                writer.paragraph(f"**{_text(key)}**")
            value = node.properties[key]
            assert isinstance(value, str)
            writer.body(value, _canonical(["body", node.id, key]), node_level)

    if profile.body_first or node_level == 1:
        body()
        properties()
    else:
        properties()
        body()
    node_map = {item.id: item for item in snapshot.nodes}
    relationships = sorted(
        (edge for edge in snapshot.edges if node.id in {edge.source, edge.target}),
        key=lambda edge: (edge.type, edge.source, edge.target, edge.id),
    )
    if profile.compact_relationships:
        for edge in relationships:
            text = (
                f"{_node_link(node_map[edge.source], profile)} → {_text(edge.type)} → "
                f"{_node_link(node_map[edge.target], profile)}"
            )
            if profile.include_identifiers:
                text += f" (edge {_code(edge.id)})"
            if edge.properties:
                text += f" — {_code(edge.properties)}"
            writer.paragraph(text)
    elif relationships:
        headers = ["Relation", "Source", "Target", "Properties"]
        if profile.include_identifiers:
            headers.insert(0, "Edge identity")
        rows = [
            ([_code(edge.id)] if profile.include_identifiers else [])
            + [
                _text(edge.type),
                _node_link(node_map[edge.source], profile),
                _node_link(node_map[edge.target], profile),
                _code(edge.properties),
            ]
            for edge in relationships
        ]
        writer.table(headers, rows)
    else:
        writer.paragraph("No relationships recorded.")
    relevant = [assessment for assessment in assessments if assessment.target_id == node.id]
    if relevant:
        writer.heading("Assessments", min(6, node_level + 1), f"assessments:{node.id}")
        for assessment in relevant:
            _assessment_section(writer, assessment, snapshot.revision, profile.include_identifiers)
    elif profile.show_empty_assessments:
        writer.paragraph("No assessments recorded for this node.")


def project_specification(
    state: SpecificationState,
    profile: PresentationProfile | None = None,
) -> MarkdownSpecification:
    """Render known facts only; entity order never changes the projected document."""
    profile = profile if profile is not None else PresentationProfile()
    snapshot = state.snapshot
    assessments = sorted(
        state.assessments, key=lambda item: (item.key, _canonical(dump_wire(item)))
    )
    assessment_digest = _digest(_canonical([dump_wire(item) for item in assessments]))
    writer = _Writer()
    intro = next((node for node in snapshot.nodes if node.id == profile.document_node), None)
    title = _node_label(intro, profile) if intro is not None else profile.title
    writer.heading(title, 1, f"node:{intro.id}" if intro is not None else "document")
    if intro is not None:
        _node_content(writer, intro, snapshot, assessments, profile, 1)
    writer.paragraph(
        f"Graph revision: {_code(snapshot.revision)}. "
        f"Nodes: {len(snapshot.nodes)}. Edges: {len(snapshot.edges)}."
    )
    writer.paragraph(
        "This specification is a deterministic view of the authored graph. "
        "Recorded assessments are revision-specific results, not independent proof of correctness."
    )
    writer.heading("Specification", 2, "specification")
    if not snapshot.nodes:
        writer.paragraph("No specification nodes have been authored yet.")
    regular_nodes = [node for node in snapshot.nodes if intro is None or node.id != intro.id]
    for group_label, group_identity, nodes in _presentation_groups(regular_nodes, profile):
        writer.heading(group_label, 3, group_identity)
        for index, table in enumerate(profile.summary_tables):
            if table.group == group_label:
                _summary_table(
                    writer,
                    table,
                    nodes,
                    snapshot,
                    _canonical(["summary-table", group_identity, index]),
                )
        for node in nodes:
            writer.heading(_node_label(node, profile), 4, f"node:{node.id}")
            _node_content(writer, node, snapshot, assessments, profile, 4)
    orphaned = [
        item for item in assessments if item.target_id not in {n.id for n in snapshot.nodes}
    ]
    if orphaned:
        writer.heading("Assessments for absent nodes", 2, "orphaned-assessments")
        for assessment in orphaned:
            _assessment_section(writer, assessment, snapshot.revision, profile.include_identifiers)
    _schema_section(writer, snapshot.schema_definition)
    markdown = "\n".join(writer.lines).rstrip() + "\n"
    return MarkdownSpecification(
        revision=snapshot.revision,
        assessment_digest=assessment_digest,
        state_digest=_digest(f"{snapshot.revision}\n{assessment_digest}\n{markdown}"),
        title=title,
        markdown=markdown,
        outline=writer.outline,
        node_count=len(snapshot.nodes),
        edge_count=len(snapshot.edges),
    )
