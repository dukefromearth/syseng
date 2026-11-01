"""Compile canonical architecture facts into a fixed, coherent reading document.

The architectural roles and reading order belong to this optional application.
Names, obligations, scenarios, technologies, targets and results belong to the graph.
The underlying graph engine remains independent of this architecture vocabulary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from functools import partial

from typed_graph.application.specification import (
    DiagramDirection,
    DiagramProfile,
    DiagramView,
    DisclosureSection,
    MarkdownSpecification,
    PresentationProfile,
    SpecificationState,
    _anchor,
    _canonical,
    _diagram,
    _diagram_label,
    _digest,
    _text,
    _Writer,
)
from typed_graph.architecture.models import (
    ROLE_CATALOG,
    BaseProperties,
    ContractProperties,
    GovernanceCategory,
    GovernanceProperties,
    LayerProperties,
    ModelProperties,
    OntologyKind,
    OntologyProperties,
    Relation,
    RequirementProperties,
    Role,
    ScopedProperties,
)
from typed_graph.architecture.schema import (
    EXPLANATORY_RELATIONS,
    METAMODEL_RELATIONS,
    RELATION_CATALOG,
)
from typed_graph.domain.models import Node, dump_wire


def _order(node: Node) -> tuple[int, str, str]:
    properties = _properties(node)
    rank = 0
    if isinstance(properties, OntologyProperties):
        rank = list(OntologyKind).index(properties.kind)
    elif isinstance(properties, LayerProperties) and properties.rank is not None:
        rank = properties.rank
    return (rank, _name(node).casefold(), node.id)


def _properties(node: Node) -> BaseProperties:
    return ROLE_CATALOG[Role(node.type)].model_validate(node.properties)


def _name(node: Node) -> str:
    return _properties(node).name


def _description(node: Node) -> str:
    return _properties(node).description


def _statements(node: Node) -> list[str]:
    return _properties(node).statements


def _version(node: Node) -> str:
    properties = _properties(node)
    return (
        properties.version if isinstance(properties, (ModelProperties, ContractProperties)) else ""
    )


def _priority(node: Node) -> str:
    properties = _properties(node)
    return properties.priority if isinstance(properties, RequirementProperties) else "Not recorded"


def _governance_category(node: Node) -> GovernanceCategory:
    properties = _properties(node)
    if not isinstance(properties, GovernanceProperties):
        raise ValueError("Expected governance rule")
    return GovernanceCategory(properties.category)


class _Architecture:
    def __init__(self, state: SpecificationState):
        self.state = state
        self.nodes = {node.id: node for node in state.snapshot.nodes}
        self.outgoing: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.incoming: dict[tuple[str, str], set[str]] = defaultdict(set)
        for edge in state.snapshot.edges:
            self.outgoing[(edge.source, edge.type)].add(edge.target)
            self.incoming[(edge.target, edge.type)].add(edge.source)

    def of(self, role: Role) -> list[Node]:
        return sorted((node for node in self.nodes.values() if node.type == role), key=_order)

    def follow(
        self, nodes: list[Node], relation: Relation, *, incoming: bool = False
    ) -> list[Node]:
        adjacency = self.incoming if incoming else self.outgoing
        reached = {target for node in nodes for target in adjacency.get((node.id, relation), set())}
        return sorted((self.nodes[identity] for identity in reached), key=_order)

    def sequence(self, nodes: list[Node]) -> list[Node]:
        """Topological reading order from semantic next links; stable ties, cycles explicit."""
        remaining = {node.id: node for node in nodes}
        result: list[Node] = []
        while remaining:
            ready = sorted(
                (
                    node
                    for node in remaining.values()
                    if not (self.incoming.get((node.id, Relation.NEXT), set()) & remaining.keys())
                ),
                key=_order,
            )
            if not ready:
                raise ValueError("Architecture sequence contains a cycle")
            result.extend(ready)
            for node in ready:
                del remaining[node.id]
        return result

    def contracts(self, system: Node) -> list[Node]:
        return self.follow(self.follow([system], Relation.OWNS), Relation.SPECIFIED_BY)

    def bindings(self, system: Node) -> list[Node]:
        return self.follow(self.contracts(system), Relation.ATTEMPTS_TO_FULFILL, incoming=True)

    def criteria(self, system: Node) -> list[Node]:
        candidates = self.follow(
            [system, *self.bindings(system)], Relation.APPLIES_TO, incoming=True
        )
        candidates += self.follow(
            self.contracts(system), Relation.CONSTRAINS_CONTRACT, incoming=True
        )
        return sorted(
            {node.id: node for node in candidates if node.type == Role.CRITERION}.values(),
            key=_order,
        )


def compile_architecture(
    state: SpecificationState, *, include_appendices: bool = True
) -> MarkdownSpecification:
    """Compile the architecture application vocabulary, without model-specific content."""
    graph = _Architecture(state)
    documents = graph.of(Role.MODEL)
    if len(documents) != 1:
        raise ValueError("Architecture compilation requires one ArchitectureModel root")
    document = documents[0]
    writer = _Writer()
    diagrams: list[DiagramView] = []
    disclosures: list[DisclosureSection] = []

    def heading(title: str, level: int, identity: str) -> None:
        writer.heading(title, level, f"architecture:{identity}")

    def body(node: Node, level: int = 2) -> None:
        writer.body(_description(node), f"architecture-body:{node.id}", level)

    def statements(node: Node) -> None:
        values = _statements(node)
        if values:
            writer.lines.extend("- " + _text(value) for value in values)
            writer.lines.append("")

    def definitions(nodes: list[Node], first: str = "Concept", second: str = "Meaning") -> None:
        if nodes:
            writer.table(
                [first, second],
                [
                    [
                        _text(_name(node)),
                        _text(" ".join([_description(node), *_statements(node)])),
                    ]
                    for node in nodes
                ],
            )
        else:
            writer.paragraph("Not recorded in the current model.")

    def diagram(
        title: str,
        identity: str,
        nodes: list[Node],
        relations: list[Relation],
        *,
        path: list[Relation] | None = None,
        direction: DiagramDirection = DiagramDirection.TOP_TO_BOTTOM,
        level: int = 3,
    ) -> None:
        if not nodes:
            return
        selection = DiagramProfile(
            id=identity,
            title=title,
            node_ids=[node.id for node in nodes],
            relations=[relation.value for relation in relations],
            direction=direction,
        )
        if path is not None:
            selection.relation_path = [relation.value for relation in path]
        diagrams.append(
            _diagram(writer, state.snapshot, PresentationProfile(), selection, len(diagrams), level)
        )

    def assessment_table(bindings: list[Node]) -> None:
        rows = []
        for binding in bindings:
            records = sorted(
                (item for item in state.assessments if item.target_id == binding.id),
                key=lambda item: item.key,
            )
            if not records:
                rows.append([_text(_name(binding)), "Not assessed", "No evidence recorded"])
            for record in records:
                freshness = "stale" if record.revision != state.snapshot.revision else "current"
                status = (
                    f"{record.state.value} · {record.result.status.value} · "
                    f"{freshness} revision {record.revision}"
                )
                evidence = "; ".join(_text(item.uri) for item in record.result.evidence)
                rows.append([_text(_name(binding)), status, evidence or "No evidence recorded"])
        if rows:
            writer.table(["Realization", "Recorded assessment", "Evidence"], rows)

    def criteria_table(nodes: list[Node]) -> None:
        writer.table(
            ["Criterion", "Required behavior", "Applies to"],
            [
                [
                    _text(_name(node)),
                    _text(_description(node)),
                    "; ".join(
                        _text(_name(target)) for target in graph.follow([node], Relation.APPLIES_TO)
                    ),
                ]
                for node in nodes
            ],
        )

    def disclosure(title: str, identity: str, level: int, render: Callable[[], None]) -> None:
        heading(title, level, identity)
        start = writer.outline[-1]
        render()
        disclosures.append(
            DisclosureSection(
                id=start.id, title=title, start_line=start.line, end_line=len(writer.lines)
            )
        )

    writer.heading(_name(document), 1, f"node:{document.id}")
    body(document, 1)
    version = _version(document)
    if version:
        writer.paragraph(f"Version {_text(version)}")
    writer.paragraph(
        "This reading document separates architectural meaning, system obligations and "
        "realization candidates. Recorded assessments are shown with their evidence and revision."
    )

    heading("1. Unified metamodel", 2, "metamodel")
    definitions(graph.of(Role.ONTOLOGY), "Model", "Defines")
    groups = [
        ("domain", "Domain · Meaning", [Role.CONCEPT, Role.INVARIANT]),
        ("system", "System · Responsibility", [Role.SYSTEM, Role.RESPONSIBILITY, Role.CONTRACT]),
        (
            "realization",
            "Realization · Mechanism",
            [
                Role.ENVIRONMENT,
                Role.BOUNDARY,
                Role.CAPABILITY,
                Role.LAYER,
                Role.BINDING,
            ],
        ),
    ]
    registered = state.snapshot.schema_definition
    roles = {
        role for _, _, selected in groups for role in selected if role in registered.node_types
    }
    lines = ["flowchart TB"]
    for group_id, label, selected in groups:
        lines.append(f'    subgraph {group_id}["{_diagram_label(label)}"]')
        for role in selected:
            if role in roles:
                label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", role.value)
                lines.append(f'        role{role.value}["{_diagram_label(label)}"]')
        lines.append("    end")
    used_relations = []
    for relation in METAMODEL_RELATIONS:
        definition = registered.relations.get(relation)
        if definition is None:
            continue
        used_relations.append(relation.value)
        for source in definition.source:
            for target in definition.target:
                if source in roles and target in roles:
                    label = _diagram_label(relation.value.replace("_", " "))
                    lines.append(f'    role{source} -->|"{label}"| role{target}')
    heading("Architectural roles and their relationships", 3, "role-metamodel")
    line = len(writer.lines)
    writer.lines.extend(["```mermaid", *lines, "```", ""])
    diagrams.append(
        DiagramView(
            id=_anchor("architecture-role-metamodel"),
            title="Architectural roles and their relationships",
            source="\n".join(lines),
            node_ids=[],
            edge_ids=[],
            omitted_node_count=0,
            omitted_edge_count=0,
            line=line,
            schema_roles=sorted(roles),
            schema_relations=used_relations,
        )
    )
    writer.paragraph(
        "This diagram describes registered architectural roles, not particular systems or "
        "verified bindings. A binding attempts to fulfill a contract; assessment determines "
        "whether the required evidence supports that claim."
    )

    heading("2. Domain ontology", 2, "domain")
    definitions(graph.of(Role.CONCEPT))
    concept_ids = {node.id for node in graph.of(Role.CONCEPT)}
    domain_sources = concept_ids | {node.id for node in graph.of(Role.INVARIANT)}
    domain_edges = sorted(
        (
            edge
            for edge in state.snapshot.edges
            if edge.source in domain_sources and edge.target in concept_ids
        ),
        key=lambda edge: (_name(graph.nodes[edge.source]), edge.type, edge.target, edge.id),
    )
    if domain_edges:
        heading("Fundamental relationships", 3, "domain-relationships")
        writer.table(
            ["From", "Relationship", "To"],
            [
                [
                    _text(_name(graph.nodes[edge.source])),
                    _text(edge.type.replace("_", " ")),
                    _text(_name(graph.nodes[edge.target])),
                ]
                for edge in domain_edges
            ],
        )
        writer.paragraph("These relationships describe meaning, not a mandatory linear pipeline.")
    heading("Domain invariants", 3, "domain-invariants")
    definitions(graph.of(Role.INVARIANT), "Invariant", "Required property")

    heading("3. System ontology", 2, "systems")
    systems = graph.of(Role.SYSTEM)
    writer.table(
        ["System", "Responsibility", "Contractual output"],
        [
            [
                f"[{_text(_name(system))}](#{_anchor(f'node:{system.id}')})",
                "; ".join(
                    _text(_description(node)) for node in graph.follow([system], Relation.OWNS)
                ),
                "; ".join(_text(_description(node)) for node in graph.contracts(system)),
            ]
            for system in systems
        ],
    )
    diagram(
        "System relationships",
        "systems",
        systems,
        [],
        path=[Relation.PRODUCES, Relation.CONSUMED_BY],
    )
    for system in systems:
        writer.heading(_name(system), 3, f"node:{system.id}")
        system_section = writer.outline[-1]
        for responsibility in graph.follow([system], Relation.OWNS):
            body(responsibility, 3)
        for contract in graph.contracts(system):
            writer.paragraph(f"**Promised output:** {_text(_description(contract))}.")
            writer.paragraph(f"Contract version: {_text(_version(contract))}.")
            statements(contract)
        bindings = graph.bindings(system)
        if bindings:
            heading(
                "Candidate realization" if len(bindings) == 1 else "Candidate realizations",
                4,
                f"candidate:{system.id}",
            )
            for binding in bindings:
                writer.paragraph(f"**{_text(_name(binding))}**")
                body(binding, 4)
                statements(binding)
            assessment_table(bindings)
        criteria = graph.criteria(system)
        if criteria:
            disclosure(
                "Acceptance requirements",
                f"acceptance:{system.id}",
                4,
                partial(criteria_table, criteria),
            )
        concepts = graph.follow([system], Relation.USES_CONCEPT)
        if concepts:
            disclosure(
                "Supporting vocabulary",
                f"vocabulary:{system.id}",
                4,
                partial(definitions, concepts),
            )

        disclosures.append(
            DisclosureSection(
                id=system_section.id,
                title=system_section.label,
                start_line=system_section.line,
                end_line=len(writer.lines),
            )
        )

    heading("4. Realization ontology", 2, "realization")
    definitions(graph.of(Role.REALIZATION_CONCEPT))
    heading("Abstraction layers", 3, "layers")
    definitions(graph.of(Role.LAYER), "Layer", "Available information")
    heading("Candidate realizations", 3, "candidate-realizations")
    writer.table(
        ["Binding", "Proposed mechanism", "Interaction boundaries"],
        [
            [
                _text(_name(binding)),
                _text(_description(binding)),
                "; ".join(
                    _text(_name(node)) for node in graph.follow([binding], Relation.USES_BOUNDARY)
                ),
            ]
            for binding in graph.of(Role.BINDING)
        ],
    )
    writer.paragraph(
        "A candidate mechanism is not a conformance result. The contract remains the "
        "reference against which its capabilities and observed behavior are evaluated."
    )

    for role, title in [
        (Role.ENVIRONMENT, "Candidate environments"),
        (Role.BOUNDARY, "Interaction boundaries"),
        (Role.CAPABILITY, "Required and proposed capabilities"),
    ]:
        disclosure(
            title,
            f"realization-support:{role}",
            3,
            partial(definitions, graph.of(role), "Name", "Meaning and constraints"),
        )

    heading("5. Cross-model relationships", 2, "cross-model")
    writer.table(
        ["Relationship", "Meaning"],
        [
            [
                _text(relation.value.replace("_", " ")),
                _text(RELATION_CATALOG[relation].meaning),
            ]
            for relation in EXPLANATORY_RELATIONS
            if relation in state.snapshot.schema_definition.relations
        ],
    )
    heading("Information crossing system boundaries", 3, "exchanges")
    for exchange in graph.of(Role.EXCHANGE):
        heading(_name(exchange), 4, f"exchange:{exchange.id}")
        producers = graph.follow([exchange], Relation.PRODUCES, incoming=True)
        consumers = graph.follow([exchange], Relation.CONSUMED_BY)
        writer.paragraph(
            "**Producer:** "
            + "; ".join(_text(_name(node)) for node in producers)
            + ". **Consumer:** "
            + "; ".join(_text(_name(node)) for node in consumers)
            + "."
        )
        writer.paragraph(f"Exchange version: {_text(_version(exchange))}.")
        body(exchange, 4)
        statements(exchange)

    heading("6. Demonstrating independence", 2, "independence")
    examples = graph.of(Role.INDEPENDENCE)
    if not examples:
        writer.paragraph("No independence comparison has been recorded.")
    for example in examples:
        heading(_name(example), 3, f"independence:{example.id}")
        body(example, 3)
        statements(example)
        for objective in graph.follow([example], Relation.DEMONSTRATES_OBJECTIVE):
            heading("Unchanged objective", 4, f"objective:{objective.id}")
            body(objective, 4)
            statements(objective)
            requirements = graph.follow([objective], Relation.APPLIES_TO, incoming=True)
            if requirements:
                definitions(requirements, "Constraint", "Required behavior")
        for contract in graph.follow([example], Relation.HOLDS_CONTRACT):
            heading("Unchanged system contract", 4, f"fixed-contract:{contract.id}")
            body(contract, 4)
            writer.paragraph(f"Contract version: {_text(_version(contract))}.")
            statements(contract)
        bindings = graph.follow([example], Relation.COMPARES_BINDING)
        heading("Alternative realization candidates", 4, f"alternatives:{example.id}")
        writer.table(
            ["Candidate", "Mechanism and limitations", "Required capabilities"],
            [
                [
                    _text(_name(binding)),
                    _text(_description(binding)),
                    "; ".join(
                        _text(_name(capability))
                        for capability in graph.follow([binding], Relation.REQUIRES_CAPABILITY)
                    ),
                ]
                for binding in bindings
            ],
        )
        assessment_table(bindings)
        writer.paragraph(
            "The comparison holds the objective and contract fixed. Different mechanisms "
            "are not interchangeable merely because they appear in this table; each must "
            "independently demonstrate sufficient capabilities and preservation of the constraints."
        )
    governance_criteria = {
        node.id: node
        for role in graph.of(Role.GOVERNANCE_ROLE)
        for node in graph.follow([role], Relation.APPLIES_TO, incoming=True)
        if node.type == Role.CRITERION
    }
    if governance_criteria:
        heading("Architectural acceptance", 3, "architectural-acceptance")
        definitions(
            sorted(governance_criteria.values(), key=_order), "Criterion", "Required evidence"
        )

    heading("7. Model invariants", 2, "model-invariants")
    for rule in graph.of(Role.GOVERNANCE):
        if _governance_category(rule) != GovernanceCategory.MODEL_INVARIANT:
            continue
        heading(_name(rule), 3, f"governance:{rule.id}")
        body(rule, 3)
        statements(rule)

    if include_appendices:
        heading("Build appendices", 2, "appendices")

        def build_constraints() -> None:
            for rule in graph.of(Role.GOVERNANCE):
                if _governance_category(rule) != GovernanceCategory.MODEL_INVARIANT:
                    heading(_name(rule), 4, f"build-constraint:{rule.id}")
                    body(rule, 4)
                    statements(rule)

        disclosure("Build constraints and measurement", "build-constraints", 3, build_constraints)

        def scenarios() -> None:
            for scenario in graph.of(Role.SCENARIO):
                heading(_name(scenario), 3, f"scenario:{scenario.id}")
                body(scenario, 3)
                scope = _properties(scenario)
                if isinstance(scope, ScopedProperties):
                    writer.paragraph(f"Scope: {scope.scope.value}.")
                statements(scenario)
                steps = graph.sequence(graph.follow([scenario], Relation.CONTAINS_STEP))
                if steps:
                    diagram(
                        "Experiment and execution",
                        f"flow:{scenario.id}",
                        steps,
                        [Relation.NEXT],
                        level=4,
                    )
                    definitions(steps, "Step", "Behavior")

        disclosure("Reference and future scenarios", "scenarios", 3, scenarios)

        def requirement_table() -> None:
            writer.table(
                ["Requirement", "Priority", "Required behavior"],
                [
                    [
                        _text(_name(node)),
                        _text(_priority(node)),
                        _text(_description(node)),
                    ]
                    for node in graph.of(Role.REQUIREMENT)
                ],
            )

        disclosure("Product and functional requirements", "requirements", 3, requirement_table)
        for role, title, first, second in [
            (Role.CRITERION, "Acceptance targets", "Criterion", "Target"),
            (Role.FAILURE, "Required negative cases", "Failure case", "Expected handling"),
            (Role.TECHNOLOGY, "Reuse candidates", "Candidate", "Proposed use"),
            (Role.GOVERNANCE_ROLE, "Architectural governance", "Role", "Responsibility"),
            (Role.EXCLUSION, "Excluded from this release", "Exclusion", "Scope"),
        ]:
            disclosure(
                title,
                f"appendix:{role}",
                3,
                partial(definitions, graph.of(role), first, second),
            )

        def phases() -> None:
            for phase in graph.sequence(graph.of(Role.PHASE)):
                heading(_name(phase), 4, f"phase:{phase.id}")
                body(phase, 4)
                scope = _properties(phase)
                if isinstance(scope, ScopedProperties):
                    writer.paragraph(f"Scope: {scope.scope.value}.")
                statements(phase)

        disclosure("Build sequence and exit conditions", "appendix:phases", 3, phases)

    heading("Resulting minimum architecture", 2, "minimum")
    definitions(graph.of(Role.ONTOLOGY), "Model", "Independent responsibility")
    writer.paragraph(
        "The architecture assigns meaning, responsibility and mechanism separately. "
        "Whether a particular realization fulfills its promises remains an evidence question."
    )
    assessment_table(graph.of(Role.BINDING))
    markdown = "\n".join(writer.lines).rstrip() + "\n"
    assessment_digest = _digest(
        _canonical(
            [dump_wire(item) for item in sorted(state.assessments, key=lambda item: item.key)]
        )
    )
    return MarkdownSpecification(
        revision=state.snapshot.revision,
        assessment_digest=assessment_digest,
        state_digest=_digest(f"{state.snapshot.revision}:{assessment_digest}:{markdown}"),
        title=_name(document),
        markdown=markdown,
        outline=writer.outline,
        node_count=len(state.snapshot.nodes),
        edge_count=len(state.snapshot.edges),
        diagrams=diagrams,
        disclosures=disclosures,
    )
