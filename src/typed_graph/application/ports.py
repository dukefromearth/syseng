"""Typed IO contracts: application code knows no filesystem, SQLite or MCP."""

from typing import Protocol

from typed_graph.application.contracts import ApplyRequest, SearchResult, ToolSpec
from typed_graph.application.specification import SpecificationState
from typed_graph.domain.models import (
    Assessment,
    GraphSchema,
    Identifier,
    JsonObject,
    Revision,
    Snapshot,
    StrictModel,
)


class Repository(Protocol):
    def current(self) -> Snapshot: ...
    def read_revision(self, revision: Revision) -> Snapshot: ...
    def import_document(self) -> Snapshot: ...
    def accept_import(self, document: Snapshot, expected_revision: Revision) -> None: ...
    def commit(self, document: Snapshot, expected_revision: Revision) -> Snapshot: ...
    def search_nodes(
        self, node_type: Identifier | None, where: JsonObject, text: str, limit: int
    ) -> SearchResult: ...
    def assessments(self, revision: Revision) -> list[Assessment]: ...
    def record_assessment(self, assessment: Assessment) -> None: ...


class PublicationValidator(Protocol):
    def __call__(self, document: Snapshot, /) -> None: ...


class ToolExtension(Protocol):
    """Optional semantic module: declarations and pure atomic operation builders."""

    def catalog(self, schema: GraphSchema) -> dict[str, ToolSpec]: ...
    def build(self, name: str, request: StrictModel) -> ApplyRequest: ...


type SpecificationToken = str


class SpecificationSource(Protocol):
    def specification_token(self) -> SpecificationToken: ...
    def specification_state(self) -> SpecificationState: ...
