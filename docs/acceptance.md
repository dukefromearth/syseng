# Acceptance scope and limitations

Implemented first-release contracts:

- [x] Schema-authored types, relations, JSON Schema 2020-12 properties and readable
  schema/nodes/edges YAML shorthand without hardcoded type names.
- [x] Endpoint/cardinality validation and bounded declarative invariants.
- [x] Dynamic typed apply_changes schema and independent call/result validation.
- [x] Atomic batches, optimistic revisions, no-op detection and immutable history.
- [x] Old/new dependency union, deletion provenance, iterative SCC decomposition and
  deterministic topological condensation scheduling.
- [x] Typed interceptors, revision-scoped pending reviews and evidence-gated results.
- [x] Recoverable versioned source snapshots, incremental SQLite commit deltas, and
  indexed type queries stamped with their exact snapshot revision.
- [x] Three-way JSON/YAML/Markdown import reconciliation and conflict rejection.
- [x] index_model, get_graph_schema, search_graph, query_graph, trace_path, apply_changes,
  detect_changes, get_assessments and compare_graphs, plus explicit submit_assessment.
- [x] graph://model/schema, nodes/{id}, revisions/{revision}, impact/{revision} and
  assessments/{revision} resources.
- [x] Opt-in MCP subscriptions and explicitly configured external MCP handlers,
  including current-revision pending job recovery on restart (at-least-once execution).

Deliberate limits:

- Python/stdio first release, local POSIX filesystem, one workspace per server.
  No authentication/multitenant network service, Windows locking or distributed commits.
- Read-only query DSL is property equality plus type and limit, not SQL, SPARQL or Cypher.
- Invariants are only the documented unique/requires_edge vocabulary. No arbitrary
  expression evaluation, remote schema references or model-selected executable code.
- Impact reports one shortest path per root/target; it does not enumerate every cyclic
  route. SCC components and deterministic condensation ordering are computed per change.
- SQLite indexes power type-filtered queries and normal commits apply deltas; application
  graph traversal currently loads the active graph in memory. Recovery rebuilds the index;
  very large graphs need further
  performance work. Source parsing is incremental by semantic diff, not file watching.
- Handler process separation is not an OS sandbox. Trusted operator allowlists and
  timeouts limit invocation; executable behavior still needs operator trust.
- Evidence is checked for contract compliance and provenance presence, not independently
  attested truth. Agent reviews remain explicit submissions; no LLM is embedded.
- Snapshot files are canonical authored state after import. Original Markdown/YAML
  imports retain formatting and are not silently overwritten by tool changes.
