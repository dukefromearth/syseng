# Architectural Metamodel v1.0 — tool-authored example

This example preserves domain meaning separately from system responsibilities and
realization choices. It is **not a verified implementation** of the blood-to-glitter
objective. All three realization bindings remain candidates with pending,
indeterminate assessments and no evidence or completed measurements.

## Reproduce through actual MCP tools

From the repository root with its installed Python environment:

```bash
.venv/bin/python examples/architectural_metamodel/author.py \
  /tmp/syseng-architectural-metamodel-fresh
```

Choose a fresh path: the script refuses any existing workspace. It launches
`typed_graph.adapters.mcp_server` as a separate process using the MCP 2.x `Client`
over stdio. `index_model` imports only a schema and an empty graph; a subsequent
`apply_changes` transaction creates all 63 nodes and 104 edges. No application
service or repository mutation API is called directly. Eighteen MCP calls verify the
schema, empty seed, authored entities, pending assessments, three semantic paths
to the same S3 contract, and added edge identities via revision comparison. Four positive responsibility-to-contract
`specified_by` traces and four negative system-to-contract traces guard the precise
relationship direction. The ten fixed cross-ontology endpoint constraints are defined
once in `CROSS_RELATION_ENDPOINTS`; occurrences are validated against them, not used
to infer those semantics.

The reviewed successful run used MCP 2.3.0 and workspace:
`/tmp/syseng-architectural-metamodel-demo-v5` (revision 2). See
`verification.json` for its compact receipt. The full MCP request/result transcript
is in that workspace's `mcp-transcript.json`, outside the repository. Two earlier
isolated runs successfully authored their graphs but stopped on client-side
verification errors (a null-result assumption and an incorrectly named comparison
tool); neither overwrote another workspace. The final script and successful run
correct both errors.

## Read the live specification

```bash
.venv/bin/python -m typed_graph.adapters.spec_server \
  /tmp/syseng-architectural-metamodel-demo-v5 \
  --profile examples/architectural_metamodel/presentation.json
```

`presentation.json` supplies only generic display metadata: groups, type order,
label/body properties and numeric order. The title and introductory prose come
once from the tool-authored `purpose` node. Reading mode puts prose first, uses
compact properties and relationships, hides identifiers and empty assessment
sections, and omits only layout properties (`section` / `order`). Candidate
status and pending assessments remain visible. It does not contain graph content
or application logic. Domain, Systems, and Realization remain distinct sections.

## Authored coverage

- 9 domain concepts, their semantic flows, and 5 invariant requirements.
- 4 systems, 4 owned responsibilities, 4 contracts, cross-system exchanges,
  responsibility-to-concept and contract-to-concept relationships.
- 5 realization concept definitions, 5 abstraction layers, and 2 illustrative
  engine environments (Unreal/Godot) and 5 classified interaction boundaries.
  Vulkan, Wayland and Linux DRM/KMS are boundary examples, not environments;
  their hosting environment is intentionally unspecified.
- 1 concrete objective, 6 required capabilities with availability unknown, and
  3 candidate bindings using engine, graphics API, and compositor boundaries.
- All bindings declare attempted satisfaction of the **same** S3 contract and
  required invariant preservation; declared edges are not proofs.
- 6 guardrails and explicit validity, capability relationship and result-flow rules.

The schema defines `provides` (Boundary → Capability), but does **not** fabricate
actual availability edges for these unverified candidates. `requires_capability`
edges express needs, while capability status remains unknown. Technology layer
mappings are illustrative supplied examples, not externally verified claims.
120 FPS is an approximately 8.33 ms frame interval, not an automatic end-to-end
intervention budget. Original-content exposure prevention is conditional on strict
prevention being required. Production and abstraction layers are not forced into
a sequential pipeline.

## Files and single source

- `author.py`: canonical authored example and common property-schema generator.
  Common properties are defined once, then generated for each open model type.
  Fixed cross-ontology relation endpoint constraints likewise have one authoritative catalog.
- `schema.json`: generated, reviewable schema-only seed (no graph entities).
- `source.json`: generated, reviewable entity/edge output; not directly imported.
- `presentation.json`: operator-controlled generic display profile.
- `verification.json`: compact successful real-tool receipt (no secrets).

Generated JSON is a review artifact, not an independently maintained definition.
No SQLite database, `.graph` runtime directory, or full bulky transport transcript
belongs in version control. Ruff and mypy pass for the authoring script. Its
successful end-to-end run exercises the real MCP transport and has assertions for
node count, edge count, schema agreement, pending states, empty evidence and
contract paths. Scientific efficacy, capability sufficiency and performance
verification remain deliberately outstanding.

Summary tables derive domain concepts, systems/responsibilities/contracts, and
abstraction layers from the same graph. The systems table follows `owns` and
`owns → specified_by`; no prose is duplicated in presentation configuration.
