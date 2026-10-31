# How-to guides

## Author and import

Put mappings with optional `schema`, `nodes` and `edges` keys into `model/*.json`,
`*.yaml` or `*.yml` (subdirectories are supported). Exactly one source may define
the schema. In Markdown, only fenced blocks tagged `graph` are imported; their body
is YAML, so JSON also works:

````markdown
# Human notes
```graph
nodes:
  - id: service-a
    type: System
    properties:
      name: Example
```
````

Call `detect_changes` for a validated preview, then `index_model`. Import is atomic;
duplicate IDs, dangling endpoints, unsupported constraints and source/tool conflicts
leave the revision unchanged. A semantic no-op creates no revision.
Symlinks anywhere inside the imported model tree or graph state are forbidden.
The operator-selected workspace itself is resolved once; tool calls accept no file paths.

## Change safely

Read `get_graph_schema` and `tools/list`. Submit `apply_changes` with the returned
`expected_revision` and a list of discriminated operations. Node updates replace
the complete properties object (not JSON Merge Patch). A batch validates its final
graph; deleting a node also requires deleting its incident edges in the same batch.
On revision conflict, re-read and consciously rebase; do not blindly retry.

Read `graph://model/impact/REVISION` for propagation provenance and
`compare_graphs` for added/removed/updated IDs. Historical resources are immutable
model snapshots.

## Review pending assessments

`get_assessments` returns pending jobs and their ImpactContext. A human or agent
reviews that revision and calls `submit_assessment` with revision, interceptor_id,
target_id and result. Results have status pass/fail/indeterminate, findings and
evidence. Evidence entries name an obligation and URI. Pass without declared and
satisfied evidence obligations is rejected. Late submissions are retained but
marked stale relative to the current graph.

## Recover

Stop the server, preserve `.graph/manifest.json`, `.graph/snapshots` and
`.graph/assessments.jsonl`, remove the SQLite projection if necessary and restart.
Startup rebuilds the index. An invalid or missing committed snapshot is an explicit
error, not a reason to silently reset the user's graph.

## Verify changes

Run the commands in README. The behavior suites cover actual file/SQLite integration,
rollback, revisions, source reconciliation, dependencies and MCP behavior. They favor
table-driven observable outcomes over isolated private-method tests.
