"""Canonical strict wire/domain vocabulary; authored property schemas remain open data."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, JsonValue


def _reject_explicit_null(value: Any) -> Any:
    if value is None:
        raise ValueError("Omit this field instead of supplying null")
    return value


def _omit_null_schema(schema: dict[str, Any]) -> None:
    """An omission-only field has a nullable Python default, not a nullable wire type."""
    if schema.get("default") is None:
        schema.pop("default", None)
    choices = schema.get("anyOf")
    if isinstance(choices, list):
        choices = [choice for choice in choices if choice != {"type": "null"}]
        if len(choices) == 1:
            schema.pop("anyOf")
            schema.update(choices[0])
        else:
            schema["anyOf"] = choices


T = TypeVar("T")
Omittable = Annotated[
    T | None, BeforeValidator(_reject_explicit_null), Field(json_schema_extra=_omit_null_schema)
]


type Identifier = Annotated[str, Field(min_length=1)]
type Revision = Annotated[int, Field(ge=0)]
type JsonObject = dict[str, JsonValue]
type Schema = JsonObject
type JsonSchema = JsonObject | bool


class AssessmentStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class AssessmentState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class ImpactDirection(StrEnum):
    TARGET_TO_SOURCE = "target_to_source"
    SOURCE_TO_TARGET = "source_to_target"
    BOTH = "both"
    NONE = "none"


def _strict_enum[E: StrEnum](enum_type: type[E]) -> Callable[[Any], E]:
    def parse(value: Any) -> E:
        if isinstance(value, enum_type):
            return value
        if type(value) is str:
            return enum_type(value)
        raise ValueError(f"Expected an exact {enum_type.__name__} string")

    return parse


type AssessmentKey = tuple[Revision, Identifier, Identifier]


def assessment_key(
    revision: Revision, interceptor_id: Identifier, target_id: Identifier
) -> AssessmentKey:
    return revision, interceptor_id, target_id


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class Node(StrictModel):
    id: Identifier
    type: Identifier
    properties: JsonObject


class Edge(StrictModel):
    id: Identifier
    type: Identifier
    source: Identifier
    target: Identifier
    properties: JsonObject = Field(default_factory=dict)


class CreateNode(StrictModel):
    op: Literal["create_node"]
    node: Node


class UpdateNode(Node):
    op: Literal["update_node"]


class DeleteNode(StrictModel):
    op: Literal["delete_node"]
    id: Identifier


class CreateEdge(StrictModel):
    op: Literal["create_edge"]
    edge: Edge


class UpdateEdge(Edge):
    op: Literal["update_edge"]


class DeleteEdge(StrictModel):
    op: Literal["delete_edge"]
    id: Identifier


type Change = Annotated[
    CreateNode | UpdateNode | DeleteNode | CreateEdge | UpdateEdge | DeleteEdge,
    Field(discriminator="op"),
]


class ImportChange(StrictModel):
    op: Literal["import"]


type HistoryChange = Annotated[Change | ImportChange, Field(discriminator="op")]


class Impact(StrictModel):
    node_id: Identifier
    paths: list[list[Identifier]]
    triggering_revision: Revision
    component_id: Identifier
    component: Annotated[list[Identifier], Field(min_length=1)]


class ApplyChangesRequest(StrictModel):
    expected_revision: Revision
    changes: list[Change]


class ApplyResult(StrictModel):
    revision: Revision
    applied_changes: list[HistoryChange]
    invalidations: list[Impact]


class Evidence(StrictModel):
    obligation: Identifier
    uri: Identifier


class AssessmentResult(StrictModel):
    status: Annotated[AssessmentStatus, BeforeValidator(_strict_enum(AssessmentStatus))]
    findings: list[JsonObject]
    evidence: list[Evidence]


class ImpactContext(StrictModel):
    target: Node
    impact: Impact
    triggering_revision: Revision
    changes: list[HistoryChange]
    handler_version: Identifier
    invocation_id: Identifier


class Assessment(StrictModel):
    revision: Revision
    interceptor_id: Identifier
    target_id: Identifier
    handler_version: Identifier
    target_fingerprint: Identifier
    state: Annotated[AssessmentState, BeforeValidator(_strict_enum(AssessmentState))]
    result: AssessmentResult
    context: ImpactContext
    framework_failure: Omittable[bool] = None

    @property
    def key(self) -> AssessmentKey:
        return assessment_key(self.revision, self.interceptor_id, self.target_id)


class AssessmentView(Assessment):
    stale: bool


class Cardinality(StrictModel):
    out_min: Omittable[Annotated[int, Field(ge=0)]] = None
    out_max: Omittable[Annotated[int, Field(ge=0)]] = None
    in_min: Omittable[Annotated[int, Field(ge=0)]] = None
    in_max: Omittable[Annotated[int, Field(ge=0)]] = None


EMPTY_PROPERTIES_SCHEMA: JsonObject = {"type": "object", "additionalProperties": False}


class RelationDefinition(StrictModel):
    source: Annotated[list[Identifier], Field(min_length=1)]
    target: Annotated[list[Identifier], Field(min_length=1)]
    impact: Annotated[ImpactDirection, BeforeValidator(_strict_enum(ImpactDirection))]
    cardinality: Omittable[Cardinality] = None
    properties: Omittable[JsonSchema] = None

    @property
    def property_schema(self) -> JsonSchema:
        return self.properties if self.properties is not None else dict(EMPTY_PROPERTIES_SCHEMA)


class UniqueInvariant(StrictModel):
    kind: Literal["unique"]
    node_type: Identifier
    property: str


class RequiresEdgeInvariant(StrictModel):
    kind: Literal["requires_edge"]
    node_type: Identifier
    relation: Identifier
    direction: Literal["out", "in"] = "out"
    min: Annotated[int, Field(ge=0)] = 1


type Invariant = Annotated[UniqueInvariant | RequiresEdgeInvariant, Field(discriminator="kind")]


class Interceptor(StrictModel):
    id: Identifier
    target_type: Identifier
    handler: Identifier
    version: Identifier
    trigger: Literal["dependency_changed"]
    result_schema: Omittable[JsonSchema] = None
    evidence_required: list[Identifier] = Field(default_factory=list)


class GraphSchema(StrictModel):
    version: Identifier
    node_types: dict[Identifier, JsonSchema]
    relations: dict[Identifier, RelationDefinition]
    invariants: list[Invariant] = Field(default_factory=list)
    interceptors: list[Interceptor] = Field(default_factory=list)


class ModelDocument(StrictModel):
    schema_definition: GraphSchema = Field(alias="schema")
    nodes: list[Node]
    edges: list[Edge]


class Snapshot(ModelDocument):
    revision: Revision
    impact: list[Impact]
    changes: list[HistoryChange]
    source_baseline: ModelDocument | None = None
    source_fingerprints: dict[str, str] | None = None


def dump_wire(model: BaseModel) -> JsonObject:
    """Canonical JSON-compatible wire keys, preserving omitted optional fields."""
    return cast(JsonObject, model.model_dump(mode="json", by_alias=True, exclude_unset=True))
