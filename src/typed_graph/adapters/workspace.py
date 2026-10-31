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
from typing import TYPE_CHECKING

from pydantic import Field, JsonValue

if TYPE_CHECKING:
    from typed_graph.application.service import GraphService

import yaml

from typed_graph.application.contracts import SearchResult
from typed_graph.domain.models import (
    Assessment,
    AssessmentState,
    Edge,
    GraphSchema,
    Identifier,
    JsonObject,
    ModelDocument,
    Node,
    Revision,
    Snapshot,
    StrictModel,
    dump_wire,
)
from typed_graph.domain.schema import compile_schema

EMPTY_SCHEMA = GraphSchema(version="0", node_types={}, relations={})


class Manifest(StrictModel):
    revision: Revision
    source_baseline: ModelDocument | None = None
    source_fingerprints: dict[str, str] | None = None


class SourceFragment(StrictModel):
    schema_definition: GraphSchema | None = Field(default=None, alias="schema")
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


def canonical(value: StrictModel | JsonValue) -> str:
    return json.dumps(
        dump_wire(value) if isinstance(value, StrictModel) else value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def manifest_for(document: Snapshot) -> Manifest:
    return Manifest(
        revision=document.revision,
        source_baseline=document.source_baseline,
        source_fingerprints=document.source_fingerprints,
    )


def reconcile[T: Node | Edge](base: list[T], authored: list[T], live: list[T]) -> list[T]:
    def keyed(items: list[T]) -> dict[str, T]:
        mapping = {item.id: item for item in items}
        if len(mapping) != len(items):
            raise ValueError("duplicate identities across sources")
        return mapping

    before_map, after_map, live_map = (keyed(items) for items in (base, authored, live))
    result = dict(live_map)
    for identity in before_map.keys() | after_map.keys():
        before, after, present = (
            before_map.get(identity),
            after_map.get(identity),
            live_map.get(identity),
        )
        if before == after:
            continue
        if present != before and present != after:
            raise ValueError(f"source/tool conflict for {identity}")
        if after is None:
            result.pop(identity, None)
        else:
            result[identity] = after
    return sorted(result.values(), key=lambda item: item.id)


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
                initial = Snapshot(
                    revision=0, schema=EMPTY_SCHEMA, nodes=[], edges=[], impact=[], changes=[]
                )
                self._write(self.snapshots / "0.json", canonical(initial))
                self._write(self.state / "manifest.json", canonical(Manifest(revision=0)))
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

    def _manifest(self) -> Manifest:
        return Manifest.model_validate_json((self.state / "manifest.json").read_text())

    def current(self) -> Snapshot:
        manifest = self._manifest()
        return self.read_revision(manifest.revision).model_copy(
            update={
                "source_baseline": manifest.source_baseline,
                "source_fingerprints": manifest.source_fingerprints,
            }
        )

    def read_revision(self, revision: Revision) -> Snapshot:
        if type(revision) is not int or revision < 0:
            raise ValueError("revision must be a nonnegative integer")
        manifest = self.state / "manifest.json"
        if manifest.exists() and revision > self._manifest().revision:
            raise ValueError(f"uncommitted revision {revision}")
        path = self.snapshots / f"{revision}.json"
        if path.is_symlink():
            raise ValueError("snapshot symlinks are forbidden")
        if not path.exists():
            raise ValueError(f"unknown revision {revision}")
        return Snapshot.model_validate_json(path.read_text())

    def _recover(self) -> None:
        current = self.current()
        with self.db:
            self.db.execute("DELETE FROM revisions")
            for revision in range(current.revision + 1):
                doc = self.read_revision(revision)
                self.db.execute("INSERT INTO revisions VALUES (?,?)", (revision, canonical(doc)))
            self.db.execute("DELETE FROM nodes")
            self.db.executemany(
                "INSERT INTO nodes VALUES (?,?,?)",
                [(n.id, n.type, canonical(n.properties)) for n in current.nodes],
            )
            self.db.execute("DELETE FROM edges")
            self.db.executemany(
                "INSERT INTO edges VALUES (?,?,?,?)",
                [(e.id, e.type, e.source, e.target) for e in current.edges],
            )
            self.db.execute("DELETE FROM assessments")
            log = self.state / "assessments.jsonl"
            if log.exists():
                for line in log.read_text().splitlines():
                    assessment = Assessment.model_validate_json(line)
                    self._index_assessment(assessment)

    def import_document(self) -> Snapshot:
        """Three-way reconcile authored fragments through canonical typed codecs."""
        current = self.current()
        source = self.root / "model"
        if not source.exists() and current.source_baseline is None:
            return current
        if source.is_symlink():
            raise ValueError("model directory must not be a symlink")
        schema: GraphSchema | None = None
        nodes: list[Node] = []
        edges: list[Edge] = []
        files: dict[str, str] = {}
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError("model symlinks are forbidden")
            if not path.is_file() or path.suffix not in (".json", ".yaml", ".yml", ".md"):
                continue
            raw = path.read_text()
            files[str(path.relative_to(source))] = hashlib.sha256(raw.encode()).hexdigest()
            blocks = (
                re.findall(r"```graph\s*\n(.*?)```", raw, re.S) if path.suffix == ".md" else [raw]
            )
            for block in blocks:
                data = json.loads(block) if path.suffix == ".json" else yaml.safe_load(block)
                if not isinstance(data, dict):
                    raise ValueError(f"model document must be a mapping: {path.name}")
                if isinstance(data.get("schema"), str):
                    data = {"schema": compile_schema(data)}
                fragment = SourceFragment.model_validate(data)
                if fragment.schema_definition is not None:
                    if schema is not None:
                        raise ValueError("multiple schema sources")
                    schema = fragment.schema_definition
                nodes.extend(fragment.nodes)
                edges.extend(fragment.edges)
        if files == current.source_fingerprints:
            return current
        authored = ModelDocument(
            schema=schema or current.schema_definition, nodes=nodes, edges=edges
        )
        baseline = current.source_baseline or ModelDocument(schema=EMPTY_SCHEMA, nodes=[], edges=[])
        resulting_schema = current.schema_definition
        if authored.schema_definition != baseline.schema_definition:
            if current.schema_definition not in (
                baseline.schema_definition,
                authored.schema_definition,
            ):
                raise ValueError("source/tool schema conflict")
            resulting_schema = authored.schema_definition
        return Snapshot(
            revision=current.revision,
            schema=resulting_schema,
            nodes=reconcile(baseline.nodes, authored.nodes, current.nodes),
            edges=reconcile(baseline.edges, authored.edges, current.edges),
            impact=[],
            changes=[],
            source_baseline=authored,
            source_fingerprints=files,
        )

    def accept_import(self, document: Snapshot, expected_revision: Revision) -> None:
        with self.lock():
            if self.current().revision != expected_revision:
                raise ValueError("revision conflict")
            self._write(self.state / "manifest.json", canonical(manifest_for(document)))

    def commit(self, document: Snapshot, expected_revision: Revision) -> Snapshot:
        with self.lock():
            current = self.current()
            if current.revision != expected_revision:
                raise ValueError(
                    f"revision conflict: expected {expected_revision}, current {current.revision}"
                )
            result = document.model_copy(update={"revision": expected_revision + 1})
            self._write(self.snapshots / f"{result.revision}.json", canonical(result))
            self._write(self.state / "manifest.json", canonical(manifest_for(result)))
            self._index_delta(current, result)
            return result

    def _index_delta(self, old: Snapshot, new: Snapshot) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO revisions VALUES (?,?)", (new.revision, canonical(new))
            )
            old_nodes, new_nodes = ({node.id: node for node in doc.nodes} for doc in (old, new))
            for identity in old_nodes.keys() - new_nodes.keys():
                self.db.execute("DELETE FROM nodes WHERE id=?", (identity,))
            for identity, node in new_nodes.items():
                if old_nodes.get(identity) != node:
                    self.db.execute(
                        "INSERT OR REPLACE INTO nodes VALUES (?,?,?)",
                        (node.id, node.type, canonical(node.properties)),
                    )
            old_edges, new_edges = ({edge.id: edge for edge in doc.edges} for doc in (old, new))
            for identity in old_edges.keys() - new_edges.keys():
                self.db.execute("DELETE FROM edges WHERE id=?", (identity,))
            for identity, edge in new_edges.items():
                if old_edges.get(identity) != edge:
                    self.db.execute(
                        "INSERT OR REPLACE INTO edges VALUES (?,?,?,?)",
                        (edge.id, edge.type, edge.source, edge.target),
                    )

    def search_nodes(
        self, node_type: Identifier | None, where: JsonObject, text: str, limit: int
    ) -> SearchResult:
        with self.lock():
            indexed = self.db.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if indexed != self.current().revision:
                self._recover()
            sql = "SELECT id,type,properties FROM nodes"
            parameters: tuple[str, ...] = ()
            if node_type is not None:
                sql += " WHERE type=?"
                parameters = (node_type,)
            sql += " ORDER BY id"
            result: list[Node] = []
            for identity, kind, raw in self.db.execute(sql, parameters):
                node = Node(id=identity, type=kind, properties=json.loads(raw))
                if not all(
                    k in node.properties and node.properties[k] == v for k, v in where.items()
                ):
                    continue
                if (
                    text
                    and text.casefold()
                    not in json.dumps(dump_wire(node), sort_keys=True).casefold()
                ):
                    continue
                result.append(node)
                if len(result) == limit:
                    break
            return SearchResult(revision=self.current().revision, nodes=result)

    def _index_assessment(self, assessment: Assessment) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO assessments VALUES (?,?,?,?)",
            (
                assessment.revision,
                assessment.interceptor_id,
                assessment.target_id,
                canonical(assessment),
            ),
        )

    def record_assessment(self, assessment: Assessment) -> None:
        with self.lock():
            log = self.state / "assessments.jsonl"
            if assessment.state == AssessmentState.PENDING and log.exists():
                existing = (
                    Assessment.model_validate_json(line) for line in log.read_text().splitlines()
                )
                if any(item.key == assessment.key for item in existing):
                    return
            contents = log.read_text() if log.exists() else ""
            self._write(log, contents + canonical(assessment) + "\n")
            with self.db:
                self._index_assessment(assessment)

    def assessments(self, revision: Revision) -> list[Assessment]:
        return [
            Assessment.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT payload FROM assessments WHERE revision=? "
                "ORDER BY interceptor_id,target_id",
                (revision,),
            )
        ]


def open_service(workspace: Path) -> GraphService:
    from typed_graph.application.service import GraphService

    return GraphService(WorkspaceRepository(workspace))
