"""Durable authored snapshots and rebuildable SQLite index.

The manifest is the sole commit point. Snapshots are immutable and fsynced before
atomic manifest replacement; SQLite is repaired from snapshots after any crash.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typed_graph.application.service import GraphService

import yaml

from typed_graph.application.ports import Document
from typed_graph.domain.schema import compile_schema

EMPTY_SCHEMA: Document = {
    "version": "0",
    "node_types": {},
    "relations": {},
    "interceptors": [],
    "invariants": [],
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class WorkspaceRepository:
    def __init__(self, workspace: Path):
        self.root = workspace.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = self.root / ".graph"
        if self.state.is_symlink():
            raise ValueError(".graph must not be a symlink")
        self.state.mkdir(exist_ok=True)
        self.snapshots = self.state / "snapshots"
        self.snapshots.mkdir(exist_ok=True)
        for name in ("snapshots", "manifest.json", "index.sqlite3", "lock", "assessments.jsonl"):
            if (self.state / name).is_symlink():
                raise ValueError("symlinks forbidden in graph state")
        self.db = sqlite3.connect(self.state / "index.sqlite3", check_same_thread=False)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS revisions(
            revision INTEGER PRIMARY KEY, document TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,properties TEXT);
          CREATE INDEX IF NOT EXISTS node_type ON nodes(type);
          CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,type TEXT,source TEXT,target TEXT);
          CREATE INDEX IF NOT EXISTS forward_deps ON edges(source,type);
          CREATE INDEX IF NOT EXISTS reverse_deps ON edges(target,type);
          CREATE TABLE IF NOT EXISTS assessments(
            revision INTEGER, interceptor_id TEXT,target_id TEXT,payload TEXT,
            PRIMARY KEY(revision,interceptor_id,target_id));
        """)
        with self.lock():
            if not (self.state / "manifest.json").exists():
                initial = {
                    "revision": 0,
                    "schema": EMPTY_SCHEMA,
                    "nodes": [],
                    "edges": [],
                    "impact": [],
                    "changes": [],
                }
                self._write(self.snapshots / "0.json", canonical(initial))
                self._write(self.state / "manifest.json", canonical({"revision": 0}))
            self._recover()

    @contextmanager
    def lock(self) -> Iterator[None]:
        with (self.state / "lock").open("a") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _write(self, path: Path, content: str) -> None:
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def current(self) -> Document:
        manifest = json.loads((self.state / "manifest.json").read_text())
        return {
            **self.read_revision(int(manifest["revision"])),
            **{k: v for k, v in manifest.items() if k.startswith("source_")},
        }

    def read_revision(self, revision: int) -> Document:
        if revision < 0:
            raise ValueError("revision must be nonnegative")
        manifest = self.state / "manifest.json"
        if manifest.exists() and revision > json.loads(manifest.read_text())["revision"]:
            raise ValueError(f"uncommitted revision {revision}")
        path = self.snapshots / f"{revision}.json"
        if path.is_symlink():
            raise ValueError("snapshot symlinks are forbidden")
        if not path.exists():
            raise ValueError(f"unknown revision {revision}")
        result: Document = json.loads(path.read_text())
        return result

    def _recover(self) -> None:
        current = self.current()
        with self.db:
            self.db.execute("DELETE FROM revisions")
            for revision in range(current["revision"] + 1):
                doc = self.read_revision(revision)
                self.db.execute("INSERT INTO revisions VALUES (?,?)", (revision, canonical(doc)))
            self.db.execute("DELETE FROM nodes")
            self.db.executemany(
                "INSERT INTO nodes VALUES (?,?,?)",
                [(n["id"], n["type"], canonical(n["properties"])) for n in current["nodes"]],
            )
            self.db.execute("DELETE FROM edges")
            self.db.executemany(
                "INSERT INTO edges VALUES (?,?,?,?)",
                [(e["id"], e["type"], e["source"], e["target"]) for e in current["edges"]],
            )
            self.db.execute("DELETE FROM assessments")
            log = self.state / "assessments.jsonl"
            if log.exists():
                for line in log.read_text().splitlines():
                    assessment = json.loads(line)
                    self._index_assessment(assessment)

    def import_document(self) -> Document:
        """Import schema.json/yaml plus model files; after apply, manifest is canonical."""
        source = self.root / "model"
        if not source.exists() and "source_baseline" not in self.current():
            return self.current()
        if source.is_symlink():
            raise ValueError("model directory must not be a symlink")
        merged: Document = {"nodes": [], "edges": []}
        files: dict[str, str] = {}
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError("model symlinks are forbidden")
            if not path.is_file() or path.suffix not in (".json", ".yaml", ".yml", ".md"):
                continue
            raw = path.read_text()
            files[str(path.relative_to(source))] = hashlib.sha256(raw.encode()).hexdigest()
            blocks = [raw]
            if path.suffix == ".md":
                blocks = re.findall(r"\x60\x60\x60graph\s*\n(.*?)\x60\x60\x60", raw, re.S)
            for block in blocks:
                data = json.loads(block) if path.suffix == ".json" else yaml.safe_load(block)
                if not isinstance(data, dict):
                    raise ValueError(f"model document must be a mapping: {path.name}")
                if isinstance(data.get("schema"), str):
                    data = {"schema": compile_schema(data)}
                if set(data) - {"schema", "nodes", "edges"}:
                    raise ValueError("unknown model document keys")
                if "schema" in data:
                    if "schema" in merged:
                        raise ValueError("multiple schema sources")
                    merged["schema"] = data["schema"]
                merged["nodes"].extend(data.get("nodes", []))
                merged["edges"].extend(data.get("edges", []))
        current = self.current()
        # Unchanged imported files must not overwrite subsequent tool-authored edits.
        if files == current.get("source_fingerprints"):
            return current
        merged["schema"] = merged.get("schema", current["schema"])
        baseline = current.get(
            "source_baseline", {"schema": EMPTY_SCHEMA, "nodes": [], "edges": []}
        )
        result: Document = {"source_fingerprints": files, "source_baseline": merged}
        # Three-way reconcile authored imports against the last import and current
        # canonical snapshot. Disjoint source/tool edits survive; overlap conflicts.
        for kind in ("nodes", "edges"):

            def keyed(items: list[Document]) -> dict[str, Document]:
                mapping = {item["id"]: item for item in items}
                if len(mapping) != len(items):
                    raise ValueError("duplicate identities across sources")
                return mapping

            base, authored, live = (keyed(doc[kind]) for doc in (baseline, merged, current))
            reconciled = dict(live)
            for identity in base.keys() | authored.keys():
                before, after, present = (
                    base.get(identity),
                    authored.get(identity),
                    live.get(identity),
                )
                if before == after:
                    continue
                if present != before and present != after:
                    raise ValueError(f"source/tool conflict for {kind}/{identity}")
                if after is None:
                    reconciled.pop(identity, None)
                else:
                    reconciled[identity] = after
            result[kind] = sorted(reconciled.values(), key=lambda item: item["id"])
        if merged["schema"] != baseline["schema"]:
            if current["schema"] not in (baseline["schema"], merged["schema"]):
                raise ValueError("source/tool schema conflict")
            result["schema"] = merged["schema"]
        else:
            result["schema"] = current["schema"]
        return result

    def accept_import(self, document: Document, expected_revision: int) -> None:
        with self.lock():
            if self.current()["revision"] != expected_revision:
                raise ValueError("revision conflict")
            manifest = {
                "revision": expected_revision,
                **{k: v for k, v in document.items() if k.startswith("source_")},
            }
            self._write(self.state / "manifest.json", canonical(manifest))

    def commit(self, document: Document, expected_revision: int) -> Document:
        with self.lock():
            current = self.current()
            if current["revision"] != expected_revision:
                raise ValueError(
                    f"revision conflict: expected {expected_revision}, current "
                    f"{current['revision']}"
                )
            revision = expected_revision + 1
            result = {**document, "revision": revision}
            self._write(self.snapshots / f"{revision}.json", canonical(result))
            self._write(
                self.state / "manifest.json",
                canonical(
                    {
                        "revision": revision,
                        **{k: v for k, v in result.items() if k.startswith("source_")},
                    }
                ),
            )
            self._index_delta(current, result)
            return result

    def _index_delta(self, old: Document, new: Document) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO revisions VALUES (?,?)", (new["revision"], canonical(new))
            )
            for kind in ("nodes", "edges"):
                before = {item["id"]: item for item in old[kind]}
                after = {item["id"]: item for item in new[kind]}
                # Table names are fixed application constants, never tool input.
                for identity in before.keys() - after.keys():
                    self.db.execute(f"DELETE FROM {kind} WHERE id=?", (identity,))
                for identity, item in after.items():
                    if before.get(identity) == item:
                        continue
                    if kind == "nodes":
                        self.db.execute(
                            "INSERT OR REPLACE INTO nodes VALUES (?,?,?)",
                            (identity, item["type"], canonical(item["properties"])),
                        )
                    else:
                        self.db.execute(
                            "INSERT OR REPLACE INTO edges VALUES (?,?,?,?)",
                            (identity, item["type"], item["source"], item["target"]),
                        )

    def search_nodes(
        self, node_type: str | None, where: Document, text: str, limit: int
    ) -> Document:
        with self.lock():
            # A different process or a post-manifest crash can leave this projection behind.
            indexed = self.db.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if indexed != self.current()["revision"]:
                self._recover()
            sql = "SELECT id,type,properties FROM nodes"
            parameters: tuple[str, ...] = ()
            if node_type is not None:
                sql += " WHERE type=?"
                parameters = (node_type,)
            sql += " ORDER BY id"
            result: list[Document] = []
            for identity, kind, raw in self.db.execute(sql, parameters):
                node = {"id": identity, "type": kind, "properties": json.loads(raw)}
                if not all(
                    k in node["properties"] and node["properties"][k] == v for k, v in where.items()
                ):
                    continue
                if text and text.casefold() not in json.dumps(node, sort_keys=True).casefold():
                    continue
                result.append(node)
                if len(result) == limit:
                    break
            return {"revision": self.current()["revision"], "nodes": result}

    def _index_assessment(self, assessment: Document) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO assessments VALUES (?,?,?,?)",
            (
                assessment["revision"],
                assessment["interceptor_id"],
                assessment["target_id"],
                canonical(assessment),
            ),
        )

    def record_assessment(self, assessment: Document) -> None:
        with self.lock():
            log = self.state / "assessments.jsonl"
            if assessment["state"] == "pending" and log.exists():
                identity = ("revision", "interceptor_id", "target_id")
                existing = (json.loads(line) for line in log.read_text().splitlines())
                if any(all(item[k] == assessment[k] for k in identity) for item in existing):
                    return
            contents = log.read_text() if log.exists() else ""
            self._write(log, contents + canonical(assessment) + "\n")
            with self.db:
                self._index_assessment(assessment)

    def assessments(self, revision: int) -> list[Document]:
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM assessments WHERE revision=? "
                "ORDER BY interceptor_id,target_id",
                (revision,),
            )
        ]


def open_service(workspace: Path) -> GraphService:
    from typed_graph.application.service import GraphService

    return GraphService(WorkspaceRepository(workspace))
