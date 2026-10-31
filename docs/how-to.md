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

## Author a specification through tools and read it live

The example schema declares a string `description` property on its node types.
Use that field for authored Markdown, with the other required properties in each
full-replacement update. For example, after indexing the unmodified example:

```json
{
  "expected_revision": 1,
  "changes": [{
    "op": "update_node",
    "id": "authorize",
    "type": "Capability",
    "properties": {
      "name": "Authorize a payment",
      "description": "## Acceptance criteria\n- Preserve the caller's idempotency key.\n- Repeated requests return the original outcome.\n\n**Evidence:** attach repeat-request test results to the contract review."
    }
  }]
}
```

Read the current revision before applying this example; do not reuse a stale number.
Run `typed-graph-serve /path/to/the/same/workspace --port 8080` and open the local
reader. This tool-authored Markdown becomes a section of the procedurally generated
specification after the next update poll. Relations and assessments are rendered
from their typed records, not guessed from the prose. Downloaded Markdown is a view,
not an input file to edit or re-import independently.
