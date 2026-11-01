"""Generate the optional architecture schema from one canonical role/relation catalog."""

from dataclasses import dataclass, replace
from typing import cast

from typed_graph.architecture.models import PACKAGE_VERSION, ROLE_CATALOG, Relation, Role
from typed_graph.domain.models import (
    Cardinality,
    GraphSchema,
    ImpactDirection,
    Interceptor,
    Invariant,
    JsonObject,
    RelationDefinition,
    RequiresEdgeInvariant,
    UniqueInvariant,
)


@dataclass(frozen=True)
class RelationSpec:
    source: tuple[Role, ...]
    target: tuple[Role, ...]
    impact: ImpactDirection = ImpactDirection.TARGET_TO_SOURCE
    cardinality: Cardinality | None = None
    meaning: str = ""

    def definition(self) -> RelationDefinition:
        definition = RelationDefinition(
            source=[str(role) for role in self.source],
            target=[str(role) for role in self.target],
            impact=self.impact,
        )
        return (
            definition.model_copy(update={"cardinality": self.cardinality})
            if self.cardinality is not None
            else definition
        )


R = Role
D = ImpactDirection
RELATION_CATALOG: dict[Relation, RelationSpec] = {
    Relation.EXCHANGES: RelationSpec((R.CONTRACT,), (R.EXCHANGE,)),
    Relation.CONSTRAINS_CONTRACT: RelationSpec(
        (R.REQUIREMENT, R.CRITERION, R.FAILURE, R.OBJECTIVE), (R.CONTRACT,), D.SOURCE_TO_TARGET
    ),
    Relation.OWNS: RelationSpec(
        (R.SYSTEM,),
        (R.RESPONSIBILITY,),
        cardinality=Cardinality(out_min=1, out_max=1, in_min=1, in_max=1),
    ),
    Relation.SPECIFIED_BY: RelationSpec(
        (R.RESPONSIBILITY,), (R.CONTRACT,), cardinality=Cardinality(out_min=1, out_max=1)
    ),
    Relation.CONCERNS: RelationSpec((R.RESPONSIBILITY, R.OBJECTIVE), (R.CONCEPT,)),
    Relation.DEFINED_IN_TERMS_OF: RelationSpec(
        (R.CONTRACT, R.EXCHANGE), (R.CONCEPT, R.REALIZATION_CONCEPT)
    ),
    Relation.PRODUCES: RelationSpec((R.SYSTEM, R.BINDING), (R.EXCHANGE,)),
    Relation.CONSUMED_BY: RelationSpec((R.EXCHANGE,), (R.SYSTEM,), D.SOURCE_TO_TARGET),
    Relation.CONSTRAINS: RelationSpec((R.ONTOLOGY,), (R.ONTOLOGY,), D.SOURCE_TO_TARGET),
    Relation.CONSTRAINS_CONCEPT: RelationSpec((R.INVARIANT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.INCLUDES: RelationSpec(
        (R.ONTOLOGY,),
        (
            R.CONCEPT,
            R.INVARIANT,
            R.SYSTEM,
            R.REALIZATION_CONCEPT,
            R.ENVIRONMENT,
            R.BOUNDARY,
            R.CAPABILITY,
            R.LAYER,
            R.BINDING,
            R.TECHNOLOGY,
        ),
        D.NONE,
    ),
    Relation.USES_CONCEPT: RelationSpec(
        (R.SYSTEM,), (R.CONCEPT, R.LOCAL_CONCEPT, R.REALIZATION_CONCEPT)
    ),
    Relation.SPECIALIZES: RelationSpec(
        (R.LOCAL_CONCEPT, R.CONCEPT), (R.CONCEPT, R.REALIZATION_CONCEPT)
    ),
    Relation.EXPRESSED_AS: RelationSpec((R.CONCEPT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.CONSUMES: RelationSpec((R.CONCEPT,), (R.CONCEPT,)),
    Relation.YIELDS: RelationSpec((R.CONCEPT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.INFORMS: RelationSpec((R.CONCEPT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.SELECTS: RelationSpec((R.CONCEPT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.MODIFIES: RelationSpec((R.CONCEPT,), (R.CONCEPT,), D.SOURCE_TO_TARGET),
    Relation.ATTEMPTS_TO_FULFILL: RelationSpec(
        (R.BINDING,), (R.CONTRACT,), cardinality=Cardinality(out_min=1, out_max=1)
    ),
    Relation.USES_BOUNDARY: RelationSpec((R.BINDING,), (R.BOUNDARY,)),
    Relation.REQUIRES_CAPABILITY: RelationSpec((R.BINDING, R.CONTRACT), (R.CAPABILITY,)),
    Relation.MUST_PRESERVE: RelationSpec((R.BINDING, R.CONTRACT), (R.INVARIANT,)),
    Relation.CANDIDATE_FOR: RelationSpec(
        (R.TECHNOLOGY,), (R.BINDING, R.BOUNDARY), D.SOURCE_TO_TARGET
    ),
    Relation.EXPOSES: RelationSpec((R.ENVIRONMENT,), (R.BOUNDARY,), D.SOURCE_TO_TARGET),
    Relation.PROVIDES: RelationSpec((R.BOUNDARY,), (R.CAPABILITY,)),
    Relation.CLASSIFIED_BY: RelationSpec((R.BOUNDARY,), (R.LAYER,)),
    Relation.APPLIES_TO: RelationSpec(
        (R.REQUIREMENT, R.CRITERION, R.FAILURE, R.OBJECTIVE),
        (R.SYSTEM, R.GOVERNANCE_ROLE, R.SCENARIO, R.BINDING, R.OBJECTIVE),
        D.SOURCE_TO_TARGET,
    ),
    Relation.GOVERNED_BY: RelationSpec((R.REQUIREMENT, R.CRITERION), (R.INVARIANT,)),
    Relation.CONTAINS_STEP: RelationSpec((R.SCENARIO,), (R.STEP,), D.NONE),
    Relation.PERFORMED_BY: RelationSpec((R.STEP,), (R.SYSTEM,)),
    Relation.NEXT: RelationSpec((R.STEP, R.PHASE), (R.STEP, R.PHASE), D.NONE),
    Relation.DELIVERS: RelationSpec((R.PHASE,), (R.REQUIREMENT,)),
    Relation.EVALUATES: RelationSpec((R.PHASE,), (R.CRITERION,)),
    Relation.SUPPORTS: RelationSpec((R.REQUIREMENT,), (R.REQUIREMENT,)),
    Relation.DEMONSTRATES_OBJECTIVE: RelationSpec(
        (R.INDEPENDENCE,), (R.OBJECTIVE,), cardinality=Cardinality(out_min=1, out_max=1)
    ),
    Relation.HOLDS_CONTRACT: RelationSpec(
        (R.INDEPENDENCE,), (R.CONTRACT,), cardinality=Cardinality(out_min=1, out_max=1)
    ),
    Relation.COMPARES_BINDING: RelationSpec(
        (R.INDEPENDENCE,), (R.BINDING,), cardinality=Cardinality(out_min=2)
    ),
}

# Human meaning is compiler metadata owned beside the relation contract, never
# independently authored layout prose or a second graph fact.
for _relation, _meaning in {
    Relation.OWNS: "A system owns an independently understandable responsibility.",
    Relation.SPECIFIED_BY: "A responsibility is specified by a behavioral contract.",
    Relation.CONCERNS: "A responsibility or objective concerns canonical domain meaning.",
    Relation.CONSTRAINS_CONCEPT: (
        "An invariant constrains the meaning or behavior of a domain concept."
    ),
    Relation.DEFINED_IN_TERMS_OF: "A contract uses canonical concepts rather than redefining them.",
    Relation.EXPOSES: "An environment exposes an interaction boundary.",
    Relation.PROVIDES: "A boundary provides an observation or control capability.",
    Relation.CLASSIFIED_BY: (
        "A boundary is classified by the information and operations at a layer."
    ),
    Relation.USES_BOUNDARY: "A realization uses one or more interaction boundaries.",
    Relation.ATTEMPTS_TO_FULFILL: (
        "A candidate binding targets a contract; this is not verification."
    ),
    Relation.MUST_PRESERVE: "A contract or binding must preserve an applicable invariant.",
    Relation.REQUIRES_CAPABILITY: "A contract or binding declares the capabilities it requires.",
    Relation.PRODUCES: "A system or binding produces an exchange with standardized meaning.",
    Relation.CONSUMED_BY: "A system consumes the standardized exchange.",
    Relation.DEMONSTRATES_OBJECTIVE: "An independence example holds one objective fixed.",
    Relation.HOLDS_CONTRACT: "An independence example holds one behavioral contract fixed.",
    Relation.COMPARES_BINDING: (
        "An independence example compares candidate realizations of that contract."
    ),
}.items():
    RELATION_CATALOG[_relation] = replace(RELATION_CATALOG[_relation], meaning=_meaning)

# The fixed specification's role diagram and relationship explanations share this selection.
METAMODEL_RELATIONS = (
    Relation.OWNS,
    Relation.CONSTRAINS_CONCEPT,
    Relation.SPECIFIED_BY,
    Relation.CONCERNS,
    Relation.DEFINED_IN_TERMS_OF,
    Relation.EXPOSES,
    Relation.PROVIDES,
    Relation.CLASSIFIED_BY,
    Relation.USES_BOUNDARY,
    Relation.ATTEMPTS_TO_FULFILL,
    Relation.MUST_PRESERVE,
)

# Explain the capability requirement too, without adding more arrows to the compact role diagram.
EXPLANATORY_RELATIONS = (*METAMODEL_RELATIONS, Relation.REQUIRES_CAPABILITY)

REQUIRED_RELATIONS = (
    (R.SYSTEM, Relation.OWNS, "out"),
    (R.RESPONSIBILITY, Relation.SPECIFIED_BY, "out"),
    (R.BINDING, Relation.ATTEMPTS_TO_FULFILL, "out"),
    (R.BINDING, Relation.USES_BOUNDARY, "out"),
    (R.EXCHANGE, Relation.CONSUMED_BY, "out"),
    (R.EXCHANGE, Relation.PRODUCES, "in"),
    (R.REQUIREMENT, Relation.APPLIES_TO, "out"),
    (R.CRITERION, Relation.APPLIES_TO, "out"),
)
BINDING_INTERCEPTOR = Interceptor(
    id="binding-conformance",
    target_type=R.BINDING,
    handler="pending",
    version="1",
    trigger="dependency_changed",
    evidence_required=[
        "contract-conformance",
        "capability-availability",
        "invariant-preservation",
        "performance-measurements",
    ],
)


def architecture_schema(
    *,
    domain_relations: dict[str, RelationDefinition] | None = None,
    interceptors: list[Interceptor] | None = None,
) -> GraphSchema:
    relations = {str(name): spec.definition() for name, spec in RELATION_CATALOG.items()}
    for name, definition in (domain_relations or {}).items():
        if name in relations:
            raise ValueError(f"Cannot replace a canonical architecture relation: {name}")
        if set(definition.source) != {R.CONCEPT} or set(definition.target) != {R.CONCEPT}:
            raise ValueError("Additional domain relations must connect DomainConcept instances")
        relations[name] = definition
    invariants: list[Invariant] = [
        UniqueInvariant(kind="unique", node_type=role, property="name")
        for role in (R.CONCEPT, R.REALIZATION_CONCEPT, R.SYSTEM, R.EXCHANGE)
    ]
    invariants.append(UniqueInvariant(kind="unique", node_type=R.ONTOLOGY, property="kind"))
    invariants.extend(
        RequiresEdgeInvariant.model_validate(
            {
                "kind": "requires_edge",
                "node_type": role,
                "relation": relation,
                "direction": direction,
            }
        )
        for role, relation, direction in REQUIRED_RELATIONS
    )
    return GraphSchema(
        version=PACKAGE_VERSION,
        node_types={
            str(role): cast(JsonObject, model.model_json_schema())
            for role, model in ROLE_CATALOG.items()
        },
        relations=relations,
        invariants=invariants,
        interceptors=interceptors
        if interceptors is not None
        else [BINDING_INTERCEPTOR.model_copy(deep=True)],
    )
