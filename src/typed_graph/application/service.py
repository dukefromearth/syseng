"""Deterministic use cases, depending only on domain and IO ports."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import deque
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator

from typed_graph.application.ports import Document, Repository
from typed_graph.domain.engine import apply_operations, compute_impact, validate_graph
from typed_graph.domain.schema import validate_schema


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class GraphService:
    def __init__(self, store: Repository):
        self.store = store

    @property
    def schema(self) -> Document:
        return dict(self.store.current()["schema"])

    @property
    def revision(self) -> int:
        return int(self.store.current()["revision"])

    def dispatch(self, tool: str, args: Document) -> Document:
        handlers = {
            "index_model": self.index_model,
            "get_graph_schema": self.get_graph_schema,
            "apply_changes": self.apply_changes,
            "detect_changes": self.detect_changes,
            "search_graph": self.search_graph,
            "query_graph": self.query_graph,
            "trace_path": self.trace_path,
            "compare_graphs": self.compare_graphs,
            "get_assessments": self.get_assessments,
            "submit_assessment": self.submit_assessment,
        }
        if tool not in handlers:
            raise ValueError(f"unknown tool {tool}")
        return handlers[tool](args)

    def get_graph_schema(self, args: Document) -> Document:
        return {"revision": self.revision, "schema": self.schema}

    def _validate(self, document: Document) -> None:
        validate_schema(document["schema"])
        validate_graph(document["schema"], document["nodes"], document["edges"])

    def _commit(
        self, old: Document, new: Document, changes: list[Document], changed: list[str]
    ) -> Document:
        self._validate(new)
        revision = old["revision"] + 1
        impact = compute_impact(
            old["schema"],
            new["schema"],
            old["nodes"],
            old["edges"],
            new["nodes"],
            new["edges"],
            changed,
            revision,
        )
        new.update({"impact": impact, "changes": changes})
        committed = self.store.commit(new, old["revision"])
        self._schedule(committed)
        return {"revision": revision, "applied_changes": changes, "invalidations": impact}

    def index_model(self, args: Document) -> Document:
        old = self.store.current()
        new = self.store.import_document()
        self._validate(new)
        changed = self._changed(old, new)
        if not changed and old["schema"] == new["schema"]:
            self.store.accept_import(new, old["revision"])
            return {"revision": old["revision"], "applied_changes": [], "invalidations": []}
        if old["schema"] != new["schema"]:
            changed = sorted({n["id"] for n in old["nodes"] + new["nodes"]})
        return self._commit(old, new, [{"op": "import"}], changed)

    def apply_changes(self, args: Document) -> Document:
        old = self.store.current()
        if args["expected_revision"] != old["revision"]:
            raise ValueError("revision conflict")
        nodes, edges, changed = apply_operations(
            old["schema"], old["nodes"], old["edges"], args["changes"]
        )
        changed = self._changed(old, {"nodes": nodes, "edges": edges})
        if not changed:
            return {"revision": old["revision"], "applied_changes": [], "invalidations": []}
        new = {**copy.deepcopy(old), "nodes": nodes, "edges": edges}
        return self._commit(old, new, args["changes"], changed)

    def _changed(self, old: Document, new: Document) -> list[str]:
        before = {n["id"]: n for n in old["nodes"]}
        after = {n["id"]: n for n in new["nodes"]}
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        a = {e["id"]: e for e in old["edges"]}
        b = {e["id"]: e for e in new["edges"]}
        for key in a.keys() | b.keys():
            if a.get(key) != b.get(key):
                for edge in (a.get(key), b.get(key)):
                    if edge:
                        changed.update((edge["source"], edge["target"]))
        return sorted(changed)

    def detect_changes(self, args: Document) -> Document:
        old, new = self.store.current(), self.store.import_document()
        self._validate(new)
        changed = self._changed(old, new)
        if old["schema"] != new["schema"]:
            changed = sorted({n["id"] for n in old["nodes"] + new["nodes"]})
        impact = compute_impact(
            old["schema"],
            new["schema"],
            old["nodes"],
            old["edges"],
            new["nodes"],
            new["edges"],
            changed,
            old["revision"] + 1,
        )
        return {
            "revision": old["revision"],
            "changed_nodes": changed,
            "schema_changed": old["schema"] != new["schema"],
            "preview_revision": old["revision"] + 1,
            "impact": impact,
        }

    def query_graph(self, args: Document) -> Document:
        if set(args) - {"type", "where", "limit"}:
            raise ValueError("query accepts only type, where equality filters, and limit")
        limit = args.get("limit", 100)
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        where = args.get("where", {})
        if not isinstance(where, dict):
            raise ValueError("where must be a property-equality mapping")
        return self.store.search_nodes(args.get("type"), where, "", limit)

    def search_graph(self, args: Document) -> Document:
        limit = args.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        return self.store.search_nodes(args.get("type"), {}, str(args.get("text", "")), limit)

    def trace_path(self, args: Document) -> Document:
        doc = self.store.current()
        ids = {n["id"] for n in doc["nodes"]}
        source, target = args["source"], args["target"]
        if source not in ids or target not in ids:
            raise ValueError("unknown endpoint")
        depth = args.get("max_depth", 20)
        if type(depth) is not int or not 0 <= depth <= 100:
            raise ValueError("max_depth must be 0..100")
        mode = args.get("mode", "semantic")
        if mode not in {"semantic", "dependency"}:
            raise ValueError("mode must be semantic or dependency")
        relation = args.get("relation")
        if relation is not None and (
            not isinstance(relation, str) or relation not in doc["schema"]["relations"]
        ):
            raise ValueError("unknown relation")
        adjacency: dict[str, set[str]] = {}
        for edge in doc["edges"]:
            if relation is not None and edge["type"] != relation:
                continue
            impact = doc["schema"]["relations"][edge["type"]]["impact"]
            if mode == "semantic" or impact in {"source_to_target", "both"}:
                adjacency.setdefault(edge["source"], set()).add(edge["target"])
            if mode == "dependency" and impact in {"target_to_source", "both"}:
                adjacency.setdefault(edge["target"], set()).add(edge["source"])
        queue = deque([[source]])
        seen = {source}
        while queue:
            path = queue.popleft()
            if path[-1] == target:
                return {"revision": doc["revision"], "path": path}
            if len(path) - 1 >= depth:
                continue
            for endpoint in sorted(adjacency.get(path[-1], set())):
                if endpoint not in seen:
                    seen.add(endpoint)
                    queue.append([*path, endpoint])
        return {"revision": doc["revision"], "path": []}

    def compare_graphs(self, args: Document) -> Document:
        old = self.store.read_revision(args["from_revision"])
        new = self.store.read_revision(args["to_revision"])
        result: Document = {
            "from_revision": old["revision"],
            "to_revision": new["revision"],
            "schema_changed": old["schema"] != new["schema"],
        }
        for kind in ("nodes", "edges"):
            a, b = ({n["id"]: n for n in doc[kind]} for doc in (old, new))
            result[kind] = {
                "added": sorted(b.keys() - a.keys()),
                "removed": sorted(a.keys() - b.keys()),
                "updated": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
            }
        return result

    def _schedule(self, document: Document) -> None:
        nodes = {n["id"]: n for n in document["nodes"]}
        recorded = {
            (a["interceptor_id"], a["target_id"])
            for a in self.store.assessments(document["revision"])
        }
        for impact in document["impact"]:
            node = nodes.get(impact["node_id"])
            if node is None:
                continue
            for interceptor in document["schema"].get("interceptors", []):
                key = (interceptor["id"], node["id"])
                if interceptor["target_type"] != node["type"] or key in recorded:
                    continue
                assessment = {
                    "revision": document["revision"],
                    "interceptor_id": interceptor["id"],
                    "target_id": node["id"],
                    "handler_version": interceptor["version"],
                    "target_fingerprint": fingerprint(node),
                    "state": "pending",
                    "result": {"status": "indeterminate", "findings": [], "evidence": []},
                    "context": {
                        "target": node,
                        "impact": impact,
                        "triggering_revision": document["revision"],
                        "changes": document["changes"],
                        "handler_version": interceptor["version"],
                        "invocation_id": fingerprint(
                            [document["revision"], interceptor["id"], node["id"]]
                        ),
                    },
                }
                self.store.record_assessment(assessment)
                recorded.add(key)

    def submit_assessment(self, args: Document) -> Document:
        revision = args["revision"]
        doc = self.store.read_revision(revision)
        self._schedule(doc)
        matches = [
            a
            for a in self.store.assessments(revision)
            if a["interceptor_id"] == args["interceptor_id"] and a["target_id"] == args["target_id"]
        ]
        if not matches:
            raise ValueError("assessment was not scheduled for this revision/target/interceptor")
        assessment = matches[0]
        interceptor = next(
            i for i in doc["schema"]["interceptors"] if i["id"] == args["interceptor_id"]
        )
        result = args["result"]
        Draft202012Validator(
            {
                "type": "object",
                "required": ["status", "findings", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "status": {"enum": ["pass", "fail", "indeterminate"]},
                    "findings": {"type": "array", "items": {"type": "object"}},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["obligation", "uri"],
                            "properties": {
                                "obligation": {"type": "string"},
                                "uri": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            }
        ).validate(result)
        if interceptor.get("result_schema"):
            Draft202012Validator(interceptor["result_schema"]).validate(result)
        supplied = {e["obligation"] for e in result["evidence"]}
        required = set(interceptor.get("evidence_required", []))
        if result["status"] == "pass" and (not required or not required <= supplied):
            raise ValueError("pass requires declared evidence obligations and matching evidence")
        assessment = {**assessment, "state": "completed", "result": result}
        self.store.record_assessment(assessment)
        return {"assessment": self._freshness(assessment)}

    def record_handler_failure(
        self, revision: int, interceptor_id: str, target_id: str, error: str
    ) -> Document:
        matches = [
            a
            for a in self.store.assessments(revision)
            if a["interceptor_id"] == interceptor_id and a["target_id"] == target_id
        ]
        if not matches:
            raise ValueError("unknown scheduled handler")
        assessment = {
            **matches[0],
            "state": "completed",
            "result": {"status": "indeterminate", "findings": [{"error": error}], "evidence": []},
            "framework_failure": True,
        }
        self.store.record_assessment(assessment)
        return {"assessment": self._freshness(assessment)}

    def _freshness(self, assessment: Document) -> Document:
        # Freshness is revision-specific, including dependencies and handler/schema edits.
        return {**assessment, "stale": assessment["revision"] != self.revision}

    def get_assessments(self, args: Document) -> Document:
        revision = args.get("revision", self.revision)
        doc = self.store.read_revision(revision)
        self._schedule(doc)
        return {
            "revision": revision,
            "assessments": [self._freshness(a) for a in self.store.assessments(revision)],
        }

    def resource(self, uri: str) -> Document:
        prefix = "graph://model/"
        if not uri.startswith(prefix):
            raise ValueError("unknown resource")
        path = uri[len(prefix) :]
        if path == "schema":
            return self.get_graph_schema({})
        kind, separator, value = path.partition("/")
        if not separator or "/" in value:
            raise ValueError("unknown resource")
        if kind == "nodes":
            node = next(
                (n for n in self.store.current()["nodes"] if n["id"] == unquote(value)), None
            )
            if node is None:
                raise ValueError("unknown node")
            return {"revision": self.revision, "node": node}
        if not value.isdecimal():
            raise ValueError("revision must be nonnegative integer")
        revision = int(value)
        if kind == "assessments":
            return self.get_assessments({"revision": revision})
        doc = self.store.read_revision(revision)
        if kind == "revisions":
            return doc
        if kind == "impact":
            return {"revision": revision, "impact": doc["impact"]}
        raise ValueError("unknown resource")
