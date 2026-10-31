# Specification reader: reference and operation

## What is rendered

The committed graph is the specification. The pure projector uses the canonical
Snapshot, GraphSchema and Assessment models to derive a deterministic Markdown document.
It does not invent prose, call an LLM, edit Markdown files or create another source of truth.

A centralized typed PresentationProfile supplies conventional display choices:
`name` then `title` provides a node label (otherwise its ID); string-valued
`description`, `body` and `markdown` are authored Markdown body fields.
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
The engine contains no special System, Responsibility or Contract rendering rules.

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
index/apply/assessment tools. A schema-defined novel type automatically appears without
frontend or projector ontology changes.

## HTTP interface

| Method/path | Representation |
| --- | --- |
| GET `/` | Local responsive reader |
| GET `/api/specification` | Typed rendered document: revision, assessment/state digests, Markdown, safe HTML, outline and counts |
| GET `/specification.md` | Exact canonical Markdown download |
| GET `/events` | Server-sent document updates; latest document is sent on each connection |
| GET `/app.js`, `/styles.css` | Bundled local assets |

The HTML and Markdown come from one projection, never independent formatting logic
in the browser. The frontend consumes the outline and HTML; it contains no graph
validation or architectural interpretation.

## Live update consistency

One shared server cache compares cheap metadata tokens for the authoritative manifest
and assessment log. It reads and reprojects the graph only when those files change,
not once per client per poll. The default polling interval is **one second**:
updates are near-real-time, not instantaneous. The API factory supports a bounded
poll interval for tests or embedding.

A projection reads one committed snapshot and that revision's assessment records
under the same workspace writer lock. The state digest includes the revision,
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
remote fetches. Code fences remain displayed text. Content Security Policy forbids
external scripts, images, form submission, framing and cross-origin connections.

The HTTP boundary accepts only loopback Host identities and same-origin browser requests;
there is no permissive CORS. Writes and arbitrary path access are not offered.
Do not reverse-proxy this unauthenticated local reader onto a public network.

Projection currently reads a complete committed snapshot and the assessment log after a
change. The cache avoids repetitive idle/per-client work, but this is not a large-graph
incremental document diff engine. The reader is local-only and read-only.
