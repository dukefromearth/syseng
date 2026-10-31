"""Pure typed graph validation, atomic mutation planning and dependency traversal."""

from __future__ import annotations

import heapq
import json
from collections import deque

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError
from referencing import Registry

from typed_graph.domain.models import (
    ApplyChangesRequest,
    Change,
    CreateEdge,
    CreateNode,
    DeleteEdge,
    DeleteNode,
    Edge,
    GraphSchema,
    Impact,
    ImpactDirection,
    JsonObject,
    JsonSchema,
    Node,
    UpdateEdge,
    UpdateNode,
    dump_wire,
)
from typed_graph.domain.schema import GraphError, apply_input_schema, validate_typed_schema


def _validate(instance: JsonObject, schema: JsonSchema | None) -> None:
    if schema is None:
        raise GraphError("JSON Schema cannot be null")
    try:
        Draft202012Validator(schema, registry=Registry()).validate(instance)
    except Exception as exc:
        raise GraphError(f"Schema validation failed: {exc}") from exc


def _indexed[T: Node | Edge](items: list[T], kind: str) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        if item.id in result:
            raise GraphError(f"Duplicate {kind} id: {item.id}")
        result[item.id] = item
    return result


def validate_typed_graph(schema: GraphSchema, nodes: list[Node], edges: list[Edge]) -> None:
    validate_typed_schema(schema)
    node_map = _indexed(nodes, "node")
    _indexed(edges, "edge")
    for node in nodes:
        if node.type not in schema.node_types:
            raise GraphError(f"Node {node.id} has unregistered type")
        _validate(node.properties, schema.node_types[node.type])
    counts: dict[tuple[str, str, str], int] = {}
    for edge in edges:
        if edge.type not in schema.relations:
            raise GraphError(f"Edge {edge.id} has unregistered relation")
        relation = schema.relations[edge.type]
        for identifier, allowed, direction in (
            (edge.source, relation.source, "out"),
            (edge.target, relation.target, "in"),
        ):
            if identifier not in node_map:
                raise GraphError(f"Missing edge endpoint: {identifier}")
            if node_map[identifier].type not in allowed:
                raise GraphError(f"Invalid endpoint type for relation {edge.type}")
            key = (edge.type, identifier, direction)
            counts[key] = counts.get(key, 0) + 1
        _validate(edge.properties, relation.property_schema)

    for name, relation in schema.relations.items():
        if relation.cardinality is None:
            continue
        limits = relation.cardinality
        for node in nodes:
            for direction, allowed, minimum, maximum in (
                ("out", relation.source, limits.out_min, limits.out_max),
                ("in", relation.target, limits.in_min, limits.in_max),
            ):
                if node.type not in allowed:
                    continue
                count = counts.get((name, node.id, direction), 0)
                if (minimum is not None and count < minimum) or (
                    maximum is not None and count > maximum
                ):
                    raise GraphError(f"Cardinality violated: {name} {node.id} {direction}")
    for invariant in schema.invariants:
        selected = [node for node in nodes if node.type == invariant.node_type]
        if invariant.kind == "unique":
            seen: set[str] = set()
            for node in selected:
                if invariant.property not in node.properties:
                    raise GraphError("unique invariant property is absent")
                value = json.dumps(node.properties[invariant.property], sort_keys=True)
                if value in seen:
                    raise GraphError(f"unique invariant violated: {invariant.property}")
                seen.add(value)
        else:
            for node in selected:
                if (
                    counts.get((invariant.relation, node.id, invariant.direction), 0)
                    < invariant.min
                ):
                    raise GraphError(f"requires_edge violated: {node.id}")


def apply_typed_operations(
    schema: GraphSchema,
    nodes: list[Node],
    edges: list[Edge],
    operations: list[Change],
) -> tuple[list[Node], list[Edge], list[str]]:
    node_map = {key: node.model_copy(deep=True) for key, node in _indexed(nodes, "node").items()}
    edge_map = {key: edge.model_copy(deep=True) for key, edge in _indexed(edges, "edge").items()}
    for operation in operations:
        if isinstance(operation, CreateNode):
            if operation.node.id in node_map:
                raise GraphError(f"node already exists: {operation.node.id}")
            node_map[operation.node.id] = operation.node.model_copy(deep=True)
        elif isinstance(operation, CreateEdge):
            if operation.edge.id in edge_map:
                raise GraphError(f"edge already exists: {operation.edge.id}")
            edge_map[operation.edge.id] = operation.edge.model_copy(deep=True)
        elif isinstance(operation, UpdateNode | DeleteNode):
            if operation.id not in node_map:
                raise GraphError(f"Unknown node: {operation.id}")
            if isinstance(operation, DeleteNode):
                del node_map[operation.id]
            else:
                node_map[operation.id] = Node(
                    id=operation.id,
                    type=operation.type,
                    properties=operation.properties,
                ).model_copy(deep=True)
        elif isinstance(operation, UpdateEdge | DeleteEdge):
            if operation.id not in edge_map:
                raise GraphError(f"Unknown edge: {operation.id}")
            if isinstance(operation, DeleteEdge):
                del edge_map[operation.id]
            else:
                updated = Edge(
                    id=operation.id,
                    type=operation.type,
                    source=operation.source,
                    target=operation.target,
                )
                if "properties" in operation.model_fields_set:
                    updated.properties = operation.properties
                edge_map[operation.id] = updated.model_copy(deep=True)
    new_nodes = sorted(node_map.values(), key=lambda node: node.id)
    new_edges = sorted(edge_map.values(), key=lambda edge: edge.id)
    validate_typed_graph(schema, new_nodes, new_edges)
    return new_nodes, new_edges, changed_node_ids(nodes, edges, new_nodes, new_edges)


def changed_node_ids(
    old_nodes: list[Node],
    old_edges: list[Edge],
    new_nodes: list[Node],
    new_edges: list[Edge],
) -> list[str]:
    """Canonical invalidation roots for any imported or applied graph delta."""
    before_nodes, before_edges = _indexed(old_nodes, "node"), _indexed(old_edges, "edge")
    node_map, edge_map = _indexed(new_nodes, "node"), _indexed(new_edges, "edge")
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
                    changed.update((edge.source, edge.target))
    return sorted(changed)


def dependency_adjacency(
    schema: GraphSchema,
    edges: list[Edge],
    relation: str | None = None,
) -> dict[str, set[str]]:
    """One definition of impact direction for propagation and dependency queries."""
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        if relation is not None and edge.type != relation:
            continue
        impact = schema.relations[edge.type].impact
        if impact in {ImpactDirection.SOURCE_TO_TARGET, ImpactDirection.BOTH}:
            adjacency.setdefault(edge.source, set()).add(edge.target)
        if impact in {ImpactDirection.TARGET_TO_SOURCE, ImpactDirection.BOTH}:
            adjacency.setdefault(edge.target, set()).add(edge.source)
    return adjacency


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


def compute_typed_impact(
    old_schema: GraphSchema,
    new_schema: GraphSchema,
    old_nodes: list[Node],
    old_edges: list[Edge],
    new_nodes: list[Node],
    new_edges: list[Edge],
    changed_ids: list[str],
    revision: int,
) -> list[Impact]:
    adjacency = dependency_adjacency(old_schema, old_edges)
    for source, targets in dependency_adjacency(new_schema, new_edges).items():
        adjacency.setdefault(source, set()).update(targets)
    existing = {node.id for node in new_nodes}
    roots = set(changed_ids)
    if old_schema != new_schema:
        roots.update(node.id for node in old_nodes + new_nodes)
    identifiers = {node.id for node in old_nodes + new_nodes}
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
        Impact(
            node_id=identifier,
            paths=paths[identifier],
            triggering_revision=revision,
            component_id=components[identifier][0],
            component=components[identifier],
        )
        for identifier in sorted(paths, key=lambda node: (order[components[node][0]], node))
    ]


# Compatibility boundaries for language-neutral callers. The core above uses canonical models.
_NODE_LIST = TypeAdapter(list[Node])
_EDGE_LIST = TypeAdapter(list[Edge])


def validate_graph(
    schema: JsonObject,
    nodes: list[JsonObject],
    edges: list[JsonObject],
) -> None:
    try:
        validate_typed_graph(
            GraphSchema.model_validate(schema),
            _NODE_LIST.validate_python(nodes, strict=True),
            _EDGE_LIST.validate_python(edges, strict=True),
        )
    except ValidationError as exc:
        raise GraphError(str(exc)) from exc


def apply_operations(
    schema: JsonObject,
    nodes: list[JsonObject],
    edges: list[JsonObject],
    operations: list[JsonObject],
) -> tuple[list[JsonObject], list[JsonObject], list[str]]:
    try:
        request = ApplyChangesRequest.model_validate(
            {"expected_revision": 0, "changes": operations}
        )
        _validate(dump_wire(request), apply_input_schema(schema))
        updated_nodes, updated_edges, changed = apply_typed_operations(
            GraphSchema.model_validate(schema),
            _NODE_LIST.validate_python(nodes, strict=True),
            _EDGE_LIST.validate_python(edges, strict=True),
            request.changes,
        )
        return (
            [dump_wire(node) for node in updated_nodes],
            [dump_wire(edge) for edge in updated_edges],
            changed,
        )
    except ValidationError as exc:
        raise GraphError(str(exc)) from exc


def compute_impact(
    old_schema: JsonObject,
    new_schema: JsonObject,
    old_nodes: list[JsonObject],
    old_edges: list[JsonObject],
    new_nodes: list[JsonObject],
    new_edges: list[JsonObject],
    changed_ids: list[str],
    revision: int,
) -> list[JsonObject]:
    try:
        return [
            dump_wire(impact)
            for impact in compute_typed_impact(
                GraphSchema.model_validate(old_schema),
                GraphSchema.model_validate(new_schema),
                _NODE_LIST.validate_python(old_nodes, strict=True),
                _EDGE_LIST.validate_python(old_edges, strict=True),
                _NODE_LIST.validate_python(new_nodes, strict=True),
                _EDGE_LIST.validate_python(new_edges, strict=True),
                changed_ids,
                revision,
            )
        ]
    except ValidationError as exc:
        raise GraphError(str(exc)) from exc
