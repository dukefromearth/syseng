"""Structural publication rules for explicitly registered architecture packages.

These rules cannot prove performance, causal correspondence or the truth of prose.
They prevent typed architectural category errors and unsupported verification claims.
"""

from collections import defaultdict, deque

from typed_graph.architecture.models import (
    PACKAGE_VERSION,
    ROLE_CATALOG,
    OntologyKind,
    OntologyProperties,
    Relation,
    Role,
)
from typed_graph.architecture.schema import (
    BINDING_INTERCEPTOR,
    RELATION_CATALOG,
    architecture_schema,
)
from typed_graph.domain.models import Snapshot

PACKAGE_NAMESPACE = "typed-graph/architecture/"


def validate_architecture(snapshot: Snapshot) -> None:
    schema = snapshot.schema_definition
    if not schema.version.startswith(PACKAGE_NAMESPACE):
        return
    if schema.version != PACKAGE_VERSION:
        raise ValueError(f"Unsupported architecture package: {schema.version}")
    expected = architecture_schema()
    if schema.node_types != expected.node_types:
        raise ValueError("Architecture role schemas must be generated from the canonical package")
    for relation, definition in expected.relations.items():
        if schema.relations.get(relation) != definition:
            raise ValueError(
                f"Architecture relation differs from its canonical contract: {relation}"
            )
    for relation, definition in schema.relations.items():
        if relation not in RELATION_CATALOG and (
            set(definition.source) != {Role.CONCEPT} or set(definition.target) != {Role.CONCEPT}
        ):
            raise ValueError(
                "Additional architecture-domain relations must connect DomainConcept instances"
            )
    if not all(invariant in schema.invariants for invariant in expected.invariants):
        raise ValueError("Architecture publication invariants cannot be removed")
    binding_review = next(
        (item for item in schema.interceptors if item.id == BINDING_INTERCEPTOR.id), None
    )
    if (
        binding_review is None
        or binding_review.target_type != Role.BINDING
        or not set(BINDING_INTERCEPTOR.evidence_required).issubset(binding_review.evidence_required)
    ):
        raise ValueError("Architecture binding assessments must retain their evidence obligations")
    nodes = {node.id: node for node in snapshot.nodes}
    if sum(node.type == Role.MODEL for node in snapshot.nodes) > 1:
        raise ValueError("An architecture workspace has one model identity")
    for node in snapshot.nodes:
        ROLE_CATALOG[Role(node.type)].model_validate(node.properties, strict=True)
    outgoing: dict[tuple[str, str], set[str]] = defaultdict(set)
    sequence_edges: dict[str, set[str]] = defaultdict(set)
    for edge in snapshot.edges:
        outgoing[(edge.source, edge.type)].add(edge.target)
        source, target = nodes[edge.source], nodes[edge.target]
        if edge.type == Relation.NEXT and source.type != target.type:
            raise ValueError("A next relation cannot mix scenario steps and delivery phases")
        if edge.type == Relation.NEXT:
            sequence_edges[edge.source].add(edge.target)
        if (
            edge.type == Relation.SPECIALIZES
            and source.type == Role.CONCEPT
            and target.type != Role.CONCEPT
        ):
            raise ValueError("Domain meaning cannot specialize a realization concept")
        if edge.type == Relation.CONSTRAINS:
            left = OntologyProperties.model_validate(source.properties).kind
            right = OntologyProperties.model_validate(target.properties).kind
            if (left, right) not in {
                (OntologyKind.DOMAIN, OntologyKind.SYSTEM),
                (OntologyKind.SYSTEM, OntologyKind.REALIZATION),
            }:
                raise ValueError("Ontology constraints flow from domain to system to realization")
        if edge.type == Relation.INCLUDES:
            kind = OntologyProperties.model_validate(source.properties).kind
            allowed = {
                OntologyKind.DOMAIN: {Role.CONCEPT, Role.INVARIANT},
                OntologyKind.SYSTEM: {Role.SYSTEM},
                OntologyKind.REALIZATION: {
                    Role.REALIZATION_CONCEPT,
                    Role.ENVIRONMENT,
                    Role.BOUNDARY,
                    Role.CAPABILITY,
                    Role.LAYER,
                    Role.BINDING,
                    Role.TECHNOLOGY,
                },
            }[kind]
            if target.type not in allowed:
                raise ValueError(f"{target.type} cannot be defined by the {kind} ontology")
    indegree = {
        identity: 0 for source, targets in sequence_edges.items() for identity in (source, *targets)
    }
    for targets in sequence_edges.values():
        for target_id in targets:
            indegree[target_id] += 1
    ready = deque(identity for identity, count in indegree.items() if count == 0)
    processed = 0
    while ready:
        identity = ready.popleft()
        processed += 1
        for target_id in sequence_edges.get(identity, set()):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    if processed != len(indegree):
        raise ValueError("Architectural next sequencing cannot contain cycles")
    for node in snapshot.nodes:
        if node.type != Role.INDEPENDENCE:
            continue
        objectives = outgoing[(node.id, Relation.DEMONSTRATES_OBJECTIVE)]
        contracts = outgoing[(node.id, Relation.HOLDS_CONTRACT)]
        candidates = outgoing[(node.id, Relation.COMPARES_BINDING)]
        if len(objectives) != 1 or len(contracts) != 1 or len(candidates) < 2:
            raise ValueError(
                "Independence requires one objective, one contract "
                "and two distinct candidate bindings"
            )
        for candidate in candidates:
            if outgoing[(candidate, Relation.ATTEMPTS_TO_FULFILL)] != contracts:
                raise ValueError(
                    "All alternatives in an independence example must target the same contract"
                )
