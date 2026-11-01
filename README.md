# Typed Reactive Graph

A language-agnostic, JSON Schema-authored graph with immutable revisions, deterministic
dependency propagation, and evidence-bearing assessments. An MCP server lets agents
inspect and propose typed changes; the graph engine itself never calls an LLM.

**First release:** Python 3.12+, MCP 2.x / protocol 2026-07-28, one local workspace per
server process. The core accepts arbitrary schemas. The optional architecture module
adds typed architectural authoring and a fixed, coherent specification compiler without
putting architecture-specific concepts into the graph engine.

## Quickstart (tutorial)

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install --no-build-isolation --no-deps -e .
mkdir -p /tmp/my-graph/model
cp examples/model.json /tmp/my-graph/model/example.json
typed-graph /tmp/my-graph
```

Connect an MCP 2026-07-28-capable client to this stdio process. Call `index_model`
with `{}`, then `get_graph_schema`, `query_graph` or `get_assessments`.
Call `tools/list` again after indexing: `apply_changes` now advertises the
model's concrete node/edge alternatives rather than an untyped property bag.

Subscriptions are **off by default**. Pass `--subscriptions` to enable MCP
`subscriptions/listen` notifications. This release does not pretend MCP 2025 clients
understand the 2026 protocol; use a compatible client.

## Live specification reader

Agents author architectural meaning through MCP. The architecture compiler turns the
committed model into a coherent specification: unified metamodel, domain, systems,
realizations, cross-model relationships, independence examples and model invariants.
The compiler owns the reading order; agents do not author layout or document blocks.
Markdown and safe HTML share one projection. A separate graph inspector provides
record-level detail; it is not the human specification.

After indexing the example through MCP as above, run a second local process:

```sh
typed-graph-serve /tmp/my-graph --port 8080
```

Open [the local reader](http://127.0.0.1:8080). Continue authoring through MCP tools;
the reader notices committed revisions and assessment-only updates within the default
one-second polling interval. The read-only UI includes an outline, live status, source
view and Markdown download. Nothing is deployed, and no CDN is required.

For a seeded development preview after installing dependencies, run `npm ci --ignore-scripts`
then `npm run dev`. It uses `.venv`, honors `PORT`, and stores the example workspace
at `/tmp/typed-graph-reader-preview` (override with `TYPED_GRAPH_WORKSPACE`; set `TYPED_GRAPH_PROFILE` for a profile JSON).

For a larger specification authored entirely through real MCP calls, see the
[Architectural Metamodel v1.0 example](examples/architectural_metamodel/README.md).
That earlier example demonstrates the generic graph inspector and presentation profiles.

The [Presentation Transformation Platform](examples/presentation_transformation/README.md)
extends that example into a build specification: product requirements, four systems,
information exchange contracts, candidate bindings and measurable acceptance targets.
The fixed architecture compiler produces focused Mermaid diagrams and coherent
expandable system sections from canonical records. The compiler knows architectural
roles, never platform-specific facts or hand-maintained diagram relationships.
Requirements and proposed technologies are not reported as proven implementations.

## Documentation

- [How-to: edit, import, review and recover](docs/how-to.md)
- [Schema reference](docs/reference.md)
- [MCP tools, subscriptions and external handlers](docs/mcp.md)
- [Architecture and persistence decisions](docs/architecture.md)
- [Acceptance and limitations](docs/acceptance.md)
- [Reader endpoints, safety and live updates](docs/specification-reader.md)

## Development

```sh
pip install -r requirements.lock
pip install --no-build-isolation --no-deps -e '.[dev]'
npm ci --ignore-scripts
npm run lint
npm run check:reader
ruff format --check .
ruff check .
mypy src scripts/preview.py examples/architectural_metamodel/author.py
mypy examples/presentation_transformation/author.py
pytest
python -m build --no-isolation
```

The diagram adapter is bundled locally from pinned npm dependencies. After changing
`scripts/reader-diagrams.js` or its dependencies, run `npm run build:reader` and commit
the generated asset and license notice. `check:reader` rejects stale generated files.

Behavior suites use real temporary workspaces, SQLite, source documents and MCP
clients, including subprocess transport. See [AGENTS.md](AGENTS.md) for engineering
rules. External handlers are disabled unless the operator supplies explicit
executable and handler allowlists; authored graph data cannot choose commands.
