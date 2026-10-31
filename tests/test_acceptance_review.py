"""Independent end-to-end contracts through public use cases and durable files."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from typed_graph.adapters.workspace import open_service


def node(identifier, name=None):
    return {"id": identifier, "type": "NovelType", "properties": {"name": name or identifier}}


def model():
    return {
        "schema": {
            "version": "1",
            "node_types": {
                "NovelType": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            },
            "relations": {
                "uses": {
                    "source": ["NovelType"],
                    "target": ["NovelType"],
                    "impact": "target_to_source",
                }
            },
            "interceptors": [
                {
                    "id": "review",
                    "target_type": "NovelType",
                    "handler": "external",
                    "version": "1",
                    "trigger": "dependency_changed",
                    "evidence_required": ["verified"],
                }
            ],
        },
        "nodes": [node("a"), node("b"), node("c")],
        "edges": [
            {"id": "ab", "type": "uses", "source": "a", "target": "b"},
            {"id": "bc", "type": "uses", "source": "b", "target": "c"},
        ],
    }


def boot(path):
    source = path / "model"
    source.mkdir()
    file = source / "input.json"
    file.write_text(json.dumps(model()))
    service = open_service(path)
    service.dispatch("index_model", {})
    return service, file


def apply(service, changes, revision=None):
    return service.dispatch(
        "apply_changes",
        {
            "expected_revision": service.revision if revision is None else revision,
            "changes": changes,
        },
    )


@pytest.mark.parametrize(
    "last",
    [
        {"op": "delete_node", "id": "missing"},
        {"op": "update_node", "id": "b", "type": "NovelType", "properties": {"name": 7}},
        {
            "op": "create_edge",
            "edge": {"id": "bad", "type": "uses", "source": "a", "target": "missing"},
        },
    ],
)
def test_failed_last_operation_is_atomic_across_restart(tmp_path, last):
    service, _ = boot(tmp_path)
    before = service.resource("graph://model/revisions/1")
    with pytest.raises(ValueError):
        apply(service, [{"op": "create_node", "node": node("extra")}, last])
    restarted = open_service(tmp_path)
    assert restarted.revision == 1
    assert restarted.resource("graph://model/revisions/1") == before
    assert len(restarted.dispatch("query_graph", {})["nodes"]) == 3


def test_concurrent_connections_have_exactly_one_expected_revision_winner(tmp_path):
    first, _ = boot(tmp_path)
    second = open_service(tmp_path)
    barrier = Barrier(2)

    def write(service, identifier):
        barrier.wait()
        try:
            return apply(service, [{"op": "create_node", "node": node(identifier)}], 1)
        except ValueError:
            return None

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(write, first, "x"), pool.submit(write, second, "y")]
        outcomes = [future.result() for future in futures]
    assert sum(value is not None for value in outcomes) == 1
    reopened = open_service(tmp_path)
    assert reopened.revision == 2
    assert len(reopened.dispatch("query_graph", {})["nodes"]) == 4


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"op": "update_node", **node("a")}],
        [{"op": "create_node", "node": node("temp")}, {"op": "delete_node", "id": "temp"}],
    ],
)
def test_semantic_noops_do_not_advance_revision(tmp_path, changes):
    service, _ = boot(tmp_path)
    assert apply(service, changes) == {"revision": 1, "applied_changes": [], "invalidations": []}


@pytest.mark.parametrize("delete_node", [False, True])
def test_removed_connection_retains_old_dependency_impact(tmp_path, delete_node):
    service, _ = boot(tmp_path)
    changes = [{"op": "delete_edge", "id": "bc"}]
    if delete_node:
        changes.append({"op": "delete_node", "id": "c"})
    result = apply(service, changes)
    assert {"a", "b"} <= {item["node_id"] for item in result["invalidations"]}
    a = next(item for item in result["invalidations"] if item["node_id"] == "a")
    assert ["c", "b", "a"] in a["paths"]


def test_late_evidence_does_not_complete_new_revision(tmp_path):
    service, _ = boot(tmp_path)
    apply(service, [{"op": "update_node", **node("c", "changed")}])
    result = service.dispatch(
        "submit_assessment",
        {
            "revision": 1,
            "interceptor_id": "review",
            "target_id": "a",
            "result": {
                "status": "pass",
                "findings": [],
                "evidence": [{"obligation": "verified", "uri": "artifact:proof"}],
            },
        },
    )
    assert result["assessment"]["stale"] is True
    current = service.dispatch("get_assessments", {})["assessments"]
    assert all(item["state"] == "pending" for item in current)
    with pytest.raises(ValueError):
        service.dispatch(
            "submit_assessment",
            {
                "revision": 2,
                "interceptor_id": "review",
                "target_id": "a",
                "result": {"status": "pass", "findings": [], "evidence": []},
            },
        )
    assert (
        open_service(tmp_path).dispatch("get_assessments", {"revision": 1})["assessments"][0][
            "result"
        ]["status"]
        == "pass"
    )


def test_source_updates_preserve_disjoint_tool_edits_and_detect_conflicts(tmp_path):
    service, file = boot(tmp_path)
    apply(service, [{"op": "create_node", "node": node("tool")}])
    imported = model()
    imported["nodes"][2] = node("c", "file edit")
    file.write_text(json.dumps(imported))
    service.dispatch("index_model", {})
    assert "tool" in {n["id"] for n in service.dispatch("query_graph", {})["nodes"]}
    apply(service, [{"op": "update_node", **node("c", "tool edit")}])
    imported["nodes"][2] = node("c", "conflicting file edit")
    file.write_text(json.dumps(imported))
    previous = service.revision
    with pytest.raises(ValueError):
        service.dispatch("index_model", {})
    assert service.revision == previous
    assert service.resource("graph://model/nodes/c")["node"]["properties"]["name"] == "tool edit"


@pytest.mark.parametrize("replacement", ["invalid-json", '{"nodes": [{"id":"broken"}]}'])
def test_failed_source_import_preserves_last_graph(tmp_path, replacement):
    service, file = boot(tmp_path)
    file.write_text(replacement)
    with pytest.raises(ValueError):
        service.dispatch("index_model", {})
    assert service.revision == 1
    assert len(service.dispatch("query_graph", {})["nodes"]) == 3


def test_source_file_deletion_reconciles_only_owned_entities(tmp_path):
    service, file = boot(tmp_path)
    apply(service, [{"op": "create_node", "node": node("tool")}])
    file.unlink()
    service.dispatch("index_model", {})
    assert service.dispatch("query_graph", {})["nodes"] == [node("tool")]


def test_rebuild_index_from_committed_source_preserves_history(tmp_path):
    service, _ = boot(tmp_path)
    apply(service, [{"op": "update_node", **node("c", "new")}])
    with sqlite3.connect(tmp_path / ".graph/index.sqlite3") as db:
        db.execute("DELETE FROM nodes")
        db.execute("DELETE FROM revisions")
    reopened = open_service(tmp_path)
    assert reopened.revision == 2
    assert len(reopened.dispatch("query_graph", {})["nodes"]) == 3
    assert reopened.dispatch("compare_graphs", {"from_revision": 1, "to_revision": 2})["nodes"][
        "updated"
    ] == ["c"]
    with sqlite3.connect(tmp_path / ".graph/index.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM nodes").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 3


def test_uncommitted_crash_snapshot_is_not_readable_revision(tmp_path):
    service, _ = boot(tmp_path)
    uncommitted = service.resource("graph://model/revisions/1")
    uncommitted["revision"] = 2
    (tmp_path / ".graph/snapshots/2.json").write_text(json.dumps(uncommitted))
    reopened = open_service(tmp_path)
    assert reopened.revision == 1
    with pytest.raises(ValueError):
        reopened.resource("graph://model/revisions/2")


@pytest.mark.parametrize("format", ["json", "yaml", "md"])
def test_source_symlink_cannot_import_outside_workspace(tmp_path, format):
    service, _ = boot(tmp_path)
    outside = tmp_path.parent / f"outside.{format}"
    outside.write_text("{}")
    (tmp_path / "model" / f"escape.{format}").symlink_to(outside)
    with pytest.raises(ValueError):
        service.dispatch("index_model", {})
    assert service.revision == 1


def test_schema_relation_direction_edit_invalidates_existing_dependents(tmp_path):
    service, file = boot(tmp_path)
    authored = model()
    authored["schema"]["relations"]["uses"]["impact"] = "none"
    file.write_text(json.dumps(authored))
    result = service.dispatch("index_model", {})
    assert result["revision"] == 2
    assert {item["node_id"] for item in result["invalidations"]} == {"a", "b", "c"}
    assert ["c", "b", "a"] in next(
        item for item in result["invalidations"] if item["node_id"] == "a"
    )["paths"]


def test_scc_cycle_has_one_assessment_per_target_and_stable_provenance(tmp_path):
    service, _ = boot(tmp_path)
    apply(
        service,
        [{"op": "create_edge", "edge": {"id": "ca", "type": "uses", "source": "c", "target": "a"}}],
    )
    result = apply(service, [{"op": "update_node", **node("c", "changed")}])
    assert [item["node_id"] for item in result["invalidations"]] == ["a", "b", "c"]
    assessments = service.dispatch("get_assessments", {})["assessments"]
    assert len(assessments) == 3
    assert len({(a["revision"], a["interceptor_id"], a["target_id"]) for a in assessments}) == 3
    assert assessments == service.dispatch("get_assessments", {})["assessments"]


def test_hexagonal_import_contract():
    """Architectural dependency rule, without inspecting implementation methods."""
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "src" / "typed_graph"
    forbidden = {
        "domain": ("typed_graph.application", "typed_graph.adapters"),
        "application": ("typed_graph.adapters",),
    }
    io_modules = {"sqlite3", "pathlib", "os", "subprocess", "socket", "requests", "httpx", "mcp"}
    violations = []
    for layer, prefixes in forbidden.items():
        for file in (root / layer).glob("*.py"):
            for item in ast.walk(ast.parse(file.read_text())):
                names = []
                if isinstance(item, ast.Import):
                    names = [alias.name for alias in item.names]
                elif isinstance(item, ast.ImportFrom):
                    names = [item.module or ""]
                    if item.level:
                        violations.append(f"{file.name}: relative import requires review")
                for name in names:
                    if name.startswith(prefixes) or name.split(".")[0] in io_modules:
                        violations.append(f"{layer}/{file.name}: {name}")
    assert violations == []


def test_search_filters_before_applying_result_limit(tmp_path):
    service, _ = boot(tmp_path)
    assert service.dispatch("search_graph", {"text": "c", "limit": 1})["nodes"] == [node("c")]


def test_removing_source_directory_reconciles_owned_graph(tmp_path):
    service, file = boot(tmp_path)
    file.unlink()
    file.parent.rmdir()
    service.dispatch("index_model", {})
    assert service.dispatch("query_graph", {})["nodes"] == []


@pytest.mark.parametrize("format", ["json", "yaml", "md"])
def test_supported_source_formats_expose_identical_typed_graph(tmp_path, format):
    import yaml

    source = tmp_path / "model"
    source.mkdir()
    authored = model()
    if format == "json":
        content = json.dumps(authored)
    else:
        content = yaml.safe_dump(authored)
        if format == "md":
            content = "# Authored graph\n\n```graph\n" + content + "```\n"
    (source / f"input.{format}").write_text(content)
    service = open_service(tmp_path)
    service.dispatch("index_model", {})
    assert service.dispatch("query_graph", {"type": "NovelType"})["nodes"] == authored["nodes"]
    assert service.dispatch("trace_path", {"source": "a", "target": "c"})["path"] == ["a", "b", "c"]


def test_existing_connection_queries_latest_committed_revision(tmp_path):
    first, _ = boot(tmp_path)
    second = open_service(tmp_path)
    apply(first, [{"op": "create_node", "node": node("z", "unique query text")}])
    query = second.dispatch("query_graph", {"where": {"name": "unique query text"}})
    assert query["revision"] == 2
    assert query["nodes"] == [node("z", "unique query text")]
    search = second.dispatch("search_graph", {"text": "unique query text"})
    assert search["revision"] == 2
    assert search["nodes"] == query["nodes"]


def test_committed_snapshot_rebuilds_missing_index_and_pending_work_after_crash(tmp_path):
    service, _ = boot(tmp_path)
    before = service.resource("graph://model/revisions/1")
    # Model a power loss after source commit and before the derived index/work queue.
    (tmp_path / ".graph/assessments.jsonl").unlink()
    with sqlite3.connect(tmp_path / ".graph/index.sqlite3") as db:
        db.execute("DELETE FROM assessments")
        db.execute("DELETE FROM nodes")
        db.execute("DELETE FROM revisions")
    reopened = open_service(tmp_path)
    assert reopened.resource("graph://model/revisions/1") == before
    assessments = reopened.dispatch("get_assessments", {})["assessments"]
    assert len(assessments) == 3
    assert all(item["state"] == "pending" for item in assessments)
    assert len(reopened.dispatch("query_graph", {})["nodes"]) == 3


def test_detect_changes_previews_transitive_impact_without_committing(tmp_path):
    service, file = boot(tmp_path)
    authored = model()
    authored["nodes"][2] = node("c", "proposed change")
    file.write_text(json.dumps(authored))
    preview = service.dispatch("detect_changes", {})
    assert preview["changed_nodes"] == ["c"]
    assert preview["preview_revision"] == 2
    assert {item["node_id"] for item in preview["impact"]} == {"a", "b", "c"}
    assert service.revision == 1
    assert service.resource("graph://model/nodes/c")["node"] == node("c")
    committed = service.dispatch("index_model", {})
    assert committed["invalidations"] == preview["impact"]


@pytest.mark.parametrize(
    "mode,source,target,path",
    [
        ("semantic", "a", "c", ["a", "b", "c"]),
        ("semantic", "c", "a", []),
        ("dependency", "c", "a", ["c", "b", "a"]),
        ("dependency", "a", "c", []),
    ],
)
def test_path_traversal_distinguishes_semantics_and_dependency_direction(
    tmp_path, mode, source, target, path
):
    service, _ = boot(tmp_path)
    assert (
        service.dispatch(
            "trace_path", {"source": source, "target": target, "mode": mode, "relation": "uses"}
        )["path"]
        == path
    )


def test_concurrent_indexed_queries_stamp_the_exact_snapshot_read(tmp_path):
    from threading import Event

    writer, _ = boot(tmp_path)
    reader = open_service(tmp_path)
    done = Event()

    def update_revisions():
        try:
            for revision in range(2, 22):
                apply(writer, [{"op": "update_node", **node("c", str(revision))}])
        finally:
            done.set()

    def read_revisions():
        results = []
        while not done.is_set():
            for tool in ("query_graph", "search_graph"):
                result = reader.dispatch(tool, {})
                name = next(n["properties"]["name"] for n in result["nodes"] if n["id"] == "c")
                expected = "c" if result["revision"] == 1 else str(result["revision"])
                results.append((name, expected))
        return results

    with ThreadPoolExecutor(2) as pool:
        reading = pool.submit(read_revisions)
        writing = pool.submit(update_revisions)
        writing.result()
        results = reading.result()
    assert results
    assert all(actual == expected for actual, expected in results)
