# Typed Reactive Graph

A language-agnostic, JSON Schema-authored graph with immutable revisions, deterministic
dependency propagation, and evidence-bearing assessments. An MCP server lets agents
inspect and propose typed changes; the graph engine itself never calls an LLM.

**First release:** Python 3.12+, MCP 2.x / protocol 2026-07-28, one local workspace per
server process. No architecture ontology is built in. The example's Capability,
Boundary, Binding, Contract and System types are ordinary user-authored definitions.

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

## Documentation

- [How-to: edit, import, review and recover](docs/how-to.md)
- [Schema reference](docs/reference.md)
- [MCP tools, subscriptions and external handlers](docs/mcp.md)
- [Architecture and persistence decisions](docs/architecture.md)
- [Acceptance and limitations](docs/acceptance.md)

## Development

```sh
pip install -r requirements.lock
pip install --no-build-isolation --no-deps -e '.[dev]'
ruff format --check .
ruff check .
mypy src
pytest
python -m build --no-isolation
```

Behavior suites use real temporary workspaces, SQLite, source documents and MCP
clients, including subprocess transport. See [AGENTS.md](AGENTS.md) for engineering
rules. External handlers are disabled unless the operator supplies explicit
executable and handler allowlists; authored graph data cannot choose commands.
