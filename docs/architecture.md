# Explanation: architecture and decisions

## Hexagonal boundaries

- **Domain:** schema compiler, graph validation, atomic in-memory operations and
  deterministic propagation. No IO, MCP, SQLite, model-specific type names or LLM.
- **Application:** graph use cases and assessment lifecycle, depending on domain
  and the Repository protocol.
- **Adapters:** versioned source/files, SQLite projection, MCP transport and explicitly
  operator-configured external MCP handlers. The workspace adapter is the composition
  root. Tests enforce import direction.

## Define once, derive the boundaries

`domain/models.py` owns strict Pydantic v2 engine contracts: identities/revisions,
nodes/edges, registered schema structure, operations, impacts, assessment results and
provenance. User-authored node property schemas remain arbitrary supported JSON Schema;
the engine's closed vocabulary does not hardcode a user's architecture ontology.

`application/contracts.py` registers each tool once with its request/result model and
handler binding. Dispatch, MCP discovery, static schemas and runtime validation derive
from that catalog. Dynamic mutation schemas specialize the canonical operation models
with registered types and authored property schemas; no parallel handwritten tool shapes
are maintained. Strict validation rejects coercion, extra fields and malformed operations
even when a later operation would erase them.

`domain/resources.py` owns resource identities, URI codecs, templates and resolver
bindings. Persistence uses the same typed Snapshot/Assessment models as the application;
SQLite and authored JSON codecs do not independently define their semantic contracts.
Typed repository ports and model attributes retain these guarantees inside the core,
rather than applying a typed facade around untyped dictionaries. JSON values remain only
at actual extensibility boundaries (authored schemas, user properties and finding data).

This refactor improves maintainability and change scalability. It does **not** claim to
remove full-snapshot IO or in-memory graph traversal costs; large-graph performance limits
remain listed in the acceptance document.

The five primitives are Node (identity, registered type, validated properties),
Edge (identity, declared relation and endpoints), Schema (authoring vocabulary),
Interceptor (typed target and handler contract), and Assessment (derived revision-
specific provenance). Interceptors never modify authored model state.

## ADR 001: snapshots, not impossible two-store transactions

The authoritative model after import is an immutable JSON document under
`.graph/snapshots/{revision}.json`. The fsynced, atomically replaced
`.graph/manifest.json` is the commit point. Snapshot write precedes manifest
replacement. SQLite is a rebuildable projection, never a second authority. Normal commits update
only changed node/edge rows and insert the new revision. Type-filtered search uses
the SQLite type index with parameterized SQL; equality/text filters are then applied
before the limit. Query revisions and results are read under one lock.

A crash before manifest replacement leaves an ignored orphan snapshot. A crash
after manifest replacement is recovered by rebuilding SQLite on next open. Historical
reads reject future/uncommitted snapshots. Cross-process advisory locks serialize
commit and assessment writes; expected revisions reject stale proposals. This relies
on local POSIX filesystem rename/fsync/lock guarantees, not network filesystems.
Only one server process per workspace is supported operationally.

The durable assessment JSONL log is separately atomically replaced and indexed.
A graph commit may succeed before pending assessments are recorded; retrieval
reconstructs missing pending jobs idempotently from the committed impact. Assessment
execution is not part of graph atomicity and must not roll back a valid graph commit.

## ADR 002: authored inputs are three-way imports

`model/` contains JSON, YAML or Markdown imports. The current snapshot is also an
authored, inspectable JSON model. `apply_changes` writes a new canonical snapshot,
not potentially lossy round-trips through YAML/Markdown. Import fingerprints and the
last imported semantic baseline are retained. Subsequent source edits three-way
merge against that baseline and the current canonical graph: disjoint changes
survive and conflicting edits fail. No-op imports update import metadata without
inventing a graph revision. Duplicate identities across sources are errors.

Do not manually modify `.graph`. Back up the whole directory; delete only
`index.sqlite3` to force reconstruction. The import directory is not an automatically
rewritten export. This explicit distinction preserves comments and human formatting
without claiming source files and SQLite can atomically co-commit.

## ADR 003: bounded, deterministic propagation and evidence

Impact traverses the union of old and new dependency directions, retaining deletion
provenance. Cycles terminate through visited-node deduplication; each target receives
one shortest path per changed root, not exponential enumeration of every path.
Iterative Kosaraju decomposition identifies strongly connected components; a stable
topological ordering of their condensation graph determines scheduling. Impact records
include component membership and identity. Scheduling is deduplicated by revision,
interceptor and target (including cycles).

Assessments start pending/indeterminate. Handler completion is not verification:
pass requires schema-declared obligations and matching evidence entries. Evidence
references are provenance supplied by the reviewer/handler, not independently proved
by this server. An older revision's result remains stale even if it arrives later.
No implicit model mutation or external invocation follows from a model definition.

## Extending the engine without parallel definitions

- Add a tool's strict request/result classes and one `_register(ToolSpec(...))`
  declaration in the tool catalog; implement the correspondingly typed application
  method. Startup checks its request/result annotations against that registration.
  MCP listing, validation and output schemas need no separate entry. If a tool needs
  authored-schema specialization, register its schema callback with the same ToolSpec.
- Add a resource's identity category and resolver binding in ResourceSpec. Parsing,
  rendering, accepted identity shape and URI templates consume that registration.
- Add registered model node types or relations only to authored schema files. The
  mutation compiler specializes canonical operation models automatically.
- Engine status/direction vocabularies are explicit StrEnums; operation/invariant
  tags are discriminated unions. The shared omission-only field convention permits
  omitted optional fields without silently accepting explicit JSON null or coercion.
- History derives its change union from the mutation union plus the import event.
  Assessment identity, empty relation-property defaults, dependency adjacency and
  changed-node calculation each have one implementation reused by their consumers.

## ADR 004: the specification reader is a projection

The tools continue to author the graph. A pure typed projector reads one Snapshot plus
that revision's Assessments and produces canonical Markdown with outline/provenance.
The HTTP adapter renders that exact Markdown through a non-HTML Markdown parser and
sanitizer; the thin browser receives the result and adds no graph rules.

A SpecificationSource port exposes an opaque cheap change token and a consistent state
read. The file adapter centralizes paths, compares manifest/assessment-log metadata and
reads both under the writer lock. One shared server cache performs projection only after
change, compares semantic digests and broadcasts to subscribers. Reconnect sends the
latest state; polling errors preserve the last valid document and remain visible.
Presentation profiles select grouping and graph-derived summaries but never author
another model or copy contract prose into frontend code. All HTTP controls remain
read-only and loopback-bound.
