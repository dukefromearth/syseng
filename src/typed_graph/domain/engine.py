"""Pure validation, mutation planning and deterministic dependency traversal."""

from __future__ import annotations

import copy
import heapq
import json
from collections import deque
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry

from typed_graph.domain.schema import GraphError, apply_input_schema, validate_schema


def _validate(instance: Any, schema: Any) -> None:
    try:
        Draft202012Validator(schema, registry=Registry()).validate(instance)
    except Exception as exc:
        # Reference resolution failures are also authored contract errors, never network fallbacks.
        raise GraphError(f"Schema validation failed: {exc}") from exc


def _indexed(items: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise GraphError(f"{kind} collection must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise GraphError(f"{kind} requires nonempty string id")
        if item["id"] in result:
            raise GraphError(f"Duplicate {kind} id: {item['id']}")
        result[item["id"]] = item
    return result


def validate_graph(
    schema: dict[str, Any], nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    validate_schema(schema)
    node_map = _indexed(nodes, "node")
    _indexed(edges, "edge")
    for node in nodes:
        if (
            set(node) != {"id", "type", "properties"}
            or not isinstance(node.get("type"), str)
            or node.get("type") not in schema["node_types"]
        ):
            raise GraphError(f"Node {node['id']} requires registered type and properties")
        if not isinstance(node["properties"], dict):
            raise GraphError("Node properties must be an object")
        _validate(node["properties"], schema["node_types"][node["type"]])
    counts: dict[tuple[str, str, str], int] = {}
    for edge in edges:
        if (
            set(edge) - {"id", "type", "source", "target", "properties"}
            or not {"id", "type", "source", "target"}.issubset(edge)
            or not isinstance(edge.get("type"), str)
            or edge.get("type") not in schema["relations"]
        ):
            raise GraphError(f"Edge {edge['id']} requires registered relation and endpoints")
        relation = schema["relations"][edge["type"]]
        for endpoint, direction in (("source", "out"), ("target", "in")):
            identifier = edge.get(endpoint)
            if not isinstance(identifier, str) or identifier not in node_map:
                raise GraphError(f"Missing edge {endpoint}: {identifier}")
            if node_map[identifier]["type"] not in relation[endpoint]:
                raise GraphError(f"Invalid {endpoint} type for relation {edge['type']}")
            key = (edge["type"], identifier, direction)
            counts[key] = counts.get(key, 0) + 1
        if not isinstance(edge.get("properties", {}), dict):
            raise GraphError("Edge properties must be an object")
        _validate(
            edge.get("properties", {}),
            relation.get("properties", {"type": "object", "additionalProperties": False}),
        )
    for name, relation in schema["relations"].items():
        limits = relation.get("cardinality", {})
        for node in nodes:
            for direction, endpoint in (("out", "source"), ("in", "target")):
                if node["type"] not in relation[endpoint]:
                    continue
                count = counts.get((name, node["id"], direction), 0)
                if (
                    not limits.get(f"{direction}_min", 0)
                    <= count
                    <= limits.get(f"{direction}_max", float("inf"))
                ):
                    raise GraphError(f"Cardinality violated: {name} {node['id']} {direction}")
    for invariant in schema.get("invariants", []):
        selected = [n for n in nodes if n["type"] == invariant["node_type"]]
        if invariant["kind"] == "unique":
            seen: set[str] = set()
            for node in selected:
                if invariant["property"] not in node["properties"]:
                    raise GraphError("unique invariant property is absent")
                value = json.dumps(node["properties"][invariant["property"]], sort_keys=True)
                if value in seen:
                    raise GraphError(f"unique invariant violated: {invariant['property']}")
                seen.add(value)
        else:
            for node in selected:
                count = counts.get(
                    (invariant["relation"], node["id"], invariant.get("direction", "out")), 0
                )
                if count < invariant.get("min", 1):
                    raise GraphError(f"requires_edge violated: {node['id']}")


def apply_operations(
    schema: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    _validate({"expected_revision": 0, "changes": operations}, apply_input_schema(schema))
    node_map = copy.deepcopy(_indexed(nodes, "node"))
    edge_map = copy.deepcopy(_indexed(edges, "edge"))
    for operation in operations:
        action, kind = operation["op"].split("_", 1)
        target = node_map if kind == "node" else edge_map
        item = (
            operation[kind]
            if action == "create"
            else {key: value for key, value in operation.items() if key != "op"}
        )
        identifier = item["id"]
        if action == "create" and identifier in target:
            raise GraphError(f"{kind} already exists: {identifier}")
        if action != "create" and identifier not in target:
            raise GraphError(f"Unknown {kind}: {identifier}")
        if action == "delete":
            del target[identifier]
        else:
            target[identifier] = copy.deepcopy(item)
    new_nodes = sorted(node_map.values(), key=lambda item: item["id"])
    new_edges = sorted(edge_map.values(), key=lambda item: item["id"])
    validate_graph(schema, new_nodes, new_edges)
    before_nodes = _indexed(nodes, "node")
    before_edges = _indexed(edges, "edge")
    changed = {
        identifier
        for identifier in before_nodes.keys() | node_map.keys()
        if before_nodes.get(identifier) != node_map.get(identifier)
    }
    for identifier in before_edges.keys() | edge_map.keys():
        old_edge, new_edge = before_edges.get(identifier), edge_map.get(identifier)
        if old_edge != new_edge:
            for edge in (old_edge, new_edge):
                if edge:
                    changed.update((edge["source"], edge["target"]))
    return new_nodes, new_edges, sorted(changed)


def _components(
    adjacency: dict[str, set[str]], identifiers: set[str]
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Iterative Kosaraju SCCs and stable topological condensation ordering."""
    visited: set[str] = set()
    finished: list[str] = []
    for root in sorted(identifiers):
        stack = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                finished.append(node)
            elif node not in visited:
                visited.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False)
                    for child in sorted(adjacency.get(node, set()), reverse=True)
                    if child not in visited
                )
    reverse: dict[str, set[str]] = {}
    for source, targets in adjacency.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    components: dict[str, list[str]] = {}
    for root in reversed(finished):
        if root in components:
            continue
        members: list[str] = []
        pending = [root]
        components[root] = members
        while pending:
            node = pending.pop()
            members.append(node)
            for parent in sorted(reverse.get(node, set()), reverse=True):
                if parent not in components:
                    components[parent] = members
                    pending.append(parent)
        members.sort()
    condensed: dict[str, set[str]] = {members[0]: set() for members in components.values()}
    indegree = dict.fromkeys(condensed, 0)
    for source, targets in adjacency.items():
        source_component = components[source][0]
        for target in targets:
            target_component = components[target][0]
            if (
                source_component != target_component
                and target_component not in condensed[source_component]
            ):
                condensed[source_component].add(target_component)
                indegree[target_component] += 1
    ready = [component for component, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: dict[str, int] = {}
    while ready:
        component = heapq.heappop(ready)
        order[component] = len(order)
        for target in sorted(condensed[component]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    return components, order


def compute_impact(
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    old_nodes: list[dict[str, Any]],
    old_edges: list[dict[str, Any]],
    new_nodes: list[dict[str, Any]],
    new_edges: list[dict[str, Any]],
    changed_ids: list[str],
    revision: int,
) -> list[dict[str, Any]]:
    """One shortest lexicographic path per root/target; old dependencies survive deletion."""
    adjacency: dict[str, set[str]] = {}
    for schema, edges in ((old_schema, old_edges), (new_schema, new_edges)):
        for edge in edges:
            impact = schema.get("relations", {}).get(edge["type"], {}).get("impact", "none")
            source, target = edge["source"], edge["target"]
            if impact in {"source_to_target", "both"}:
                adjacency.setdefault(source, set()).add(target)
            if impact in {"target_to_source", "both"}:
                adjacency.setdefault(target, set()).add(source)
    existing = {node["id"] for node in new_nodes}
    roots = set(changed_ids)
    if old_schema != new_schema:
        roots.update(node["id"] for node in old_nodes + new_nodes)
    identifiers = {node["id"] for node in old_nodes + new_nodes}
    components, order = _components(adjacency, identifiers)
    paths: dict[str, list[list[str]]] = {}
    for root in sorted(roots):
        queue = deque([[root]])
        visited = {root}
        while queue:
            path = queue.popleft()
            target = path[-1]
            if target in existing:
                paths.setdefault(target, []).append(path)
            for dependent in sorted(adjacency.get(target, set())):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append([*path, dependent])
    return [
        {
            "node_id": identifier,
            "paths": paths[identifier],
            "triggering_revision": revision,
            "component_id": components[identifier][0],
            "component": components[identifier],
        }
        for identifier in sorted(paths, key=lambda node: (order[components[node][0]], node))
    ]
