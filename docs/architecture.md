# Explanation: architecture and decisions

## Hexagonal boundaries

- **Domain:** schema compiler, graph validation, atomic in-memory operations and
  deterministic propagation. No IO, MCP, SQLite, model-specific type names or LLM.
- **Application:** graph use cases and assessment lifecycle, depending on domain
  and the Repository protocol.
- **Adapters:** versioned source/files, SQLite projection, MCP transport and explicitly
  operator-configured external MCP handlers. The workspace adapter is the composition
  root. Tests enforce import direction.

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
