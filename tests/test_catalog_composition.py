"""Composition rejects catalog/use-case drift before serving a real workspace."""

from pathlib import Path

import pytest

from typed_graph.adapters.workspace import WorkspaceRepository
from typed_graph.application.contracts import EmptyRequest, SearchResult
from typed_graph.application.service import GraphService


def test_mismatched_handler_contract_cannot_start(tmp_path: Path) -> None:
    class InvalidService(GraphService):
        def query_graph(self, args: EmptyRequest) -> SearchResult:  # type: ignore[override]
            return SearchResult(revision=0, nodes=[])

    repository = WorkspaceRepository(tmp_path)
    with pytest.raises(TypeError, match="query_graph"):
        InvalidService(repository)
    assert repository.current().revision == 0
