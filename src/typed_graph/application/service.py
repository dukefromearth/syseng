"""Typed graph use cases. Wire codecs live at the public dispatch boundary."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import deque
from collections.abc import Callable
from typing import cast, get_type_hints

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry

from typed_graph.application.contracts import (
    TOOL_CATALOG,
    ApplyRequest,
    AssessmentsRequest,
    AssessmentsResult,
    AssessmentSubmissionResult,
    CompareRequest,
    CompareResult,
    DetectResult,
    Diff,
    EmptyRequest,
    GraphSchemaResult,
    ImpactResourceResult,
    NodeResourceResult,
    QueryRequest,
    SearchRequest,
    SearchResult,
    SubmitAssessmentRequest,
    TraceRequest,
    TraceResult,
    tool_spec,
    validate_request,
    validate_response,
)
from typed_graph.application.ports import Repository
from typed_graph.domain.engine import (
    apply_typed_operations,
    changed_node_ids,
    compute_typed_impact,
    dependency_adjacency,
    validate_typed_graph,
)
from typed_graph.domain.models import (
    ApplyResult,
    Assessment,
    AssessmentResult,
    AssessmentState,
    AssessmentStatus,
    AssessmentView,
    Edge,
    HistoryChange,
    Identifier,
    ImpactContext,
    ImportChange,
    JsonObject,
    Node,
    Revision,
    Snapshot,
    StrictModel,
    assessment_key,
    dump_wire,
)
from typed_graph.domain.resources import ResourceURI
from typed_graph.domain.schema import validate_typed_schema


def fingerprint(value: StrictModel | list[str | int]) -> str:
    data = dump_wire(value) if isinstance(value, StrictModel) else value
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def changed_entities(old: Snapshot, new: Snapshot) -> list[Identifier]:
    return changed_node_ids(old.nodes, old.edges, new.nodes, new.edges)


def entity_diff[T: Node | Edge](old: list[T], new: list[T]) -> Diff:
    before, after = ({item.id: item for item in items} for items in (old, new))
    return Diff(
        added=sorted(after.keys() - before.keys()),
        removed=sorted(before.keys() - after.keys()),
        updated=sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
    )


class GraphService:
    def __init__(self, store: Repository):
        self.store = store
        # Fail at composition time if an extension's declared contract and use case drift.
        for spec in TOOL_CATALOG.values():
            handler = getattr(self, spec.handler_name, None)
            if not callable(handler):
                raise TypeError(f"Missing tool handler: {spec.name}")
            parameters = list(inspect.signature(handler).parameters.values())
            hints = get_type_hints(handler)
            if (
                len(parameters) != 1
                or hints.get(parameters[0].name) is not spec.request_model
                or hints.get("return") is not spec.result_model
            ):
                raise TypeError(f"Tool contract/handler signature mismatch: {spec.name}")

    @property
    def schema(self) -> JsonObject:
        return dump_wire(self.store.current().schema_definition)

    @property
    def revision(self) -> Revision:
        return self.store.current().revision

    def dispatch(self, tool: str, args: JsonObject) -> JsonObject:
        spec = tool_spec(tool)
        request = validate_request(tool, args, self.schema)
        handler = cast(Callable[[StrictModel], StrictModel], getattr(self, spec.handler_name))
        return dump_wire(validate_response(tool, handler(request)))

    def get_graph_schema(self, args: EmptyRequest) -> GraphSchemaResult:
        document = self.store.current()
        return GraphSchemaResult(revision=document.revision, schema=document.schema_definition)

    def _validate(self, document: Snapshot) -> None:
        validate_typed_schema(document.schema_definition)
        validate_typed_graph(document.schema_definition, document.nodes, document.edges)

    def _commit(
        self, old: Snapshot, new: Snapshot, changes: list[HistoryChange], changed: list[Identifier]
    ) -> ApplyResult:
        self._validate(new)
        revision = old.revision + 1
        impact = compute_typed_impact(
            old.schema_definition,
            new.schema_definition,
            old.nodes,
            old.edges,
            new.nodes,
            new.edges,
            changed,
            revision,
        )
        committed = self.store.commit(
            new.model_copy(update={"impact": impact, "changes": changes}), old.revision
        )
        self._schedule(committed)
        return ApplyResult(revision=revision, applied_changes=changes, invalidations=impact)

    def index_model(self, args: EmptyRequest) -> ApplyResult:
        old, new = self.store.current(), self.store.import_document()
        self._validate(new)
        changed = changed_entities(old, new)
        if not changed and old.schema_definition == new.schema_definition:
            self.store.accept_import(new, old.revision)
            return ApplyResult(revision=old.revision, applied_changes=[], invalidations=[])
        if old.schema_definition != new.schema_definition:
            changed = sorted({node.id for node in old.nodes + new.nodes})
        return self._commit(old, new, [ImportChange(op="import")], changed)

    def apply_changes(self, args: ApplyRequest) -> ApplyResult:
        old = self.store.current()
        if args.expected_revision != old.revision:
            raise ValueError("revision conflict")
        nodes, edges, changed = apply_typed_operations(
            old.schema_definition, old.nodes, old.edges, args.changes
        )
        if not changed:
            return ApplyResult(revision=old.revision, applied_changes=[], invalidations=[])
        new = old.model_copy(update={"nodes": nodes, "edges": edges}, deep=True)
        return self._commit(old, new, list(args.changes), changed)

    def detect_changes(self, args: EmptyRequest) -> DetectResult:
        old, new = self.store.current(), self.store.import_document()
        self._validate(new)
        changed = changed_entities(old, new)
        if old.schema_definition != new.schema_definition:
            changed = sorted({node.id for node in old.nodes + new.nodes})
        impact = compute_typed_impact(
            old.schema_definition,
            new.schema_definition,
            old.nodes,
            old.edges,
            new.nodes,
            new.edges,
            changed,
            old.revision + 1,
        )
        return DetectResult(
            revision=old.revision,
            changed_nodes=changed,
            schema_changed=old.schema_definition != new.schema_definition,
            preview_revision=old.revision + 1,
            impact=impact,
        )

    def query_graph(self, args: QueryRequest) -> SearchResult:
        return self.store.search_nodes(args.type, args.where, "", args.limit)

    def search_graph(self, args: SearchRequest) -> SearchResult:
        return self.store.search_nodes(args.type, {}, args.text, args.limit)

    def trace_path(self, args: TraceRequest) -> TraceResult:
        document = self.store.current()
        ids = {node.id for node in document.nodes}
        if args.source not in ids or args.target not in ids:
            raise ValueError("unknown endpoint")
        if args.relation is not None and args.relation not in document.schema_definition.relations:
            raise ValueError("unknown relation")
        adjacency: dict[Identifier, set[Identifier]]
        if args.mode == "dependency":
            adjacency = dependency_adjacency(
                document.schema_definition, document.edges, args.relation
            )
        else:
            adjacency = {}
            for edge in document.edges:
                if args.relation is None or edge.type == args.relation:
                    adjacency.setdefault(edge.source, set()).add(edge.target)
        queue = deque([[args.source]])
        seen = {args.source}
        while queue:
            path = queue.popleft()
            if path[-1] == args.target:
                return TraceResult(revision=document.revision, path=path)
            if len(path) > args.max_depth:
                continue
            for target in sorted(adjacency.get(path[-1], set())):
                if target not in seen:
                    seen.add(target)
                    queue.append([*path, target])
        return TraceResult(revision=document.revision, path=[])

    def compare_graphs(self, args: CompareRequest) -> CompareResult:
        old, new = (
            self.store.read_revision(revision)
            for revision in (args.from_revision, args.to_revision)
        )
        return CompareResult(
            from_revision=old.revision,
            to_revision=new.revision,
            schema_changed=old.schema_definition != new.schema_definition,
            nodes=entity_diff(old.nodes, new.nodes),
            edges=entity_diff(old.edges, new.edges),
        )

    def _schedule(self, document: Snapshot) -> None:
        nodes = {node.id: node for node in document.nodes}
        recorded = {assessment.key for assessment in self.store.assessments(document.revision)}
        for impact in document.impact:
            node = nodes.get(impact.node_id)
            if node is None:
                continue
            for interceptor in document.schema_definition.interceptors:
                key = assessment_key(document.revision, interceptor.id, node.id)
                if interceptor.target_type != node.type or key in recorded:
                    continue
                assessment = Assessment(
                    revision=document.revision,
                    interceptor_id=interceptor.id,
                    target_id=node.id,
                    handler_version=interceptor.version,
                    target_fingerprint=fingerprint(node),
                    state=AssessmentState.PENDING,
                    result=AssessmentResult(
                        status=AssessmentStatus.INDETERMINATE, findings=[], evidence=[]
                    ),
                    context=ImpactContext(
                        target=node,
                        impact=impact,
                        triggering_revision=document.revision,
                        changes=document.changes,
                        handler_version=interceptor.version,
                        invocation_id=fingerprint(list(key)),
                    ),
                )
                self.store.record_assessment(assessment)
                recorded.add(assessment.key)

    def submit_assessment(self, args: SubmitAssessmentRequest) -> AssessmentSubmissionResult:
        document = self.store.read_revision(args.revision)
        self._schedule(document)
        assessment = self._assessment(args.revision, args.interceptor_id, args.target_id)
        interceptor = next(
            item
            for item in document.schema_definition.interceptors
            if item.id == args.interceptor_id
        )
        if interceptor.result_schema is not None:
            try:
                Draft202012Validator(interceptor.result_schema, registry=Registry()).validate(
                    dump_wire(args.result)
                )
            except ValidationError as error:
                raise ValueError(error.message) from error
        supplied = {entry.obligation for entry in args.result.evidence}
        required = set(interceptor.evidence_required)
        if args.result.status == AssessmentStatus.PASS and (
            not required or not required <= supplied
        ):
            raise ValueError("pass requires declared evidence obligations and matching evidence")
        assessment = assessment.model_copy(
            update={"state": AssessmentState.COMPLETED, "result": args.result}
        )
        self.store.record_assessment(assessment)
        return AssessmentSubmissionResult(assessment=self._freshness(assessment))

    def _assessment(
        self, revision: Revision, interceptor_id: Identifier, target_id: Identifier
    ) -> Assessment:
        for assessment in self.store.assessments(revision):
            if assessment.interceptor_id == interceptor_id and assessment.target_id == target_id:
                return assessment
        raise ValueError("assessment was not scheduled for this revision/target/interceptor")

    def record_handler_failure(
        self, revision: Revision, interceptor_id: Identifier, target_id: Identifier, error: str
    ) -> AssessmentSubmissionResult:
        assessment = self._assessment(revision, interceptor_id, target_id).model_copy(
            update={
                "state": AssessmentState.COMPLETED,
                "result": AssessmentResult(
                    status=AssessmentStatus.INDETERMINATE, findings=[{"error": error}], evidence=[]
                ),
                "framework_failure": True,
            }
        )
        self.store.record_assessment(assessment)
        return AssessmentSubmissionResult(assessment=self._freshness(assessment))

    def _freshness(self, assessment: Assessment) -> AssessmentView:
        return AssessmentView.model_validate(
            {**dump_wire(assessment), "stale": assessment.revision != self.revision}
        )

    def get_assessments(self, args: AssessmentsRequest) -> AssessmentsResult:
        revision = self.revision if args.revision is None else args.revision
        document = self.store.read_revision(revision)
        self._schedule(document)
        return AssessmentsResult(
            revision=revision,
            assessments=[
                self._freshness(assessment) for assessment in self.store.assessments(revision)
            ],
        )

    def resource(self, uri: str) -> JsonObject:
        identity = ResourceURI.parse(uri)
        resolver = cast(
            Callable[[ResourceURI], StrictModel], getattr(self, identity.spec.resolver_name)
        )
        return dump_wire(resolver(identity))

    def resolve_schema_resource(self, identity: ResourceURI) -> GraphSchemaResult:
        return self.get_graph_schema(EmptyRequest())

    def resolve_node_resource(self, identity: ResourceURI) -> NodeResourceResult:
        document = self.store.current()
        node = next((item for item in document.nodes if item.id == identity.node_id), None)
        if node is None:
            raise ValueError("unknown node")
        return NodeResourceResult(revision=document.revision, node=node)

    def resolve_revision_resource(self, identity: ResourceURI) -> Snapshot:
        assert identity.revision is not None
        return self.store.read_revision(identity.revision)

    def resolve_impact_resource(self, identity: ResourceURI) -> ImpactResourceResult:
        document = self.resolve_revision_resource(identity)
        return ImpactResourceResult(revision=document.revision, impact=document.impact)

    def resolve_assessments_resource(self, identity: ResourceURI) -> AssessmentsResult:
        assert identity.revision is not None
        return self.get_assessments(AssessmentsRequest(revision=identity.revision))
