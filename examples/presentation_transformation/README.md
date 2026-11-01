# Presentation Transformation Platform

A complete architectural specification authored through the canonical architecture
MCP tools and compiled into a fixed seven-section reading document. This is a build
specification, **not** an implementation or performance demonstration of the proposed
graphics platform.

## Run the example

From the repository root after installing the locked dependencies and package:

```sh
WORKSPACE=/tmp/syseng-platform-fresh
.venv/bin/python examples/presentation_transformation/author.py "$WORKSPACE"
.venv/bin/typed-graph-serve "$WORKSPACE" --port 8080
```

Open `http://127.0.0.1:8080/`. Choose a fresh workspace: the author refuses to replace
an existing directory. No presentation profile, document blocks, layout nodes, section
numbers or reading-order properties are needed in the model. The optional architecture
application owns the reading structure; the underlying graph engine remains generic.

The compiler presents the unified metamodel, domain ontology, system ontology,
realization ontology, cross-model relationships, independence example and model
invariants. Build requirements, performance criteria, failure cases, reference scenarios,
phases, reuse and exclusions remain available in organized appendices. Diagrams, tables
and repeated references use the same canonical facts; Markdown remains downloadable.

## Authoring and provenance

`author.py` declares the example's architectural facts. The shared
`typed_graph.architecture` catalog supplies the property models, legal relationships,
validation rules and semantic-tool contracts. Regenerate the reviewable artifacts with:

```sh
.venv/bin/python examples/presentation_transformation/author.py --write-artifacts
```

The script imports an empty canonical schema, then uses all five semantic tools:
`define_concept`, `add_layer`, `define_boundary`, `define_system` and `propose_binding`.
Each call checks its expected revision and commits atomically. Generic `apply_changes`
adds the remaining typed facts and relationships through the same validators. The
script verifies every generated entity against the canonical authored fixture.

The workspace's `mcp-transcript.json` and `result.json` contain actual tool calls,
revision receipts, rejected invalid mutations and retrieved assessments. Published
`verification.json` summarizes a real run. These receipts are evidence about authoring
and validation, not evidence that the proposed graphics platform meets its contracts.

The initial builder produces pending/indeterminate binding assessments with no invented
measurements. Assessments retain their originating revisions; the reader distinguishes
current, stale and absent records. Candidate lifecycle is an authored proposal state,
not a substitute for an assessment or a claim of successful conformance.

## Semantic corrections

- System **behavioral contracts** specify obligations. C1–C5 **exchange contracts**
  specify information crossing boundaries. Both have explicit versions.
- Policy, Objective and Capability have canonical definitions. Scoped vocabularies
  reference or specialize them without redefining their meaning. An Objective instance
  is distinct from the definition of Objective.
- Architectural realization Binding differs from runtime Policy Binding. Architecture
  governance is a role, not a fifth system.
- An explicit independence example compares engine, Vulkan and compositor candidates
  against the **same S3 contract and objective**. Additional compositor recognition is
  a required capability, not an assertion that it is available.
- Shared S3 capabilities describe semantic targeting and authorized intervention
  independently of representations. Graphics resource/shader details belong to the
  graphics candidate. No `provides` relationship fabricates capability availability.
- Reference 0.5 ms additional p99, 7.8 ms baseline p99 and 120 FPS targets are preserved
  and scoped to the reference binding/objective. They do not become a universal S3
  contract. Adding two p99 values cannot establish the transformed workload's p99;
  direct measurement is required.
- A05 preparation is strictly outside the reference frame-critical path. The general
  contract retains its qualified “wherever possible” obligation. No-full-frame-model
  restrictions apply to the known reference transformation, not every candidate policy.
- Strict protection concerns covered production presentation. It does not prohibit
  research capture of the original variant. Policy review and activation precede
  execution; correction follows execution.
- Phone-feed validation and phase 7 retain explicit future scope. They are planned
  tests of portability, not evidence that portability has been achieved.

## What validation establishes

The MCP rejects duplicate canonical definitions, illegal endpoints, domain-to-technology
relationships under domain relations, missing ownership/contracts/versions/boundaries,
a purported same-contract comparison with different contracts, invented verification
states, evidence-free passing assessments and stale expected revisions. Generic and
semantic tools share these checks.

It cannot prove causal equivalence, semantic preservation, evidence truth or runtime
performance from prose assertions. Those require independently evaluated evidence.

The behavioral example test authors a novel concept through `define_concept` and checks
that it appears in the domain section without any schema, profile or compiler edits.
It also changes canonical responsibility and acceptance facts and checks every included
reading location updates. Dependency tests distinguish scoped reference requirements
from shared contract changes, preserving explainable invalidation paths.
