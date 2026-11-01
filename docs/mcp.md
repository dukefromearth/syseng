# MCP transport reference

Run `typed-graph /absolute/workspace` using an MCP client's stdio configuration.
The server binds exactly one workspace. Install requires official Python SDK
`mcp>=2,<3`; tested SDK 2.3.0 negotiates protocol `2026-07-28`. The SDK owns
protocol negotiation, discovery and legacy negotiation; this server does not
pretend an older SDK implements newer protocol features.

## Tools

- `index_model {}` imports authored files and returns revision, applied changes,
  and invalidations; unchanged imports do not create a revision.
- `get_graph_schema {}` returns the registered graph schema and revision.
- `search_graph {text?,type?,limit?}` searches serialized node content.
- `query_graph {type?,where?,limit?}` selects nodes by exact property equality.
  `where` is an object mapping property names to JSON values, not SQL or code.
- `trace_path {source,target,max_depth?}` returns a deterministic directed path.
- `apply_changes {expected_revision,changes}` atomically applies typed operations.
  Clients must refresh `tools/list` after model schema changes. Node create/update
  alternatives contain the registered type's actual properties schema.
- `detect_changes {}` previews authored-file differences without committing.
- `get_assessments {revision?}` returns pending/completed, revision-specific results.
- `compare_graphs {from_revision,to_revision}` returns node/edge identity diffs.
- `submit_assessment {revision,interceptor_id,target_id,result}` records explicit
  review. `result` has status `pass|fail|indeterminate`, object-array findings, and
  evidence entries `{obligation,uri}`. Pass requires matching declared obligations.

Inputs and structured outputs are independently JSON Schema validated at the
adapter boundary. Tool failures return `isError`; invalid arguments never execute
the application operation. Limits: query/search 1–1000; trace depth 0–100.

Resources are JSON: `graph://model/schema`, `graph://model/nodes/{id}`,
`graph://model/revisions/{revision}`, `graph://model/impact/{revision}`, and
`graph://model/assessments/{revision}`.

## Optional architecture authoring

A workspace registered with schema version `typed-graph/architecture/v1` advertises five
additional meaning-oriented tools: `define_concept`, `define_system`, `add_layer`,
`define_boundary` and `propose_binding`. Their input schemas derive from the same
strict role models as the registered graph schema. Refresh `tools/list` after
indexing the package; generic workspaces do not acquire these architectural tools.

Higher-order commands create the related records and edges atomically. For example,
a system definition includes its responsibility and versioned behavioral contract.
A proposed binding references a contract and interaction boundaries; it is not a
verification claim. Expected-revision checks still apply. Generic `apply_changes`
and source imports undergo the same architecture publication checks, so they cannot
bypass endpoint, required-reference or same-contract comparison constraints.

Agents author meaning, not reading order or document blocks. The fixed architecture
compiler produces the human specification from those records. Existing arbitrary
user schemas remain supported by the generic tools and graph inspector. The package
keeps architectural roles closed while allowing additional typed domain predicates:
`architecture_schema(domain_relations=...)` accepts new relations whose endpoints are
DomainConcept instances. Those predicates appear in the fixed domain section without
compiler changes. Canonical architecture relations cannot be replaced.

## Opt-in subscriptions

Add `--subscriptions` to enable `subscriptions/listen` for clients negotiating
`2026-07-28`. The SDK rejects listen on older negotiated protocols. Accepted resource
filters are confined to the graph resource URI patterns; each stream receives only
its honored filters. Schema commits publish tools-list-changed and schema-resource
updates. Revision commits publish revision/impact/assessment and affected-node updates.
Assessment submissions publish the assessment's own revision, including historical
results. Subscriptions are live and non-replayable: after disconnect, re-listen and
refetch; do not treat delivery as a durable event log. Maximum 64 concurrent streams,
256 buffered events per stream; slow streams are terminated by the SDK.

## Explicit external MCP handlers

Without `--handlers`, external names remain pending for agent/manual review; no
external command runs. To enable trusted handlers, supply an operator-owned JSON
file outside authored model data:

```json
{
  "allowed_executables": ["/opt/graph-tools/bin/python"],
  "handlers": {
    "contract-check": {
      "command": "/opt/graph-tools/bin/python",
      "args": ["/opt/graph-tools/contract_check.py"],
      "tool": "assess_contract",
      "timeout": 30
    }
  }
}
```

Run `typed-graph WORKSPACE --handlers /trusted/operator-handlers.json`.
An interceptor's `handler` names an operator-configured entry; model data cannot
choose executable, arguments, tool or timeout. Executables must be absolute and
resolve to the explicit allowlist. Each invocation is a fresh MCP subprocess in an
empty temporary working directory with temporary HOME/TMPDIR. The SDK additionally
inherits its limited environment allowlist (e.g. PATH and user name), not arbitrary
application secrets. No shell is invoked. Timeout is bounded to (0,300] seconds.

The external MCP tool receives `{context: ImpactContext}` and must return structured
assessment JSON. The graph pipeline validates returned results, evidence and custom
schemas; execution success alone is not pass. Errors/timeouts/missing evidence become
indeterminate. Commands execute as the server user: **process isolation is not an OS
security sandbox**. Operators must trust these programs or provide their own sandbox;
filesystem and network access of an allowlisted program are not restricted here.

On startup with handlers enabled, pending jobs at the current revision resume.
Scheduling is deduplicated by revision/interceptor/target. A crash after an external
process completes but before its result is recorded can cause a retry: delivery is
**at least once**, not exactly once. Handlers must deduplicate the context's stable
`invocation_id` and be idempotent. Superseded revision jobs remain available for
explicit review but are not automatically executed at startup. A client disconnect
does not interrupt an in-flight commit/handler pipeline or release its serialization
lock early; the bounded invocation completes and records its outcome.

Node resource path components use percent encoding (`/` inside a node identity is
`%2F`, for example `graph://model/nodes/team%2Fservice`). IDs are data, never file paths.
