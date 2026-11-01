"""Reproducible metamodel authoring through the actual MCP stdio transport.

The only source import is an empty graph plus schema. Every entity/edge is authored
with apply_changes. Refuses an existing workspace to avoid overwriting user work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters
from mcp.client import Client

HERE = Path(__file__).resolve().parent
SECTIONS = ["Purpose", "Domain", "Systems", "Realization", "Example", "Governance"]


def property_schema() -> dict[str, Any]:
    """Define the common vocabulary once; instantiate for each authored type."""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "section": {"enum": SECTIONS},
            "order": {"type": "integer"},
            "status": {"enum": ["definition", "requirement", "candidate", "unknown"]},
        },
        "required": ["name", "description", "section", "order", "status"],
        "additionalProperties": False,
    }


# Cross-ontology meanings are authoritative, not inferred from example occurrences.
CROSS_RELATION_ENDPOINTS = {
    "owns": ("System", "Responsibility"),
    "specified_by": ("Responsibility", "Contract"),
    "concerns": ("Responsibility", "DomainConcept"),
    "defined_in_terms_of": ("Contract", "DomainConcept"),
    "exposes": ("Environment", "InteractionBoundary"),
    "provides": ("InteractionBoundary", "Capability"),
    "classified_by": ("InteractionBoundary", "AbstractionLayer"),
    "uses": ("Binding", "InteractionBoundary"),
    "satisfies": ("Binding", "Contract"),
    "preserves": ("Binding", "Invariant"),
}


def build() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    relations: dict[str, Any] = {
        kind: {"source": [source], "target": [target], "impact": "target_to_source"}
        for kind, (source, target) in CROSS_RELATION_ENDPOINTS.items()
    }

    def node(
        identity: str,
        kind: str,
        name: str,
        description: str,
        section: str,
        status: str = "definition",
    ) -> str:
        nodes.append(
            {
                "id": identity,
                "type": kind,
                "properties": {
                    "name": name,
                    "description": description,
                    "section": section,
                    "order": len(nodes),
                    "status": status,
                },
            }
        )
        return identity

    def edge(kind: str, source: str, target: str) -> None:
        by_id = {n["id"]: n["type"] for n in nodes}
        definition = relations.setdefault(
            kind, {"source": [], "target": [], "impact": "target_to_source"}
        )
        for field, identity in [("source", source), ("target", target)]:
            if by_id[identity] not in definition[field]:
                if kind in CROSS_RELATION_ENDPOINTS:
                    raise ValueError(f"Invalid {kind} {field} type: {by_id[identity]}")
                definition[field].append(by_id[identity])
        edges.append(
            {"id": f"{kind}:{source}:{target}", "type": kind, "source": source, "target": target}
        )

    node(
        "purpose",
        "ModelPurpose",
        "Architectural Metamodel v1.0",
        "A technology-independent architecture for learning and executing transformations "
        "of digital experiences while preserving correctness and real-time performance. "
        "Three independently extensible ontologies are connected by fixed semantic relationships; "
        "do not prematurely choose components.",
        "Purpose",
    )
    domain = [
        (
            "experience",
            "Experience",
            "Evolving state over time and interaction, expressed through representations.",
        ),
        (
            "representation",
            "Representation",
            "Describes an experience at some level of abstraction.",
        ),
        (
            "production",
            "Production",
            "Transforms information toward presentation; consumes and produces "
            "representations. Production may be a graph, not a line.",
        ),
        ("presentation", "Presentation", "A perceptible result that realizes an experience."),
        ("objective", "Objective", "A desired change that constrains an intervention."),
        ("intervention", "Intervention", "Modifies information or production."),
        (
            "counterfactual",
            "Counterfactual",
            "Alternative outcomes under controlled conditions, enabling comparable experiences.",
        ),
        ("evidence", "Evidence", "Observations with provenance that support evaluation."),
        ("policy", "Policy", "A reusable intervention rule that selects interventions."),
    ]
    for identity, name, description in domain:
        node(identity, "DomainConcept", name, description, "Domain")
    for relation, source, target in [
        ("expressed_as", "experience", "representation"),
        ("consumes", "production", "representation"),
        ("produces", "production", "representation"),
        ("yields", "production", "presentation"),
        ("realizes", "presentation", "experience"),
        ("constrains", "objective", "intervention"),
        ("modifies", "intervention", "production"),
        ("modifies", "intervention", "presentation"),
        ("controls_conditions_for", "experience", "counterfactual"),
        ("grounds", "counterfactual", "evidence"),
        ("informs", "evidence", "policy"),
        ("guides", "objective", "policy"),
        ("selects", "policy", "intervention"),
    ]:
        edge(relation, source, target)
    invariants = [
        (
            "causal",
            "Causal correspondence",
            "Known shared conditions and controlled differences make outcomes comparable.",
        ),
        ("provenance", "Provenance", "Preserve the origin and interpretation of observations."),
        ("semantic", "Semantic preservation", "Preserve the properties required by the objective."),
        (
            "integrity",
            "Presentation integrity",
            "Prohibit exposure to the original content IF strict prevention is "
            "required; this is a conditional requirement.",
        ),
        (
            "performance",
            "Performance",
            "Latency and throughput are parameterized requirements. 120 FPS "
            "implies an approximately 8.33 ms frame interval, not a universal "
            "limit or automatically the entire intervention budget.",
        ),
    ]
    for identity, name, description in invariants:
        node(identity, "Invariant", name, description, "Domain", "requirement")
    systems = [
        (
            "S1",
            "Counterfactual Experimentation",
            "Produces comparable alternative experiences; research path.",
            "Controlled, attributable evidence.",
            ["experience", "counterfactual", "evidence"],
        ),
        (
            "S2",
            "Transformation Synthesis",
            "Derives and validates reusable interventions; research path.",
            "Policies with defined applicability and verified properties. This is "
            "a promised obligation, not a claim of completed verification.",
            ["policy", "intervention", "evidence", "objective"],
        ),
        (
            "S3",
            "Presentation Mediation",
            "Executes interventions within an environment; runtime path.",
            "The modified presentation satisfies applicable constraints.",
            ["presentation", "production", "intervention", "objective"],
        ),
        (
            "S4",
            "Preference Management",
            "Manages desired outcomes and feedback; intent path.",
            "Stable technology-independent objectives.",
            ["objective", "experience"],
        ),
    ]
    for identity, name, responsibility, contract, concepts in systems:
        node(
            identity,
            "System",
            f"{identity} · {name}",
            "Owns a responsibility, not the definition of any domain concept.",
            "Systems",
        )
        node(
            f"{identity}-responsibility",
            "Responsibility",
            name + " responsibility",
            responsibility,
            "Systems",
        )
        node(
            f"{identity}-contract",
            "Contract",
            name + " contract",
            contract,
            "Systems",
            "requirement",
        )
        edge("owns", identity, f"{identity}-responsibility")
        edge("specified_by", f"{identity}-responsibility", f"{identity}-contract")
        for concept in concepts:
            edge("concerns", f"{identity}-responsibility", concept)
            edge("defined_in_terms_of", f"{identity}-contract", concept)
    for relation, source, target in [
        ("supplies_objective", "S4", "S2"),
        ("supplies_evidence", "S1", "S2"),
        ("supplies_policy", "S2", "S3"),
        ("supplies_preference_activation", "S4", "S3"),
        ("mediates", "S3", "presentation"),
    ]:
        edge(relation, source, target)
    core = [
        (
            "environment-concept",
            "Environment",
            "A computational or physical producer of experiences.",
        ),
        (
            "layer-concept",
            "Abstraction Layer",
            "Classification by information and operations; layers are NOT a sequential pipeline.",
        ),
        (
            "boundary-concept",
            "Interaction Boundary",
            "An observation and control point; an environment may expose some, "
            "multiple, or no relevant boundaries.",
        ),
        ("capability-concept", "Capability", "A supported observation or modification operation."),
        (
            "binding-concept",
            "Binding",
            "Connects a contract to sufficient capabilities and may use multiple boundaries.",
        ),
    ]
    for identity, name, description in core:
        node(identity, "RealizationConcept", name, description, "Realization")
    for identity, name, description in [
        ("L1", "State and semantics", "Entities, relations and behavior."),
        ("L2", "Presentation description", "Layout, geometry, materials and effects."),
        ("L3", "Rendering operations", "Commands, resources and shaders."),
        ("L4", "Composed representation", "Surfaces, buffers and pixels."),
        ("L5", "Physical presentation", "Display planes and timing / scanout."),
    ]:
        node(
            identity,
            "AbstractionLayer",
            f"{identity} · {name}",
            description + " A classification, not a mandatory sequential pipeline stage.",
            "Realization",
        )
    for identity, name, layers, description in [
        (
            "unreal",
            "Unreal Engine",
            ["L1", "L2", "L3", "L4"],
            "Engine execution/rendering interfaces; layer coverage depends on the "
            "selected interface.",
        ),
        (
            "godot",
            "Godot",
            ["L1", "L2", "L3", "L4"],
            "Engine execution/rendering interfaces; layer coverage depends on the "
            "selected interface.",
        ),
        ("vulkan", "Vulkan", ["L3"], "Graphics boundary, primarily rendering operations."),
        ("wayland", "Wayland", ["L4"], "Compositor boundary at composed representation."),
        ("drm", "Linux DRM/KMS", ["L5"], "Physical presentation / display control boundary."),
    ]:
        if identity in {"unreal", "godot"}:
            node(
                identity,
                "Environment",
                name,
                description
                + " Illustrative mapping, not a dependency or verified capability inventory.",
                "Realization",
            )
        node(
            identity + "-boundary",
            "InteractionBoundary",
            name + " illustrative boundary",
            description + " Exact interface and capability availability remain unknown.",
            "Realization",
            "unknown",
        )
        if identity in {"unreal", "godot"}:
            edge("exposes", identity, identity + "-boundary")
        for layer in layers:
            edge("classified_by", identity + "-boundary", layer)
    node(
        "example-objective",
        "Objective",
        "Blood → glitter at 120 FPS",
        "Replace blood with glitter while preserving other scene properties, targeting 120 FPS. "
        "The frame interval is approximately 8.33 ms; available intervention latency must be "
        "derived from the actual environment. No measurements have been completed.",
        "Example",
        "requirement",
    )
    edge("instantiates", "example-objective", "objective")
    edge("constrains", "example-objective", "S3-contract")
    capabilities = [
        (
            "targeting",
            "Specific target identification",
            "Identify the intended blood content with enough specificity to avoid "
            "unrelated changes.",
        ),
        (
            "modification",
            "Controlled modification",
            "Modify the target information or operations into the intended glitter result.",
        ),
        (
            "preservation",
            "Preservation observation",
            "Observe and establish that all required other scene properties remain preserved.",
        ),
        (
            "timing",
            "Latency and throughput measurement",
            "Measure the complete intervention and presentation path against the allocated budget.",
        ),
        (
            "recognition",
            "Pixel content recognition",
            "Recognize intended content where intrinsic object identity is absent.",
        ),
        (
            "exposure",
            "Exposure prevention observation and control",
            "Check and prevent original-content exposure when strict prevention is required.",
        ),
    ]
    for identity, name, description in capabilities:
        node(
            identity,
            "Capability",
            name,
            description + " Required capability; actual availability is unknown.",
            "Example",
            "unknown",
        )
    candidates = [
        (
            "engine-binding",
            "Engine candidate binding",
            "unreal-boundary",
            "May modify identified materials/effects if targeting, preservation "
            "and performance are demonstrated.",
            ["targeting", "modification", "preservation", "timing", "exposure"],
        ),
        (
            "graphics-binding",
            "Graphics API candidate binding",
            "vulkan-boundary",
            "May substitute resources or operations only if specific enough to "
            "preserve the contract.",
            ["targeting", "modification", "preservation", "timing", "exposure"],
        ),
        (
            "compositor-binding",
            "Compositor candidate binding",
            "wayland-boundary",
            "May alter pixels, but lacks intrinsic object identity; requires "
            "recognition and latency/exposure checks.",
            ["targeting", "modification", "preservation", "timing", "recognition", "exposure"],
        ),
    ]
    for identity, name, boundary, description, requirements in candidates:
        node(
            identity,
            "Binding",
            name,
            description + " Unverified candidate: no completed measurements, conformance proof "
            "or capability-availability evidence.",
            "Example",
            "candidate",
        )
        edge("uses", identity, boundary)
        edge("satisfies", identity, "S3-contract")
        for invariant, _, _ in invariants:
            edge("preserves", identity, invariant)
        for capability in requirements:
            edge("requires_capability", identity, capability)
            # Do not assert provides edges for unknown actual capability availability.
    node(
        "capability-relation",
        "SemanticRule",
        "Boundary provides capability",
        "The provides relation means an interaction boundary supports a "
        "capability. No candidate boundary is asserted to provide a capability "
        "until availability is established.",
        "Governance",
    )
    rules = [
        (
            "validity",
            "Binding validity",
            "Valid(B,C,I) iff B models C and B models I. A declared satisfies "
            "edge expresses an attempt to fulfill a contract, NOT proof; "
            "preserves expresses an obligation, not demonstrated "
            "preservation.",
        ),
        (
            "domain-independence",
            "Domain independence",
            "Domain concepts and invariants are independent of technologies and "
            "system decomposition.",
        ),
        (
            "system-independence",
            "System independence",
            "A system is defined by responsibility, not its implementation method.",
        ),
        (
            "capability-selection",
            "Capability-based realization",
            "Select realizations by capabilities, not assumed interface "
            "equivalence. Unreal Engine is not literally a substitute for a "
            "Vulkan interface; bindings may fulfill the same higher contract only "
            "when capabilities are sufficient.",
        ),
        (
            "joint-sufficiency",
            "Joint observation and control sufficiency",
            "Observation and control capabilities must jointly suffice for the "
            "applicable contract and invariants.",
        ),
        (
            "substitutability",
            "Semantic substitutability",
            "Substitution requires the same contract to remain preserved, not "
            "merely similar outputs or interchangeable technology names.",
        ),
        (
            "unsupported",
            "Report unsupported requirements",
            "Report unsupported requirements rather than weakening the contract.",
        ),
        (
            "result-flow",
            "Resulting architecture flow",
            "Domain meaning and invariants → system responsibilities and "
            "contracts → realization bindings → behavior subject to verification. "
            "This model does not claim that candidate behavior is already "
            "verified.",
        ),
    ]
    for identity, name, description in rules:
        node(
            identity,
            "SemanticRule" if identity in ["validity", "result-flow"] else "Guardrail",
            name,
            description,
            "Governance",
            "requirement",
        )
    schema = {
        "version": "1.0",
        "node_types": {kind: property_schema() for kind in sorted({n["type"] for n in nodes})},
        "relations": relations,
        "invariants": [],
        "interceptors": [
            {
                "id": "candidate-contract-and-invariants",
                "target_type": "Binding",
                "handler": "pending",
                "version": "1",
                "trigger": "dependency_changed",
                "evidence_required": [
                    "contract-conformance",
                    "required-invariant-preservation",
                    "capability-availability",
                    "latency-throughput-measurements",
                ],
            }
        ],
    }
    return schema, nodes, edges


async def author(workspace: Path) -> None:
    schema, nodes, edges = build()
    if workspace.exists():
        raise SystemExit(f"Refusing existing workspace: {workspace}; choose a fresh path")
    (workspace / "model").mkdir(parents=True)
    seed = {"schema": schema, "nodes": [], "edges": []}
    (workspace / "model" / "schema.json").write_text(json.dumps(seed, indent=2) + "\n")
    results: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(workspace)]
    )
    async with Client(parameters, read_timeout_seconds=120) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            response = await client.call_tool(name, arguments)
            if response.is_error:
                raise RuntimeError(f"{name}: {response}")
            result = response.structured_content
            assert isinstance(result, dict)
            results.append({"tool": name, "arguments": arguments, "result": result})
            return result

        indexed = await call("index_model", {})
        empty = await call("query_graph", {"limit": 1000})
        assert empty["nodes"] == []
        changes = [{"op": "create_node", "node": n} for n in nodes]
        changes += [{"op": "create_edge", "edge": e} for e in edges]
        applied = await call(
            "apply_changes", {"expected_revision": indexed["revision"], "changes": changes}
        )
        observed_schema = await call("get_graph_schema", {})
        observed = await call("query_graph", {"limit": 1000})
        assessments = await call("get_assessments", {})
        assert observed_schema["schema"]["node_types"] == schema["node_types"]
        assert len(observed["nodes"]) == len(nodes)
        for kind, (source_type, target_type) in CROSS_RELATION_ENDPOINTS.items():
            actual = observed_schema["schema"]["relations"][kind]
            assert actual["source"] == [source_type] and actual["target"] == [target_type]
        for system in ["S1", "S2", "S3", "S4"]:
            responsibility, contract = f"{system}-responsibility", f"{system}-contract"
            positive = await call(
                "trace_path",
                {"source": responsibility, "target": contract, "relation": "specified_by"},
            )
            assert positive["path"] == [responsibility, contract]
            negative = await call(
                "trace_path", {"source": system, "target": contract, "relation": "specified_by"}
            )
            assert negative["path"] == []
        assert len(assessments["assessments"]) == 3
        assert all(a["state"] == "pending" for a in assessments["assessments"])
        assert all(
            a["result"]["status"] == "indeterminate" and not a["result"]["evidence"]
            for a in assessments["assessments"]
        )
        for binding in ["engine-binding", "graphics-binding", "compositor-binding"]:
            trace = await call(
                "trace_path", {"source": binding, "target": "S3-contract", "relation": "satisfies"}
            )
            assert trace["path"] == [binding, "S3-contract"]
        diff = await call(
            "compare_graphs",
            {"from_revision": indexed["revision"], "to_revision": applied["revision"]},
        )
        assert len(diff["edges"]["added"]) == len(edges)
    summary = {
        "workspace": str(workspace),
        "transport": "MCP stdio / mcp.client.Client",
        "revision": applied["revision"],
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(sorted(Counter(n["type"] for n in nodes).items())),
        "relation_types": len(schema["relations"]),
        "pending_assessments": 3,
        "completed_assessments": 0,
        "tool_calls": len(results),
    }
    (workspace / "mcp-transcript.json").write_text(json.dumps(results, indent=2) + "\n")
    (workspace / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    asyncio.run(author(parser.parse_args().workspace.resolve()))
