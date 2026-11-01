"""One typed identity/parser/renderer for all graph resource URIs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self
from urllib.parse import quote, unquote

from pydantic import model_validator

from typed_graph.domain.models import Identifier, Revision, StrictModel


class ResourceKind(StrEnum):
    SCHEMA = "schema"
    NODE = "nodes"
    REVISION = "revisions"
    IMPACT = "impact"
    ASSESSMENTS = "assessments"


@dataclass(frozen=True)
class ResourceSpec:
    kind: ResourceKind
    resolver_name: str
    identity: Literal["node_id", "revision"] | None

    @property
    def parameter(self) -> str | None:
        return "id" if self.identity == "node_id" else self.identity


RESOURCE_CATALOG = {
    spec.kind: spec
    for spec in (
        ResourceSpec(ResourceKind.SCHEMA, "resolve_schema_resource", None),
        ResourceSpec(ResourceKind.NODE, "resolve_node_resource", "node_id"),
        ResourceSpec(ResourceKind.REVISION, "resolve_revision_resource", "revision"),
        ResourceSpec(ResourceKind.IMPACT, "resolve_impact_resource", "revision"),
        ResourceSpec(ResourceKind.ASSESSMENTS, "resolve_assessments_resource", "revision"),
    )
}


class ResourceURI(StrictModel):
    kind: ResourceKind
    node_id: Identifier | None = None
    revision: Revision | None = None

    @property
    def spec(self) -> ResourceSpec:
        return RESOURCE_CATALOG[self.kind]

    @model_validator(mode="after")
    def matching_identity(self) -> Self:
        present = {key for key in ("node_id", "revision") if getattr(self, key) is not None}
        expected = {self.spec.identity} if self.spec.identity is not None else set()
        if present != expected:
            raise ValueError("Resource kind and identity do not match")
        return self

    @classmethod
    def parse(cls, uri: str) -> ResourceURI:
        prefix = "graph://model/"
        if not uri.startswith(prefix):
            raise ValueError("Unknown graph resource")
        kind, separator, identity = uri[len(prefix) :].partition("/")
        try:
            resource_kind = ResourceKind(kind)
        except ValueError as error:
            raise ValueError("Unknown graph resource kind") from error
        spec = RESOURCE_CATALOG[resource_kind]
        if spec.identity is None:
            if separator:
                raise ValueError("Resource has no identity")
            return cls(kind=resource_kind)
        if not separator or not identity or "/" in identity:
            raise ValueError("Resource requires one encoded identity component")
        if spec.identity == "node_id":
            # Strict decoding rejects invalid UTF-8 rather than aliasing identifiers.
            return cls(kind=resource_kind, node_id=unquote(identity, errors="strict"))
        if not identity.isascii() or not identity.isdecimal():
            raise ValueError("Revision must be a nonnegative integer")
        return cls(kind=resource_kind, revision=int(identity))

    def __str__(self) -> str:
        prefix = f"graph://model/{self.kind.value}"
        if self.spec.identity is None:
            return prefix
        value = getattr(self, self.spec.identity)
        return f"{prefix}/{quote(str(value), safe='')}"

    @classmethod
    def schema_resource(cls) -> ResourceURI:
        return cls(kind=ResourceKind.SCHEMA)

    @classmethod
    def node(cls, node_id: Identifier) -> ResourceURI:
        return cls(kind=ResourceKind.NODE, node_id=node_id)

    @classmethod
    def revision_resource(cls, kind: ResourceKind, revision: Revision) -> ResourceURI:
        return cls(kind=kind, revision=revision)

    @classmethod
    def templates(cls) -> list[tuple[ResourceKind, str]]:
        return [
            (spec.kind, f"graph://model/{spec.kind.value}/{{{spec.parameter}}}")
            for spec in RESOURCE_CATALOG.values()
            if spec.parameter is not None
        ]
