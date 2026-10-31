"""Canonical strict tool contracts and the single public tool registration catalog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import Field
from referencing import Registry

from typed_graph.domain.models import (
    ApplyChangesRequest,
    ApplyResult,
    AssessmentResult,
    AssessmentView,
    GraphSchema,
    Identifier,
    Impact,
    JsonObject,
    Node,
    Omittable,
    Revision,
    StrictModel,
)


class EmptyRequest(StrictModel):
    pass


Limit = Annotated[int, Field(strict=True, ge=1, le=1000)]
Depth = Annotated[int, Field(strict=True, ge=0, le=100)]


class SearchRequest(StrictModel):
    text: str = ""
    type: Omittable[Identifier] = None
    limit: Limit = 100


class QueryRequest(StrictModel):
    type: Omittable[Identifier] = None
    where: JsonObject = Field(default_factory=dict)
    limit: Limit = 100


class TraceRequest(StrictModel):
    source: Identifier
    target: Identifier
    relation: Omittable[Identifier] = None
    mode: Literal["semantic", "dependency"] = "semantic"
    max_depth: Depth = 20


ApplyRequest = ApplyChangesRequest


class AssessmentsRequest(StrictModel):
    revision: Omittable[Revision] = None


class CompareRequest(StrictModel):
    from_revision: Revision
    to_revision: Revision


class SubmitAssessmentRequest(StrictModel):
    revision: Revision
    interceptor_id: Identifier
    target_id: Identifier
    result: AssessmentResult


class GraphSchemaResult(StrictModel):
    revision: Revision
    schema_definition: GraphSchema = Field(alias="schema")


class SearchResult(StrictModel):
    revision: Revision
    nodes: list[Node]


class TraceResult(StrictModel):
    revision: Revision
    path: list[Identifier]


class DetectResult(StrictModel):
    revision: Revision
    changed_nodes: list[Identifier]
    schema_changed: bool
    preview_revision: Revision
    impact: list[Impact]


class AssessmentsResult(StrictModel):
    revision: Revision
    assessments: list[AssessmentView]


class AssessmentSubmissionResult(StrictModel):
    assessment: AssessmentView


class Diff(StrictModel):
    added: list[Identifier]
    removed: list[Identifier]
    updated: list[Identifier]


class CompareResult(StrictModel):
    from_revision: Revision
    to_revision: Revision
    schema_changed: bool
    nodes: Diff
    edges: Diff


@dataclass(frozen=True)
class ToolSpec:
    name: str
    request_model: type[StrictModel]
    result_model: type[StrictModel]
    specialize_input: Callable[[JsonObject, JsonObject], JsonObject] | None = None

    @property
    def handler_name(self) -> str:
        return self.name


def _apply_schema(base: JsonObject, authored: JsonObject) -> JsonObject:
    from typed_graph.domain.schema import apply_input_schema

    return apply_input_schema(authored)


def _trace_schema(base: JsonObject, authored: JsonObject) -> JsonObject:
    registered = sorted(GraphSchema.model_validate(authored).relations)
    properties = base["properties"]
    assert isinstance(properties, dict)
    properties["relation"] = {"enum": [name for name in registered]} if registered else False
    return base


TOOL_CATALOG: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> ToolSpec:
    if spec.name in TOOL_CATALOG:
        raise ValueError(f"Duplicate tool registration: {spec.name}")
    TOOL_CATALOG[spec.name] = spec
    return spec


INDEX_MODEL = _register(ToolSpec("index_model", EmptyRequest, ApplyResult))
GET_GRAPH_SCHEMA = _register(ToolSpec("get_graph_schema", EmptyRequest, GraphSchemaResult))
SEARCH_GRAPH = _register(ToolSpec("search_graph", SearchRequest, SearchResult))
QUERY_GRAPH = _register(ToolSpec("query_graph", QueryRequest, SearchResult))
TRACE_PATH = _register(
    ToolSpec("trace_path", TraceRequest, TraceResult, specialize_input=_trace_schema)
)
APPLY_CHANGES = _register(
    ToolSpec("apply_changes", ApplyRequest, ApplyResult, specialize_input=_apply_schema)
)
DETECT_CHANGES = _register(ToolSpec("detect_changes", EmptyRequest, DetectResult))
GET_ASSESSMENTS = _register(ToolSpec("get_assessments", AssessmentsRequest, AssessmentsResult))
COMPARE_GRAPHS = _register(ToolSpec("compare_graphs", CompareRequest, CompareResult))
SUBMIT_ASSESSMENT = _register(
    ToolSpec("submit_assessment", SubmitAssessmentRequest, AssessmentSubmissionResult)
)


def tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_CATALOG[name]
    except KeyError as error:
        raise ValueError(f"unknown tool {name}") from error


def validate_request(name: str, arguments: JsonObject, authored: JsonObject) -> StrictModel:
    request = tool_spec(name).request_model.model_validate(arguments, strict=True)
    try:
        Draft202012Validator(request_schema(name, authored), registry=Registry()).validate(
            arguments
        )
    except ValidationError as error:
        raise ValueError(error.message) from error
    return request


def validate_response(name: str, result: JsonObject | StrictModel) -> StrictModel:
    # Roundtrip instances too: mutation/model_construct must not bypass boundary validation.
    payload = (
        result.model_dump(mode="python", by_alias=True, exclude_unset=True)
        if isinstance(result, StrictModel)
        else result
    )
    return tool_spec(name).result_model.model_validate(payload, strict=True)


def request_schema(name: str, authored: JsonObject) -> JsonObject:
    spec = tool_spec(name)
    base = spec.request_model.model_json_schema(by_alias=True)
    return spec.specialize_input(base, authored) if spec.specialize_input else base


def response_schema(name: str) -> JsonObject:
    return tool_spec(name).result_model.model_json_schema(by_alias=True)


class NodeResourceResult(StrictModel):
    revision: Revision
    node: Node


class ImpactResourceResult(StrictModel):
    revision: Revision
    impact: list[Impact]
