# Specification reader: reference and operation

## Architecture specification

The optional architecture application module defines the meaning of an architectural
model. Its compiler owns a fixed reading order: purpose; unified metamodel; domain
ontology; system ontology; realization ontology; cross-model relationships;
demonstrating independence; model invariants; resulting minimum architecture.
Requirements, execution scenarios, acceptance criteria and build phases appear in
standard supporting sections when present. Agents author concepts, responsibilities,
contracts and relationships through MCP—not document blocks, layout or reading order.

Each system section resolves its responsibility, behavioral contract, obligations,
applicable requirements, candidate bindings and assessment state from canonical records.
Summary and detail views reference the same facts. Editing a requirement changes every
projection of that requirement without a second prose edit. Fixed explanatory text
explains architectural rules; it never asserts instance-specific measurements or proof.

The metamodel diagram describes the registered architecture role/relation catalog.
Instance diagrams describe actual graph relationships. Proposed bindings remain
candidates; current or stale assessment evidence is shown separately. Structural
validity cannot prove causal correspondence, semantic preservation or performance.

The default view is this human-readable specification. The graph inspector is a
separate secondary view. A workspace without an architecture model reports that no
architecture specification is available and still offers its generic inspector.
An additional concept authored in a supported architectural role appears in the fixed
section for that role without frontend or presentation-profile edits. Arbitrary new
registered graph types remain visible in the inspector; the compiler does not pretend
to infer their architectural meaning.

## Generic graph inspector reference

The generic inspector projects the committed graph. Its pure projector uses the canonical
Snapshot, GraphSchema and Assessment models to derive a deterministic Markdown document.
It does not invent prose, call an LLM, edit Markdown files or create another source of truth.

A centralized typed PresentationProfile supplies conventional display choices:
`name` then `title` provides a node label (otherwise its ID); string-valued
`description`, `body` and `markdown` are authored Markdown body fields; configured
body properties containing arrays of strings render as prose lists.
Other properties are rendered as declared values. Registered types, relations,
constraints, invariants, interceptor obligations and assessment evidence/provenance
remain visible. These names are display conventions, not hardcoded architecture types.
Supply a strict profile JSON through `--profile path/to/presentation.json` or the
pure projector API; absent a profile, the defaults above apply. Profiles contain only
display choices, not specification content. Supported fields are `title`,
`label_properties`, `body_properties`, `group_property`, `group_order`,
`type_order`, `order_property`, and `hidden_properties`. Group/order fields refer
to properties declared by the user's schema. Explicitly hidden property names are
omitted from node presentation only; selected labels, the original graph and schema
declarations remain intact. Unknown groups/types have deterministic lexical fallbacks.
The optional reading-mode fields `document_node`, `body_first`, `show_body_labels`,
`compact_properties`, `compact_relationships`, `include_identifiers` and
`show_empty_assessments` control presentation only. A selected document node supplies
the title and introduction once and is omitted from later groups while retaining its
stable anchor. Compact mode uses linked relationship statements instead of audit tables.
Disabling identifiers hides internal node/edge IDs and assessment hashes in this view;
statuses, revision/handler provenance, findings and evidence remain visible.
Defaults retain the fuller traceability view.

`summary_tables` can declare up to eight graph-derived tables at the start of a group.
Each table defines `group`, `row_type`, `title`, and one to eight `columns`.
A column names its `label`, literal property key (default `name`), optional outgoing
semantic `relation_path` (at most four hops), and optional `link`. Values come from
the same committed graph, not copied prose. Targets are deterministically deduplicated;
cycles are bounded by the path length, and missing values read “Not recorded.”
For example, a System row can read responsibility prose through `owns` and contract
prose through `owns → specified_by` when those relations are authored in the schema.
The generic inspector contains no special System, Responsibility or Contract rendering rules.
The optional architecture compiler intentionally does; it is a separate application module.

Profile changes require a server restart.

Authored specification sections lead the document; schema declarations form a trailing
reference appendix. A selected display label is shown once as its heading rather than
duplicated in the property table. Array properties are procedural lists; relationship
endpoints use friendly labels linked to stable node anchors while preserving IDs.

The projector normalizes authored body headings beneath their node section and closes
unmatched fenced blocks at the body-property boundary. This prevents malformed Markdown
from consuming later generated sections. These are deterministic presentation changes
in the derived Markdown; the graph's original authored text is unchanged.

Generated headings have stable identifier-derived anchors. The server assigns IDs using
source-line metadata, so authored body headings cannot steal a generated section anchor.
Type and node sections are deterministic, not dependent on database row order.
Markdown is downloadable and inspectable without a browser.

## Local process

```sh
typed-graph-serve /path/to/workspace --port 8080 --profile presentation.json
```

The CLI binds only `127.0.0.1`; the port must be 1–65535. The workspace must be the
same workspace the MCP server uses. No separate import happens in the reader.
Invalid/uncommitted authored file edits do not change the displayed specification.
Use `detect_changes` and `index_model` through MCP when importing source edits.

The UI has no mutation endpoint. To change a specification, use the existing MCP
index/apply/assessment tools. A schema-defined novel type automatically appears in the inspector without
frontend changes. Architecture concepts use the canonical architecture role vocabulary.

## HTTP interface

| Method/path | Representation |
| --- | --- |
| GET `/` | Local responsive reader |
| GET `/api/specification` | Typed rendered document: revision, assessment/state digests, Markdown, safe HTML, outline and counts |
| GET `/specification.md` | Exact compiled specification Markdown download |
| GET `/inspector.md` | Generic graph inspector Markdown download |
| GET `/events` | Server-sent document updates; latest document is sent on each connection |
| GET `/app.js`, `/reader-diagrams.js`, `/styles.css` | Bundled local assets |

The HTML and Markdown come from one projection, never independent formatting logic
in the browser. The frontend consumes the outline and HTML; it contains no graph
validation or architectural interpretation.

## Live update consistency

One shared server cache compares cheap metadata tokens for the authoritative manifest
and assessment log. It reads and reprojects the graph only when those files change,
not once per client per poll. The default polling interval is **one second**:
updates are near-real-time, not instantaneous. The API factory supports a bounded
poll interval for tests or embedding.

A projection reads one committed snapshot and the latest recorded assessment for each
interceptor/target pair under the same workspace writer lock. Older records retain
their originating revision and are explicitly labeled **stale**, including unresolved
findings after an unrelated edit. They are never promoted to current verification.
A newer pending or completed assessment supersedes the older record; late completion
of an older revision cannot displace it. Assessments for removed targets remain in an
explicit absent-node section. MCP assessment retrieval stays revision-specific.
The state digest includes the revision,
assessment content and projected Markdown. Consequently an assessment-only completion
updates the reader without inventing a graph revision. Semantic no-ops do not produce
endless duplicate events. Reconnecting clients receive the latest projection, including
changes made by an MCP process while disconnected.

The change token is sampled before the locked state read; a concurrent commit cannot
disappear between initial rendering and subscription. Slow client writes do not hold
the cache condition lock. Polling errors retain the last valid document, report status,
and retry; recovered state returns the reader to live status. Process shutdown cancels
polling and bounds graceful waiting for open event streams.

## Safety and limits

Graph-supplied HTML is disabled in Markdown rendering; generated HTML is additionally
sanitized to a small allowlist. Script/event attributes and unsafe link protocols are
not executable. Images become inert alternative-text descriptions rather than triggering
remote fetches. Authored code fences remain displayed text; only graph-derived diagram descriptors
are rendered as diagrams. Content Security Policy forbids
external scripts, images, form submission, framing and cross-origin connections.

The HTTP boundary accepts only loopback Host identities and same-origin browser requests;
there is no permissive CORS. Writes and arbitrary path access are not offered.
Do not reverse-proxy this unauthenticated local reader onto a public network.

Projection currently reads a complete committed snapshot and the assessment log after a
change. The cache avoids repetitive idle/per-client work, but this is not a large-graph
incremental document diff engine. The reader is local-only and read-only.

## Generic inspector diagram profiles

A profile may declare up to eight `diagrams`. A diagram selects a bounded subgraph of the committed graph, either direct
relationships or explicitly selected two-hop paths. It cannot introduce an architectural relationship,
claim a binding is verified, or infer a missing connection. The generated Mermaid
source is included in the Markdown download and can be inspected independently.

Each diagram has these strict fields:

- `id`, `title`: view identity and display title, not graph facts.
- `node_types`, `node_ids`: optional selection lists. Empty means unrestricted;
  nonempty filters intersect.
- `relations`: optional direct relation-type selection; empty means every relation
  between selected nodes. Edges to unselected endpoints are not drawn.
- `relation_path`: optional list of exactly two relation types. When supplied, it
  replaces direct-edge selection with two-hop paths between selected endpoints.
  The intermediate node supplies each arrow label. No path is invented from prose.
  Omit `relations` in path mode; it is a direct-mode selector.
- `group`: optional node filter against the profile's `group_property`.
- `placement_group`: optional display location at the beginning of an existing group.
  An omitted or unavailable group places the diagram before the specification groups.
- `direction`: `LR` (default) or `TB`.
- `max_nodes`: 1–60, default 30. `max_edges`: 1–120, default 60.

For example, a model with `System` and `ExchangeContract` types can select those types
and its `produces` / `consumed_by` relationships. Another model can use completely
different types without modifying the reader. Selection order and bounds are
stable. Explicit omission counts appear when bounds are exceeded. Every node still
has its complete record below, including newly authored types outside any diagram.
Diagram labels are bounded display text; complete labels remain in node records.

Architecture catalog diagrams additionally report `schema_roles` and
`schema_relations`; their instance `node_ids` and `edge_ids` are empty. This distinguishes
a metamodel definition from a claim about instances.

The response's `diagrams` entries contain `id`, `title`, generated Mermaid `source`,
`node_ids`, `edge_ids`, omission counts and the canonical Markdown source `line`.
Path mode additionally records `paths`: each has `source`, `target`, `via` and the
original pair of `edge_ids`. Identical source/target/via paths are deduplicated with
a deterministic representative edge pair. `max_edges` bounds displayed paths;
`omitted_path_count` counts omitted paths between the displayed nodes. Complete
parallel edges and any omitted nodes remain in their graph records.
Only these generated fences become diagram placeholders. Authored Mermaid fences,
HTML, directives and click handlers remain inert text. Graph IDs become hashed
Mermaid IDs, and graph labels are escaped as quoted Mermaid text. The bundled local
renderer displays only generated diagrams; no diagram service or external asset is
contacted. A diagram that fails to render retains its readable source fallback.

## Inspector disclosure profiles

Set `collapse_nodes` and/or `collapse_schema` to `true` to display node records and
the schema appendix as expandable sections. Defaults are `false`. Their headings
remain visible and linked; the records are not removed from the document. Group
headings, summary tables and focused diagrams stay outside collapsed node details.
The Markdown download always contains the complete specification.

The response's `disclosures` records carry stable section `id`, `title`, `start_line`
and exclusive `end_line`. The safe server renderer applies disclosure markup only
at those generated sections. Authored HTML cannot manufacture a disclosure section.
The reader preserves open sections across updates and expands enclosing details
when a user follows an outline or internal reference link.

## Inspector typography profiles

`show_type_metadata: false` hides repeated registered-type labels in node records;
the schema appendix and graph still retain types. `show_projection_metadata: false`
omits the duplicate revision/count paragraph and projection boilerplate from the
document body; the reader toolbar still displays the revision and counts. Both
default to `true`, and neither setting hides authored status or assessment results.

`body_properties` also accepts properties whose values are arrays of strings. Those
values render as bullet prose. With `show_body_labels: false`, multiple body fields
remain unlabeled; their content is still present. Other property values retain their
ordinary rendering. Compact relationships group endpoints by direction and relation:
“Outgoing · uses concept” and “Incoming · uses concept” retain the original relation
direction rather than inventing inverse semantics. Relation underscores become spaces
for readability. Each endpoint retains its edge properties and, when enabled, IDs.
