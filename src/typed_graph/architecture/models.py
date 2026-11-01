"""Canonical meaning-only roles for the optional architecture/v1 package."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from typed_graph.domain.models import Identifier, Omittable, StrictModel

PACKAGE_VERSION = "typed-graph/architecture/v1"


class Role(StrEnum):
    MODEL = "ArchitectureModel"
    ONTOLOGY = "Ontology"
    CONCEPT = "DomainConcept"
    INVARIANT = "Invariant"
    SYSTEM = "System"
    RESPONSIBILITY = "Responsibility"
    CONTRACT = "BehavioralContract"
    EXCHANGE = "ExchangeContract"
    LOCAL_CONCEPT = "ScopedConcept"
    REALIZATION_CONCEPT = "RealizationConcept"
    ENVIRONMENT = "Environment"
    BOUNDARY = "Boundary"
    CAPABILITY = "Capability"
    LAYER = "Layer"
    BINDING = "Binding"
    TECHNOLOGY = "TechnologyCandidate"
    REQUIREMENT = "Requirement"
    CRITERION = "AcceptanceCriterion"
    SCENARIO = "Scenario"
    STEP = "ScenarioStep"
    FAILURE = "FailureCase"
    PHASE = "Phase"
    EXCLUSION = "Exclusion"
    GOVERNANCE = "GovernanceRule"
    GOVERNANCE_ROLE = "GovernanceRole"
    OBJECTIVE = "Objective"
    INDEPENDENCE = "IndependenceExample"


class Relation(StrEnum):
    EXCHANGES = "exchanges"
    CONSTRAINS_CONTRACT = "constrains_contract"
    OWNS = "owns"
    SPECIFIED_BY = "specified_by"
    CONCERNS = "concerns"
    DEFINED_IN_TERMS_OF = "defined_in_terms_of"
    PRODUCES = "produces"
    CONSUMED_BY = "consumed_by"
    CONSTRAINS = "constrains"
    CONSTRAINS_CONCEPT = "constrains_concept"
    INCLUDES = "includes"
    USES_CONCEPT = "uses_concept"
    SPECIALIZES = "specializes"
    EXPRESSED_AS = "expressed_as"
    CONSUMES = "consumes"
    YIELDS = "yields"
    INFORMS = "informs"
    SELECTS = "selects"
    MODIFIES = "modifies"
    ATTEMPTS_TO_FULFILL = "attempts_to_fulfill"
    USES_BOUNDARY = "uses_boundary"
    REQUIRES_CAPABILITY = "requires_capability"
    MUST_PRESERVE = "must_preserve"
    CANDIDATE_FOR = "candidate_for"
    EXPOSES = "exposes"
    PROVIDES = "provides"
    CLASSIFIED_BY = "classified_by"
    APPLIES_TO = "applies_to"
    GOVERNED_BY = "governed_by"
    CONTAINS_STEP = "contains_step"
    PERFORMED_BY = "performed_by"
    NEXT = "next"
    DELIVERS = "delivers"
    EVALUATES = "evaluates"
    SUPPORTS = "supports"
    DEMONSTRATES_OBJECTIVE = "demonstrates_objective"
    HOLDS_CONTRACT = "holds_contract"
    COMPARES_BINDING = "compares_binding"


class OntologyKind(StrEnum):
    DOMAIN = "domain"
    SYSTEM = "system"
    REALIZATION = "realization"


class BindingLifecycle(StrEnum):
    CANDIDATE = "candidate"


class RequirementPriority(StrEnum):
    REQUIRED = "required"
    FUTURE = "future"


class GovernanceCategory(StrEnum):
    MODEL_INVARIANT = "model_invariant"
    BUILD_CONSTRAINT = "build_constraint"
    RUNTIME_CONSTRAINT = "runtime_constraint"
    MEASUREMENT = "measurement"
    REUSE = "reuse"


class ScenarioScope(StrEnum):
    REFERENCE = "reference"
    FUTURE = "future"


class BaseProperties(StrictModel):
    name: Identifier
    description: str
    statements: list[str] = Field(default_factory=list)


class ModelProperties(BaseProperties):
    version: Identifier


class OntologyProperties(BaseProperties):
    kind: Literal[OntologyKind.DOMAIN, OntologyKind.SYSTEM, OntologyKind.REALIZATION]


class ContractProperties(BaseProperties):
    version: Identifier


class BindingProperties(BaseProperties):
    lifecycle: Literal[BindingLifecycle.CANDIDATE] = BindingLifecycle.CANDIDATE


class RequirementProperties(BaseProperties):
    priority: Literal[RequirementPriority.REQUIRED, RequirementPriority.FUTURE] = (
        RequirementPriority.REQUIRED
    )


class LayerProperties(BaseProperties):
    # An authored taxonomy may be ranked. Rank never means a rendering pipeline.
    rank: Omittable[Annotated[int, Field(ge=0)]] = None


class GovernanceProperties(BaseProperties):
    category: Literal[
        GovernanceCategory.MODEL_INVARIANT,
        GovernanceCategory.BUILD_CONSTRAINT,
        GovernanceCategory.RUNTIME_CONSTRAINT,
        GovernanceCategory.MEASUREMENT,
        GovernanceCategory.REUSE,
    ]


class ScopedProperties(BaseProperties):
    scope: Literal[ScenarioScope.REFERENCE, ScenarioScope.FUTURE] = ScenarioScope.REFERENCE


SystemProperties = BaseProperties
ResponsibilityProperties = BaseProperties
ConceptProperties = BaseProperties
BoundaryProperties = BaseProperties

ROLE_CATALOG: dict[Role, type[BaseProperties]] = {role: BaseProperties for role in Role}
ROLE_CATALOG.update(
    {
        Role.MODEL: ModelProperties,
        Role.ONTOLOGY: OntologyProperties,
        Role.CONTRACT: ContractProperties,
        Role.EXCHANGE: ContractProperties,
        Role.BINDING: BindingProperties,
        Role.REQUIREMENT: RequirementProperties,
        Role.LAYER: LayerProperties,
        Role.GOVERNANCE: GovernanceProperties,
        Role.SCENARIO: ScopedProperties,
        Role.PHASE: ScopedProperties,
    }
)
