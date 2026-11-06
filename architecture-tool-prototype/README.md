# Architecture tool prototype

Local, non-production Python stdio MCP server with two strict Pydantic tools. The server validates and persists supplied artifacts; it does not invoke a model, perform research, or add design advice. The caller performs those activities.

## Run

Use Python 3.12+ and a separate virtual environment for this standalone prototype.
It uses MCP 1.x; the repository application uses MCP 2.x.

From the repository root:

```sh
cd architecture-tool-prototype
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py --output-dir ./experiment-output
```

Thin MCP client bridge (actual `tools/list` and `tools/call` over subprocess stdio):

```sh
python client.py list --output-dir ./experiment-output
python client.py call define_product_boundary '{"name":"Example","intended_experience":"Desired outcome","scope":"Product boundary","exclusions":[],"external_dependencies":[],"open_questions":[]}' --output-dir ./experiment-output
# Or read the JSON arguments from stdin:
python client.py call decompose_system - --output-dir ./experiment-output < arguments.json
```

All input fields are required. Unknown fields and incorrect types are rejected, including nested fields. `calls.jsonl` records received inputs exactly as JSON values, then their persistence or rejection outcome. Successful calls persist numbered immutable-by-convention revision files and a latest snapshot, with revisions per tool. Validation failures do not increment revisions. Revisions survive server restarts.

## Verification

```sh
python smoke_test.py
```

The behavioral smoke test starts a real MCP subprocess, discovers schemas, calls both tools, checks exact input logging and revision persistence, rejects missing/extra/incorrect/nested fields, and restarts the server to check revisions continue. It uses a new temporary output directory, isolated from experiments.

## Limits

Prototype only: no authentication, production hardening, semantic architecture validation, or concurrency guarantees. Do not run multiple writers against one output directory. No crash-atomic transaction guarantees. Inputs and results are stored locally as plain JSON. Discovery starts the server and creates its output directory but does not write a tool-call event. Client commands each start a new server process; reuse an output directory to retain revision history.

Installed/tested dependency versions: mcp 1.29.0, pydantic 2.13.4.

## Provenance

Imported from the [November 1 experiment](https://github.com/dukefromearth/syseng/tree/58881ff3167605449f2b7e2767e6087043f0a4c6/experiments/architecture-tool-prototype). The server, client, smoke test, dependency pins, and saved experiment evidence are unchanged.
