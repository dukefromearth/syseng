# Engineering contract
- Python 3.12+. Format and lint with Ruff; type-check with mypy; run pytest behavior suites and build before delivery.
- Hexagonal boundaries: domain imports no application/adapters/IO; application depends on domain and Protocol ports only; adapters implement persistence, sources, MCP and external handlers.
- No built-in architecture ontology. All types, relations, propagation and evidence obligations come from schema.
- Treat model/files/tool arguments as untrusted. No eval, arbitrary SQL, model-selected commands, remote schema loading or unconstrained paths.
- Prefer table-driven behavioral tests through public application and real SQLite/files/MCP transports. Avoid mock-heavy/private-method unit tests.
- Atomic batches, immutable history, deterministic ordering, explicit expected revisions and recoverable source/index consistency are contracts.
- External effects require operator configuration; assessments never mutate authored graph or equate completion with evidence.
