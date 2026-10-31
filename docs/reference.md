# Reference: authored graph and supported schema

An authored document contains `schema`, `nodes`, and `edges`. These are data,
not Python classes. See [the example](../examples/model.json): its five example
types are not hardcoded by the engine.

## Schema

```json
{
  "version": "1",
  "node_types": {
    "Item": {
      "type": "object",
      "properties": {"name": {"type": "string"}},
      "required": ["name"],
      "additionalProperties": false
    }
  },
  "relations": {
    "depends_on": {
      "source": ["Item"],
      "target": ["Item"],
      "impact": "target_to_source",
      "cardinality": {"out_max": 2}
    }
  },
  "invariants": [],
  "interceptors": []
}
```

- Node: `{"id":"a","type":"Item","properties":{"name":"A"}}`.
  Identity is a nonempty string unique among nodes. Properties must be an object.
- Edge: `{"id":"ab","type":"depends_on","source":"a","target":"b"}`.
  Identity is unique among edges. Both endpoints must exist and match registered
  endpoint types. Optional `properties` are checked against the relation's
  optional JSON Schema `properties` definition. Without that definition, edge
  properties are a closed empty object.
- Property schemas use JSON Schema 2020-12. Local JSON Pointer references
  (`#`, `#/$defs/...`) are supported. Remote references, resource `$id`,
  anchors, and dynamic references are rejected. Formats are annotations rather
  than assertions. The engine never fetches schemas from a network.
- Every relation declares `impact`: `target_to_source`, `source_to_target`,
  `both`, or `none`. Direction concerns invalidation, not edge orientation.
- `cardinality`: optional nonnegative integer `out_min`, `out_max`,
  `in_min`, `in_max`. Bounds apply to each node of eligible endpoint type,
  including nodes with zero matching edges.
- `unique` invariant: `{"kind":"unique","node_type":"Item","property":"name"}`.
  The property must be present on every selected node. Values compare by
  canonical JSON; missing values are not silently skipped.
- `requires_edge` invariant:
  `{"kind":"requires_edge","node_type":"Item","relation":"depends_on","direction":"out","min":1}`.
  Direction defaults to `out`; `min` defaults to 1.
- No arbitrary expressions, SQL invariants, scripts, or general-purpose rule
  language are accepted. Unknown schema fields and invariant kinds fail closed.
- Empty type registries are allowed for bootstrap only: no node can validate and
  no nonempty mutation batch is advertised until types are imported.

## Interceptors and evidence

An interceptor is schema data:

```json
{
  "id": "review",
  "target_type": "Item",
  "handler": "pending",
  "version": "1",
  "trigger": "dependency_changed",
  "evidence_required": ["conformance"]
}
```

`pending` requests explicit review; it is not verification. Named external
handlers require separate operator configuration. A handler result contains
`status` (`pass`, `fail`, `indeterminate`), `findings` (objects), and
`evidence` (`{"obligation":"conformance","uri":"..."}` objects).
Optional `result_schema` adds a JSON Schema result contract. A completed
invocation without evidence cannot satisfy a declared evidence obligation.
Assessments are derived revision-specific records, never implicit model edits.

## Typed mutation batches

`apply_changes` takes `expected_revision` and `changes`. The advertised tool
schema is regenerated from the registered node and relation types.

| Operation | Fields besides `op` |
| --- | --- |
| `create_node` | `node`: complete node |
| `update_node` | `id`, `type`, `properties` |
| `delete_node` | `id` |
| `create_edge` | `edge`: complete edge |
| `update_edge` | `id`, `type`, `source`, `target`, optional `properties` |
| `delete_edge` | `id` |

Updates replace properties; they are not merge patches. Deletion does not
silently cascade: remove incident edges in the same batch. Intermediate states
may violate graph constraints; the final batch state must validate. Unknown
identities and duplicate creates reject the whole batch.

## Impact semantics and limits

Traversal uses the union of old and new edges and old and new propagation
definitions. Deleted dependencies therefore still invalidate dependents.
Each affected existing node records the triggering revision and one shortest,
lexicographically deterministic path per changed root. Deleted roots can appear
in paths. Cycles are visited once per root: paths never grow indefinitely.
This is not enumeration of all possible paths or a general graph query engine.
Schema changes conservatively invalidate all existing nodes. Neither traversal
nor assessments call an LLM in the domain engine.

## Concise schema authoring

A standalone schema can instead use the following generic shorthand:

```json
{
  "schema": "architecture/v1",
  "nodes": {
    "Widget": {"properties": {"name": "string", "count": "integer"}},
    "Bucket": {"properties": {"label": "string"}, "required": []}
  },
  "edges": {
    "contains": {"from": "Bucket", "to": "Widget", "impact": "target_to_source"}
  }
}
```

The schema compiler translates `schema` to version, `nodes` to node types,
and `edges` to relations. Endpoint `from`/`to` may be a string or list.
Property values may be JSON Schemas or primitive names `string`, `number`,
`integer`, `boolean`, `object`, `array`, `null`.
All declared properties are required by default; an explicit `required` list
overrides this. Node properties are closed by default; explicit JSON Schema
`additionalProperties` overrides that default. Canonical schemas are not
rewritten or assigned shorthand defaults.

## Path queries and strongly connected components

`trace_path` accepts `source`, `target`, optional `max_depth` (0–100,
default 20), optional registered `relation` filter, and `mode`.
The default `semantic` mode follows authored source-to-target edges.
`dependency` mode follows the declared impact directions; `none` contributes
no dependency links. Both modes return one deterministic shortest path.

Invalidation computes strongly connected components over the union dependency
graph using iterative Kosaraju decomposition, then topologically orders the
condensation graph with stable component-ID tie-breaking. Every impact entry
includes `component_id` (smallest member ID) and sorted `component` members,
alongside its shortest provenance paths. Components can include deleted nodes,
while impact entries themselves address surviving nodes. Interceptors are
scheduled once per revision/interceptor/target, not once per traversal path.
