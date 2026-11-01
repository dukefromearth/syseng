"""Ergonomic semantic tools compile to one ordinary atomic graph change batch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from typed_graph.application.contracts import ApplyRequest, ToolSpec
from typed_graph.architecture.models import (
    PACKAGE_VERSION,
    BaseProperties,
    BindingProperties,
    BoundaryProperties,
    ConceptProperties,
    ContractProperties,
    LayerProperties,
    Relation,
    ResponsibilityProperties,
    Role,
    SystemProperties,
)
from typed_graph.domain.models import (
    ApplyResult,
    Change,
    CreateEdge,
    CreateNode,
    Edge,
    GraphSchema,
    Identifier,
    Node,
    Omittable,
    Revision,
    StrictModel,
    dump_wire,
)


class RevisionRequest(StrictModel):
    expected_revision: Revision
    id: Identifier


class DefineSystemRequest(RevisionRequest):
    system: SystemProperties
    responsibility: ResponsibilityProperties
    contract: ContractProperties
    concerns: list[Identifier] = Field(default_factory=list)
    invariants: list[Identifier] = Field(default_factory=list)
    capabilities: list[Identifier] = Field(default_factory=list)


class DefineConceptRequest(RevisionRequest):
    concept: ConceptProperties
    specializes: Omittable[Identifier] = None


class AddLayerRequest(RevisionRequest):
    layer: LayerProperties


class DefineBoundaryRequest(RevisionRequest):
    boundary: BoundaryProperties
    environment: Omittable[Identifier] = None
    layers: list[Identifier] = Field(default_factory=list)
    capabilities: list[Identifier] = Field(default_factory=list)


class ProposeBindingRequest(RevisionRequest):
    binding: BindingProperties
    contract: Identifier
    boundaries: Annotated[list[Identifier], Field(min_length=1)]
    capabilities: list[Identifier] = Field(default_factory=list)
    invariants: list[Identifier] = Field(default_factory=list)


def _node(identity: str, role: Role, properties: BaseProperties) -> CreateNode:
    return CreateNode(
        op="create_node", node=Node(id=identity, type=role, properties=dump_wire(properties))
    )


def _edge(relation: Relation, source: str, target: str) -> CreateEdge:
    return CreateEdge(
        op="create_edge",
        edge=Edge(
            id=f"{relation}:{source}:{target}",
            type=relation,
            source=source,
            target=target,
        ),
    )


def _system(request: DefineSystemRequest) -> ApplyRequest:
    responsibility, contract = f"{request.id}-responsibility", f"{request.id}-contract"
    changes: list[Change] = [
        _node(request.id, Role.SYSTEM, request.system),
        _node(responsibility, Role.RESPONSIBILITY, request.responsibility),
        _node(contract, Role.CONTRACT, request.contract),
        _edge(Relation.OWNS, request.id, responsibility),
        _edge(Relation.SPECIFIED_BY, responsibility, contract),
    ]
    changes.extend(
        _edge(Relation.CONCERNS, responsibility, target) for target in sorted(set(request.concerns))
    )
    changes.extend(
        _edge(Relation.MUST_PRESERVE, contract, target)
        for target in sorted(set(request.invariants))
    )
    changes.extend(
        _edge(Relation.REQUIRES_CAPABILITY, contract, target)
        for target in sorted(set(request.capabilities))
    )
    return ApplyRequest(expected_revision=request.expected_revision, changes=changes)


def _concept(request: DefineConceptRequest) -> ApplyRequest:
    changes: list[Change] = [_node(request.id, Role.CONCEPT, request.concept)]
    if request.specializes is not None:
        changes.append(_edge(Relation.SPECIALIZES, request.id, request.specializes))
    return ApplyRequest(expected_revision=request.expected_revision, changes=changes)


def _layer(request: AddLayerRequest) -> ApplyRequest:
    return ApplyRequest(
        expected_revision=request.expected_revision,
        changes=[_node(request.id, Role.LAYER, request.layer)],
    )


def _boundary(request: DefineBoundaryRequest) -> ApplyRequest:
    changes: list[Change] = [_node(request.id, Role.BOUNDARY, request.boundary)]
    if request.environment is not None:
        changes.append(_edge(Relation.EXPOSES, request.environment, request.id))
    changes.extend(
        _edge(Relation.CLASSIFIED_BY, request.id, target) for target in sorted(set(request.layers))
    )
    changes.extend(
        _edge(Relation.PROVIDES, request.id, target) for target in sorted(set(request.capabilities))
    )
    return ApplyRequest(expected_revision=request.expected_revision, changes=changes)


def _binding(request: ProposeBindingRequest) -> ApplyRequest:
    changes: list[Change] = [
        _node(request.id, Role.BINDING, request.binding),
        _edge(Relation.ATTEMPTS_TO_FULFILL, request.id, request.contract),
    ]
    changes.extend(
        _edge(Relation.USES_BOUNDARY, request.id, target)
        for target in sorted(set(request.boundaries))
    )
    changes.extend(
        _edge(Relation.REQUIRES_CAPABILITY, request.id, target)
        for target in sorted(set(request.capabilities))
    )
    changes.extend(
        _edge(Relation.MUST_PRESERVE, request.id, target)
        for target in sorted(set(request.invariants))
    )
    return ApplyRequest(expected_revision=request.expected_revision, changes=changes)


@dataclass(frozen=True)
class ArchitectureTool:
    spec: ToolSpec
    build: Callable[[StrictModel], ApplyRequest]


def _tool[T: StrictModel](
    name: str, request: type[T], build: Callable[[T], ApplyRequest]
) -> ArchitectureTool:
    def invoke(value: StrictModel) -> ApplyRequest:
        if not isinstance(value, request):
            raise TypeError(f"Wrong request model for {name}")
        return build(value)

    return ArchitectureTool(ToolSpec(name, request, ApplyResult), invoke)


TOOL_CATALOG = {
    tool.spec.name: tool
    for tool in (
        _tool("define_system", DefineSystemRequest, _system),
        _tool("define_concept", DefineConceptRequest, _concept),
        _tool("add_layer", AddLayerRequest, _layer),
        _tool("define_boundary", DefineBoundaryRequest, _boundary),
        _tool("propose_binding", ProposeBindingRequest, _binding),
    )
}


class ArchitectureTools:
    def catalog(self, schema: GraphSchema) -> dict[str, ToolSpec]:
        return (
            {name: tool.spec for name, tool in TOOL_CATALOG.items()}
            if schema.version == PACKAGE_VERSION
            else {}
        )

    def build(self, name: str, request: StrictModel) -> ApplyRequest:
        return TOOL_CATALOG[name].build(request)
