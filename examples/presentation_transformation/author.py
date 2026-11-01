"""Author the reference platform through real MCP tools; no direct graph-store writes.

The builder is the single source for reviewable source/schema artifacts. All technologies
are candidates, every performance number is a target, and no conformance is fabricated.
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

from typed_graph.architecture.models import (
    ROLE_CATALOG,
    BindingLifecycle,
    GovernanceCategory,
    OntologyKind,
    Relation,
    RequirementPriority,
    ScenarioScope,
)
from typed_graph.architecture.models import (
    Role as Kind,
)
from typed_graph.architecture.schema import RELATION_CATALOG, architecture_schema
from typed_graph.domain.models import dump_wire

HERE = Path(__file__).resolve().parent


CONTRACT_VERSION = "1.0"


class Builder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.kinds: dict[str, Kind] = {}

    def node(
        self,
        identity: str,
        kind: Kind,
        name: str,
        description: str,
        scope: ScenarioScope = ScenarioScope.REFERENCE,
        statements: list[str] | None = None,
    ) -> str:
        if identity in self.kinds:
            raise ValueError(f"Duplicate identity: {identity}")
        values: dict[str, Any] = {
            "name": name,
            "description": description,
            "statements": statements or [],
        }
        if kind in {Kind.MODEL, Kind.CONTRACT, Kind.EXCHANGE}:
            values["version"] = CONTRACT_VERSION
        if kind == Kind.ONTOLOGY:
            values["kind"] = {
                "domain": OntologyKind.DOMAIN,
                "systems": OntologyKind.SYSTEM,
                "realization": OntologyKind.REALIZATION,
            }[identity]
        if kind == Kind.REQUIREMENT:
            values["priority"] = (
                RequirementPriority.FUTURE
                if scope == ScenarioScope.FUTURE
                else RequirementPriority.REQUIRED
            )
        if kind == Kind.BINDING:
            values["lifecycle"] = BindingLifecycle.CANDIDATE
        if kind == Kind.LAYER:
            values["rank"] = int(identity.removeprefix("L"))
        if kind in {Kind.SCENARIO, Kind.PHASE}:
            values["scope"] = scope
        if kind == Kind.GOVERNANCE:
            values["category"] = {
                "runtime-restrictions": GovernanceCategory.RUNTIME_CONSTRAINT,
                "measurement-protocol": GovernanceCategory.MEASUREMENT,
                "reuse": GovernanceCategory.REUSE,
                "implementation": GovernanceCategory.BUILD_CONSTRAINT,
            }.get(identity, GovernanceCategory.MODEL_INVARIANT)
        properties = ROLE_CATALOG[kind].model_validate(values)
        serialized = properties.model_dump(mode="json")
        if not statements:
            serialized.pop("statements")
        self.nodes.append({"id": identity, "type": kind.value, "properties": serialized})
        self.kinds[identity] = kind
        return identity

    def edge(self, relation: str, source: str, target: str) -> None:
        specification = RELATION_CATALOG[Relation(relation)]
        if (
            self.kinds[source] not in specification.source
            or self.kinds[target] not in specification.target
        ):
            raise ValueError(f"Invalid {relation}: {source} → {target}")
        self.edges.append(
            {
                "id": f"{relation}:{source}:{target}",
                "type": relation,
                "source": source,
                "target": target,
            }
        )
        # A requirement/test assigned to a system constrains its behavioral contract.
        if relation == "applies_to" and self.kinds[target] == Kind.SYSTEM:
            self.edge("constrains_contract", source, f"{target}-contract")

    def schema(self) -> dict[str, Any]:
        return dump_wire(architecture_schema())


def build() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    b = Builder()
    b.node(
        "platform",
        Kind.MODEL,
        "Presentation Transformation Platform",
        (
            "Define an unwanted visual experience, learn its desired replacement from "
            "controlled examples, and apply a reusable policy inside the "
            "application's production process. Reference slice: blood becomes glitter "
            "in a controlled Linux/Vulkan-backed game. This is a build specification, "
            "not evidence that the platform has been implemented."
        ),
    )
    b.node(
        "architecture",
        Kind.GOVERNANCE_ROLE,
        "Architecture governance",
        "Owns cross-system modeling and substitution conformance. "
        "This is a governance role, not a fifth independently realizable system.",
    )
    ontologies = [
        (
            "domain",
            "Domain · Meaning",
            (
                "Defines concepts, behavior, relationships and invariants independently "
                "of systems and technology."
            ),
        ),
        (
            "systems",
            "Systems · Responsibility",
            (
                "Assigns responsibilities and behavioral contracts independently of "
                "implementation mechanisms."
            ),
        ),
        (
            "realization",
            "Realization · Mechanism",
            ("Describes boundaries, capabilities and bindings without redefining system identity."),
        ),
    ]
    for identity, name, description in ontologies:
        b.node(identity, Kind.ONTOLOGY, name, description)
    b.edge("constrains", "domain", "systems")
    b.edge("constrains", "systems", "realization")
    domain = [
        ("experience", "Experience", "An evolving state influenced by inputs and time."),
        (
            "representation",
            "Representation",
            "Information describing some aspect of an experience.",
        ),
        (
            "production",
            "Production",
            (
                "A process consuming and producing representations; it may be a graph, "
                "not a linear pipeline."
            ),
        ),
        ("presentation", "Presentation", "The perceptible result of production."),
        ("objective", "Objective", "A desired change to an experience."),
        (
            "intervention",
            "Intervention",
            "A controlled modification to representation or production.",
        ),
        (
            "counterfactual",
            "Counterfactual",
            ("An alternative outcome originating from equivalent controlled conditions."),
        ),
        (
            "evidence",
            "Evidence",
            "Observations with provenance supporting an inference or evaluation.",
        ),
        ("policy", "Policy", "A reusable rule governing interventions."),
    ]
    for identity, name, description in domain:
        b.node(identity, Kind.CONCEPT, name, description)
        b.edge("includes", "domain", identity)
    for relation, source, target in [
        ("expressed_as", "experience", "representation"),
        ("consumes", "production", "representation"),
        ("yields", "production", "representation"),
        ("yields", "production", "presentation"),
        ("informs", "objective", "intervention"),
        ("modifies", "intervention", "production"),
        ("modifies", "intervention", "representation"),
        ("yields", "counterfactual", "evidence"),
        ("informs", "evidence", "policy"),
        ("informs", "objective", "policy"),
        ("selects", "policy", "intervention"),
    ]:
        b.edge(relation, source, target)
    invariants = [
        (
            "D1",
            "Causal correspondence",
            "Controlled alternatives share identifiable originating conditions.",
        ),
        ("D2", "Provenance", "Evidence identifies its source and observation boundary."),
        (
            "D3",
            "Preservation",
            "Interventions preserve properties not authorized for modification.",
        ),
        (
            "D4",
            "Presentation protection",
            (
                "No prohibited presentation is allowed in covered production scenarios "
                "when strict prevention is promised. Research capture of an original "
                "variant is distinct from protected production presentation."
            ),
        ),
        (
            "D5",
            "Performance",
            "Runtime execution satisfies its declared latency and throughput budget.",
        ),
        (
            "D6",
            "Reproducibility",
            "Experimental outcomes can be reproduced within declared tolerances.",
        ),
        (
            "D7",
            "Semantic stability",
            ("Representation and implementation changes do not silently redefine objectives."),
        ),
    ]
    for identity, name, description in invariants:
        b.node(
            identity,
            Kind.INVARIANT,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("includes", "domain", identity)
    for invariant, concepts in {
        "D1": ["counterfactual"],
        "D2": ["evidence"],
        "D3": ["intervention", "objective"],
        "D4": ["presentation"],
        "D5": ["production"],
        "D6": ["counterfactual"],
        "D7": ["objective"],
    }.items():
        for concept in concepts:
            b.edge(Relation.CONSTRAINS_CONCEPT, invariant, concept)
    systems = [
        (
            "S1",
            "Counterfactual Experimentation",
            ("Generate comparable experiences and capture their native representations."),
            "Attributable counterfactual evidence",
            ["experience", "representation", "counterfactual", "evidence"],
            [
                "Reproduce or align equivalent originating states.",
                "Apply declared differences between variants.",
                "Capture available representations at specified observation boundaries.",
                "Preserve native representation data and necessary references.",
                "Record correspondence and provenance.",
                "Make experimental outcomes independently verifiable.",
                (
                    "Parallel rendering branches and sequential deterministic replay are "
                    "alternatives, not mandatory mechanisms."
                ),
                (
                    "Boundary: produces evidence; does not own interpretation, policy "
                    "learning or runtime execution."
                ),
            ],
        ),
        (
            "S2",
            "Transformation Synthesis",
            ("Turn objectives and experimental evidence into reusable, validated interventions."),
            "Policies with applicability and validation evidence",
            ["objective", "evidence", "intervention", "policy"],
            [
                "Consume evidence without assuming a particular engine or graphics API.",
                "Identify or synthesize candidate transformations.",
                "Evaluate desired effects, preservation and cost.",
                "Describe capabilities needed to execute a candidate.",
                ("Publish versioned policies with explicit applicability and validation evidence."),
                (
                    "Deterministic analysis, statistical learning, neural models and search "
                    "are replaceable synthesis methods."
                ),
                (
                    "Boundary: produces intervention knowledge; does not own environmental "
                    "execution."
                ),
            ],
        ),
        (
            "S3",
            "Presentation Mediation",
            (
                "Apply policies within supported production environments without "
                "violating constraints."
            ),
            "Modified presentation within declared constraints",
            ["policy", "intervention", "presentation", "evidence"],
            [
                (
                    "Identify target capabilities and determine whether a policy can be "
                    "validly executed."
                ),
                ("Prepare transformations before the critical rendering path whenever possible."),
                "Execute through the cheapest suitable interaction boundary.",
                "Enforce required presentation and performance constraints.",
                "Report unsupported policies rather than claiming weaker guarantees.",
                "Expose execution evidence for evaluation and feedback.",
                (
                    "Boundary: executes interventions; does not own user objectives or policy "
                    "learning."
                ),
            ],
        ),
        (
            "S4",
            "Preference Management",
            ("Express desired changes and collect feedback independently of execution mechanisms."),
            "Technology-independent objectives",
            ["objective", "experience", "presentation"],
            [
                (
                    "Allow users to identify an undesirable experience or region and express "
                    "the intended outcome."
                ),
                "Associate preferences with scope.",
                "Record corrections and observed failures.",
                "Request activation of compatible policies.",
                (
                    "Users need not understand shaders, graphics APIs, rendering buffers or "
                    "model architectures."
                ),
            ],
        ),
    ]
    for identity, name, responsibility, contract, concepts, statements in systems:
        execution_context = {
            "S1": "Research / capture",
            "S2": "Offline synthesis",
            "S3": "Production runtime",
            "S4": "User intent and feedback",
        }[identity]
        b.node(
            identity,
            Kind.SYSTEM,
            f"{identity} · {name} · {execution_context}",
            execution_context,
        )
        b.edge("includes", "systems", identity)
        b.node(
            f"{identity}-responsibility",
            Kind.RESPONSIBILITY,
            f"{name} responsibility",
            responsibility,
        )
        b.node(
            f"{identity}-contract",
            Kind.CONTRACT,
            f"{identity} · Behavioral contract",
            contract,
            ScenarioScope.REFERENCE,
            statements,
        )
        b.edge("owns", identity, f"{identity}-responsibility")
        b.edge("specified_by", f"{identity}-responsibility", f"{identity}-contract")
        for concept in concepts:
            b.edge("concerns", f"{identity}-responsibility", concept)
            b.edge("defined_in_terms_of", f"{identity}-contract", concept)
            b.edge("uses_concept", identity, concept)
        for invariant, _, _ in invariants:
            b.edge("must_preserve", f"{identity}-contract", invariant)
    scoped = [
        (
            "scenario-concept",
            "Scenario",
            "Initial conditions, inputs, time and environment.",
            "S1",
            None,
        ),
        ("variant", "Variant", "A controlled alternative to a scenario.", "S1", None),
        (
            "observation",
            "Observation",
            "Information captured at a specified boundary.",
            "S1",
            None,
        ),
        (
            "correspondence",
            "Correspondence",
            "Relationship between comparable states or observations.",
            "S1",
            None,
        ),
        (
            "experiment",
            "Experiment",
            "Collection of variants under controlled conditions.",
            "S1",
            None,
        ),
        (
            "counterfactual-evidence",
            "Counterfactual Evidence",
            "Evidence attributed to observations and outcomes from an experiment.",
            "S1",
            "evidence",
        ),
        (
            "training-case",
            "Training Case",
            "Evidence associated with an objective.",
            "S2",
            "evidence",
        ),
        (
            "candidate-intervention",
            "Candidate Intervention",
            "A proposed intervention whose validity is not yet established.",
            "S2",
            "intervention",
        ),
        (
            "evaluation",
            "Evaluation",
            "Evidence evaluating whether a proposal satisfies defined properties.",
            "S2",
            "evidence",
        ),
        ("applicability", "Applicability", "Conditions under which a policy is valid.", "S2", None),
        (
            "presentation-target",
            "Presentation Target",
            "Environment or context whose output is mediated.",
            "S3",
            None,
        ),
        (
            "policy-binding",
            "Policy Binding",
            (
                "Association between a policy and supported target capabilities; distinct "
                "from an architectural realization Binding."
            ),
            "S3",
            None,
        ),
        ("installation", "Installation", "A prepared executable transformation.", "S3", None),
        ("execution", "Execution", "Application of an intervention.", "S3", "intervention"),
        (
            "execution-outcome",
            "Execution Outcome",
            "Result and evidence of policy execution.",
            "S3",
            "evidence",
        ),
        ("preference", "Preference", "Desired behavior expressed by a user.", "S4", None),
        ("scope", "Scope", "Where a preference applies.", "S4", None),
        ("selection", "Selection", "User-identified content or experience.", "S4", None),
        (
            "desired-outcome",
            "Desired Outcome",
            "Requested replacement, suppression or modification.",
            "S4",
            "objective",
        ),
        ("feedback", "Feedback", "Confirmation or correction of behavior.", "S4", "evidence"),
        ("profile", "Profile", "Collection of active preferences.", "S4", None),
    ]
    for identity, name, description, system, parent in scoped:
        b.node(identity, Kind.LOCAL_CONCEPT, name, description)
        b.edge("uses_concept", system, identity)
        if parent:
            b.edge("specializes", identity, parent)
    realization = [
        (
            "environment-concept",
            "Environment",
            "Computing environment responsible for producing an experience.",
        ),
        (
            "boundary-concept",
            "Interaction Boundary",
            "Point where information can be observed or controlled.",
        ),
        ("capability-concept", "Capability", "Available observation or modification operation."),
        (
            "layer-concept",
            "Abstraction Layer",
            (
                "Classification of a boundary by available information and operations; "
                "not a mandatory pipeline stage."
            ),
        ),
        (
            "binding-concept",
            "Binding",
            (
                "Implementation mechanism attempting to satisfy a system contract through "
                "sufficient capabilities."
            ),
        ),
    ]
    for identity, name, description in realization:
        b.node(identity, Kind.REALIZATION_CONCEPT, name, description)
        b.edge("includes", "realization", identity)
    b.edge("uses_concept", "S3", "capability-concept")
    exchanges = [
        (
            "C1",
            "Transformation Objective",
            "Portable meaning of the requested change.",
            ["objective"],
            ["S4"],
            ["S2", "S3"],
            [
                "Target concept or behavior; desired outcome; applicability scope.",
                ("Preservation requirements; performance constraints; protection requirements."),
            ],
        ),
        (
            "C2",
            "Counterfactual Evidence",
            "Causally aligned native observations and outcomes.",
            ["evidence", "counterfactual", "representation"],
            ["S1"],
            ["S2"],
            [
                ("Shared originating conditions; controlled variants; declared interventions."),
                (
                    "Observation boundaries; native representation references; correspondence "
                    "and provenance; observed outcomes."
                ),
                (
                    "Observation boundaries identify the stage and interpretation of "
                    "referenced data."
                ),
                (
                    "Commands must include or reference required resource and execution state "
                    "for supported analysis or replay."
                ),
            ],
        ),
        (
            "C3",
            "Transformation Policy",
            ("Portable intent and validity; executable realizations may be platform-specific."),
            ["policy", "objective"],
            ["S2"],
            ["S3"],
            [
                "Policy identity and version; objective; applicability conditions.",
                "Required capabilities; executable realizations; evaluation evidence.",
                "Preservation and performance constraints.",
            ],
        ),
        (
            "C4",
            "Execution Outcome",
            "Execution observations, supported status and attributable failures.",
            ["evidence", "presentation", "policy"],
            ["S3"],
            ["S1", "S2", "S4"],
            [
                (
                    "Executed policy and target; supported or unsupported status; observed "
                    "modification."
                ),
                (
                    "Preservation results; frame-time and latency measurements; failures and "
                    "unsupported capabilities."
                ),
            ],
        ),
        (
            "C5",
            "Capability Description",
            "Discoverable capabilities, not assumptions based on a technology name.",
            ["capability-concept", "boundary-concept"],
            [],
            ["S1", "S2", "S3", "S4"],
            [
                ("Available observation and control boundaries; supported abstraction layers."),
                (
                    "Representation formats; execution constraints; timing or presentation "
                    "guarantees."
                ),
            ],
        ),
    ]
    for identity, name, description, concepts, producers, consumers, statements in exchanges:
        b.node(
            identity,
            Kind.EXCHANGE,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
            statements,
        )
        for concept in concepts:
            b.edge("defined_in_terms_of", identity, concept)
        for producer in producers:
            b.edge("produces", producer, identity)
        for consumer in consumers:
            b.edge("consumed_by", identity, consumer)
        for system in sorted(set(producers + consumers)):
            b.edge("exchanges", f"{system}-contract", identity)
    add_realizations(b)
    add_requirements(b)
    add_reference(b)
    add_acceptance(b)
    add_delivery(b)
    add_governance(b)
    add_independence(b)
    return b.schema(), b.nodes, b.edges


def add_realizations(b: Builder) -> None:
    layers = [
        (
            "L1",
            "State / Semantics",
            (
                "Entities, behavior and events; candidate boundaries include engine state "
                "and application models."
            ),
        ),
        (
            "L2",
            "Presentation Description",
            (
                "Layout, geometry, materials and visual properties; candidate boundaries "
                "include scene graphs and UI layout."
            ),
        ),
        (
            "L3",
            "Rendering Operations",
            (
                "Draw commands, shaders, resources and buffers; candidate boundaries "
                "include Vulkan, Direct3D and rendering backends."
            ),
        ),
        (
            "L4",
            "Composed Representation",
            (
                "Completed surfaces and pixels; candidate boundaries include compositors "
                "and frame buffers."
            ),
        ),
        (
            "L5",
            "Physical Presentation",
            (
                "Scanout, hardware composition and timing; candidate boundaries include "
                "DRM/KMS and display controllers."
            ),
        ),
    ]
    for identity, name, description in layers:
        b.node(identity, Kind.LAYER, f"{identity} · {name}", description)
    b.node(
        "linux-godot",
        Kind.ENVIRONMENT,
        "Controlled Linux / Godot environment",
        (
            "Proposed Godot 4 scene on a Linux desktop with a Vulkan-capable GPU and "
            "120 Hz presentation target. Exact hardware, driver, workload and "
            "tolerances must be pinned before acceptance measurements."
        ),
        ScenarioScope.REFERENCE,
    )
    boundaries = [
        (
            "engine-boundary",
            "Engine state and scene boundary",
            ("Proposed control of scenario state, events, camera, materials and effects."),
            ["L1", "L2"],
        ),
        (
            "graphics-boundary",
            "Vulkan operation/resource boundary",
            (
                "Proposed capture and intervention boundary. Specificity, resource "
                "completeness and timing support require evidence."
            ),
            ["L3"],
        ),
        (
            "analysis-boundary",
            "Offline native-evidence analysis boundary",
            (
                "Reads explicitly typed native representations and their interpretation "
                "metadata; no universal intermediate representation is required."
            ),
            [],
        ),
        (
            "preference-boundary",
            "Local preference interaction boundary",
            (
                "Proposed user selection, objective and correction interface. User "
                "meaning remains independent of graphics representation."
            ),
            ["L1", "L2"],
        ),
        (
            "composition-boundary",
            "Compositor boundary",
            (
                "Replaceable candidate observing composed pixels; semantic identity and "
                "pre-exposure guarantees must not be assumed."
            ),
            ["L4"],
        ),
    ]
    for identity, name, description, layer_ids in boundaries:
        b.node(identity, Kind.BOUNDARY, name, description, ScenarioScope.REFERENCE)
        for layer in layer_ids:
            b.edge("classified_by", identity, layer)
    # The environment is proposed, so its declared boundary structure is not measured availability.
    for boundary in ("engine-boundary", "graphics-boundary"):
        b.edge("exposes", "linux-godot", boundary)
    capabilities = [
        (
            "replay-capability",
            "Controlled state and replay",
            (
                "Reproduce or align simulation states, inputs, logical time, event "
                "identity and camera within declared tolerances."
            ),
        ),
        (
            "capture-capability",
            "Native capture with resource closure",
            (
                "Capture commands, resources, shaders and relevant execution state at "
                "identified boundaries, retaining necessary references."
            ),
        ),
        (
            "correspondence-capability",
            "Causal correspondence",
            (
                "Relate operations and observations to shared originating conditions and "
                "controlled differences."
            ),
        ),
        (
            "analysis-capability",
            "Native transformation analysis",
            (
                "Interpret native evidence sufficiently to derive candidate changes and "
                "validate their applicability."
            ),
        ),
        (
            "targeting-capability",
            "Specific effect targeting",
            (
                "Identify the intended semantic target through available observations "
                "with enough specificity to preserve unrelated content."
            ),
        ),
        (
            "substitution-capability",
            "Prepared intervention",
            (
                "Prepare and apply an authorized intervention at a supported boundary "
                "while preserving the applicable contract and invariants."
            ),
        ),
        (
            "protection-capability",
            "Covered pre-exposure protection",
            (
                "Prevent prohibited production presentation in covered scenarios, or "
                "report unsupported unless an explicit conservative mode is authorized."
            ),
        ),
        (
            "measurement-capability",
            "Separated timing and outcome measurement",
            (
                "Measure presentation, GPU execution, CPU submission, input-to-display "
                "latency and preservation without confusing offline capture cost with "
                "runtime cost."
            ),
        ),
        (
            "preference-capability",
            "Selection and correction",
            (
                "Associate a selected region with its observation, express an outcome and "
                "scope, request activation and record corrections."
            ),
        ),
    ]
    for identity, name, description in capabilities:
        b.node(identity, Kind.CAPABILITY, name, description, ScenarioScope.REFERENCE)
    bindings = [
        (
            "B1",
            "S1 · Controlled experiment binding",
            "S1",
            ["engine-boundary", "graphics-boundary"],
            ["replay-capability", "capture-capability", "correspondence-capability"],
            (
                "Godot simulation with Vulkan capture/replay is proposed. Unreal, custom "
                "simulation and browser automation are alternatives only where sufficient "
                "capabilities are demonstrated."
            ),
        ),
        (
            "B2",
            "S2 · Offline synthesis binding",
            "S2",
            ["analysis-boundary"],
            ["analysis-capability", "measurement-capability"],
            (
                "Initial deterministic analysis may derive changed resource/shader "
                "relationships from paired records; learned synthesis, program synthesis "
                "and rule inference may fulfill the same contract."
            ),
        ),
        (
            "B3",
            "S3 · Graphics intervention binding",
            "S3",
            ["graphics-boundary"],
            [
                "targeting-capability",
                "substitution-capability",
                "protection-capability",
                "measurement-capability",
            ],
            (
                "Proposed Vulkan interception and resource/shader substitution. Engine "
                "integration, other graphics APIs and compositor integration require "
                "separate conformance evaluation."
            ),
        ),
        (
            "B4",
            "S4 · Local preference binding",
            "S4",
            ["preference-boundary"],
            ["preference-capability"],
            (
                "Proposed local preference UI with region selection; desktop overlays, "
                "mobile applications and other UIs may implement the same responsibility."
            ),
        ),
    ]
    for identity, name, system, boundary_ids, capability_ids, description in bindings:
        b.node(
            identity,
            Kind.BINDING,
            name,
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("attempts_to_fulfill", identity, f"{system}-contract")
        b.edge("produces", identity, "C5")
        for boundary in boundary_ids:
            b.edge("uses_boundary", identity, boundary)
        for capability in capability_ids:
            b.edge("requires_capability", identity, capability)
            b.edge("requires_capability", f"{system}-contract", capability)
        for invariant in ("D1", "D2", "D3", "D4", "D5", "D6", "D7"):
            b.edge("must_preserve", identity, invariant)
    technologies = [
        ("godot", "Godot", "Reuse interactive simulation; do not build a rendering engine.", "B1"),
        (
            "vulkan",
            "Vulkan",
            (
                "Reuse graphics API; suitability depends on observed capabilities, not "
                "the technology name."
            ),
            "graphics-boundary",
        ),
        (
            "gfxreconstruct",
            "GFXReconstruct",
            (
                "Candidate graphics capture/replay tooling; verify capture completeness "
                "and replay support for the selected scene."
            ),
            "B1",
        ),
        (
            "renderdoc",
            "RenderDoc",
            (
                "Candidate rendering inspection and pixel provenance diagnostics; "
                "inspection is separate from production runtime."
            ),
            "B1",
        ),
        (
            "spirv",
            "Existing Vulkan / SPIR-V tooling",
            ("Reuse shader compilation and inspection tooling; no custom compiler is required."),
            "B3",
        ),
        (
            "driver",
            "Mesa or supported vendor driver",
            (
                "Reuse an existing Linux graphics driver; shader replacement mechanisms "
                "are candidates where sufficient."
            ),
            "B3",
        ),
        (
            "interception",
            "Existing graphics interception mechanisms",
            (
                "Extend only where capabilities are insufficient; never circumvent "
                "protected content or anti-cheat."
            ),
            "B3",
        ),
        (
            "learning-infrastructure",
            "Existing analysis and learning infrastructure",
            (
                "Prefer reuse for model architecture and training where compatible with "
                "native evidence and contracts."
            ),
            "B2",
        ),
    ]
    for identity, name, description, target in technologies:
        b.node(identity, Kind.TECHNOLOGY, name, description, ScenarioScope.REFERENCE)
        b.edge("candidate_for", identity, target)


def add_requirements(b: Builder) -> None:
    product = [
        (
            "P1",
            "Paired comparable observations",
            "Produce paired observations of equivalent experiences.",
            "S1",
        ),
        (
            "P2",
            "Native pre-presentation evidence",
            "Capture native pre-presentation representations, not only images.",
            "S1",
        ),
        (
            "P3",
            "Reusable learned transformations",
            "Derive reusable transformation policies from paired evidence.",
            "S2",
        ),
        (
            "P4",
            "Single runtime production path",
            "Execute a policy without rendering the entire experience twice.",
            "S3",
        ),
        (
            "P5",
            "Real-time performance",
            "Preserve performance of real-time applications within declared budgets.",
            "S3",
        ),
        (
            "P6",
            "Technology-independent meaning",
            "Keep domain and system ontologies independent of technology.",
            "architecture",
        ),
        (
            "P7",
            "User-defined transformation",
            "Allow users to define and correct desired transformations.",
            "S4",
        ),
        (
            "P8",
            "Replaceable bindings",
            ("Support different environment bindings without redefining system contracts."),
            "architecture",
        ),
        (
            "P9",
            "Broader applications and mobile",
            (
                "Extend to arbitrary applications and mobile operating systems without "
                "assuming equivalent capabilities."
            ),
            "architecture",
        ),
    ]
    functions = [
        (
            "F01",
            "Formal architectural definitions",
            "Define and validate the three architectural ontologies.",
            "architecture",
            "P6",
        ),
        (
            "F02",
            "Replayable scenarios",
            "Record deterministic, replayable scenario states and inputs.",
            "S1",
            "P1",
        ),
        (
            "F03",
            "Controlled alternatives",
            "Generate original and transformed variants.",
            "S1",
            "P1",
        ),
        (
            "F04",
            "Native capture",
            "Capture pre-presentation representations with provenance.",
            "S1",
            "P2",
        ),
        (
            "F05",
            "Aligned counterfactual evidence",
            "Assemble causally aligned counterfactual evidence.",
            "S1",
            "P1",
        ),
        (
            "F06",
            "Candidate policy derivation",
            "Derive and evaluate candidate transformation policies.",
            "S2",
            "P3",
        ),
        (
            "F07",
            "Scoped policy publication",
            "Publish policies with capability and applicability requirements.",
            "S2",
            "P3",
        ),
        (
            "F08",
            "Capability discovery",
            "Discover environmental observation/control capabilities.",
            "S3",
            "P8",
        ),
        (
            "F09",
            "Prepared compatible transformation",
            "Prepare and install compatible transformations.",
            "S3",
            "P4",
        ),
        (
            "F10",
            "Production-boundary execution",
            "Apply transformations through supported production boundaries.",
            "S3",
            "P4",
        ),
        (
            "F11",
            "Runtime measurements",
            "Measure runtime presentation and performance behavior.",
            "S3",
            "P5",
        ),
        (
            "F12",
            "Preference interaction",
            "Capture selections, objectives and corrections.",
            "S4",
            "P7",
        ),
        (
            "F13",
            "Honest unsupported states",
            "Reject unsupported bindings without silently weakening guarantees.",
            "S3",
            "P8",
        ),
        (
            "F14",
            "Independent substitution",
            (
                "Demonstrate a second independently implemented binding for relevant "
                "contract conformance."
            ),
            "architecture",
            "P8",
        ),
    ]
    for identity, name, description, owner in product:
        b.node(
            identity,
            Kind.REQUIREMENT,
            f"{identity} · {name}",
            description,
            ScenarioScope.FUTURE if identity == "P9" else ScenarioScope.REFERENCE,
        )
        b.edge("applies_to", identity, owner)
    for identity, name, description, owner, product_id in functions:
        b.node(
            identity,
            Kind.REQUIREMENT,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("applies_to", identity, owner)
        b.edge("supports", identity, product_id)
    for requirement, invariant in [
        ("P5", "D5"),
        ("P6", "D7"),
        ("F02", "D6"),
        ("F04", "D2"),
        ("F05", "D1"),
        ("F13", "D4"),
    ]:
        b.edge("governed_by", requirement, invariant)


def add_reference(b: Builder) -> None:
    b.node(
        "reference-scene",
        Kind.SCENARIO,
        "Reference · Blood becomes glitter",
        (
            "A controlled Godot 4 scene on Linux with Vulkan-backed rendering and a "
            "120 Hz presentation target. One authoritative simulation establishes "
            "equivalent originating conditions. Original and modified variants may be "
            "produced by branches or deterministic replay; equivalence must be "
            "verified."
        ),
        ScenarioScope.REFERENCE,
        [
            (
                "Original: scripted action produces blood; native rendering state and "
                "output are recorded for evaluation."
            ),
            (
                "Modified: equivalent state, inputs, timing and camera produce glitter; "
                "capture occurs at the same logical boundary."
            ),
            (
                "Preserve logical time, event identity, shaders/resources/state, known "
                "intervention, correspondence and presentation outcomes."
            ),
            (
                "Images verify results; upstream native representations are the "
                "training/analysis evidence."
            ),
        ],
    )
    b.node(
        "blood-glitter-objective",
        Kind.OBJECTIVE,
        "Replace blood with glitter",
        "Change visible blood into glitter in the supported reference experience while "
        "preserving unrelated scene properties and the declared protection and "
        "performance constraints.",
        ScenarioScope.REFERENCE,
    )
    flows = [
        (
            "experiment-step",
            "1 · Capture controlled alternatives",
            "S1",
            (
                "Scenario → controlled variants → observations → attributed "
                "counterfactual evidence. Capture native payload and resource closure; "
                "verify originating-state equivalence and presentation correspondence."
            ),
        ),
        (
            "synthesis-step",
            "2 · Derive and evaluate policy",
            "S2",
            (
                "Objective and paired evidence produce a candidate intervention. "
                "Initially deterministic analysis may derive the changed shader/resource "
                "relationship. Validate by replay or equivalent controlled execution "
                "before publication."
            ),
        ),
        (
            "runtime-step",
            "Production · Execute in the normal path",
            "S3",
            (
                "Launch the reference game in its original configuration. Discover "
                "compatible capabilities, prepare the policy, and substitute matching "
                "operations/resources so covered runtime presentation is modified."
            ),
        ),
        (
            "feedback-step",
            "Feedback · Inspect execution and correct",
            "S4",
            (
                "User inspects the observed execution outcome and gives corrections "
                "if behavior is wrong."
            ),
        ),
    ]
    for identity, name, system, description in flows:
        b.node(identity, Kind.STEP, name, description, ScenarioScope.REFERENCE)
        b.edge("contains_step", "reference-scene", identity)
        b.edge("performed_by", identity, system)
    b.node(
        "preference-step",
        Kind.STEP,
        "User expression · Select and request",
        (
            "Select or circle unwanted content on a captured frame; specify glitter "
            "or suppression; associate the selection with its observation and scope; "
            "submit an objective. The interface need not interpret native rendering "
            "payloads."
        ),
        ScenarioScope.REFERENCE,
    )
    b.edge("contains_step", "reference-scene", "preference-step")
    b.edge("performed_by", "preference-step", "S4")
    b.node(
        "activation-step",
        Kind.STEP,
        "Activation · Review and enable policy",
        "Inspect the evaluated policy and its applicability, then request activation "
        "before runtime execution.",
        ScenarioScope.REFERENCE,
    )
    b.edge("contains_step", "reference-scene", "activation-step")
    b.edge("performed_by", "activation-step", "S4")
    for source, target in [
        ("experiment-step", "synthesis-step"),
        ("preference-step", "synthesis-step"),
        ("synthesis-step", "activation-step"),
        ("activation-step", "runtime-step"),
        ("runtime-step", "feedback-step"),
    ]:
        b.edge("next", source, target)
    b.node(
        "runtime-restrictions",
        Kind.GOVERNANCE,
        "Reference runtime restrictions",
        (
            "These restrictions apply to the known reference transformation, not "
            "every future policy type."
        ),
        ScenarioScope.REFERENCE,
        [
            "No two concurrent full renderings in production.",
            "No mandatory CPU screenshot round trip.",
            (
                "No full-frame neural classification on every frame for the known "
                "resource substitution."
            ),
            "No continuous training or experimental capture in production runtime.",
        ],
    )
    b.node(
        "phone-feed",
        Kind.SCENARIO,
        "Future experiment · Simulated phone feed",
        (
            "Generate equivalent scrolling-feed states with advertisements present "
            "and absent or replaced. Capture available semantic, "
            "presentation-description and graphics representations. Test whether "
            "shared contracts remain unchanged; this is planned cross-domain "
            "validation, not demonstrated portability."
        ),
        ScenarioScope.FUTURE,
    )


def add_acceptance(b: Builder) -> None:
    criteria = [
        (
            "A01",
            "Additional p99 critical-path cost",
            (
                "At most 0.5 ms additional p99 critical-path frame cost on declared "
                "reference hardware and scene. Measure the combined transformed workload "
                "directly; baseline p99 plus overhead p99 does not prove transformed p99."
            ),
            "D5",
        ),
        (
            "A02",
            "Sustained 120 FPS",
            (
                "At least 120 FPS when the fixed baseline workload has sufficient "
                "headroom. 120 FPS corresponds to approximately 8.33 ms per frame; no "
                "universal performance guarantee is implied."
            ),
            "D5",
        ),
        (
            "A03",
            "Baseline headroom",
            (
                "Use a fixed workload with baseline p99 frame time no greater than 7.8 "
                "ms. This is workload qualification, not proof that adding the 0.5 ms "
                "target preserves all frame deadlines."
            ),
            "D5",
        ),
        (
            "A04",
            "Zero added queued frames",
            (
                "No additional queued frames from runtime transformation; measure "
                "input-to-display latency separately."
            ),
            "D5",
        ),
        (
            "A05",
            "Off-path preparation",
            ("Prepare runtime policies outside the frame-critical path."),
            "D5",
        ),
        (
            "A06",
            "No required full-frame model",
            (
                "Full-frame model execution is not required for the known "
                "resource-substitution policy."
            ),
            "D5",
        ),
        (
            "A07",
            "Zero prohibited presented occurrences",
            (
                "Zero strictly prohibited presented occurrences in covered production "
                "scenarios. If pre-exposure prevention cannot be guaranteed, report "
                "unsupported or use an explicitly authorized conservative mode."
            ),
            "D4",
        ),
        (
            "A08",
            "Zero unauthorized negative-case changes",
            (
                "Zero unauthorized changes in controlled negative cases. Shared-resource "
                "effects require specific targeting."
            ),
            "D3",
        ),
        (
            "A09",
            "Valid scope",
            (
                "The policy applies only within evaluated applicability conditions and "
                "produces the specified change."
            ),
            "D7",
        ),
        (
            "A10",
            "Independent evidence",
            (
                "Captured paired evidence includes attributable originating conditions, "
                "representations and observed outcomes that can be independently "
                "verified."
            ),
            "D1",
        ),
        (
            "A11",
            "Reproducible experiment",
            "Experimental outcomes reproduce within explicitly declared tolerances.",
            "D6",
        ),
        (
            "A12",
            "Independent realization substitution",
            (
                "At least two independently implemented bindings demonstrate the same "
                "relevant contract and invariant obligations without redefining meaning."
            ),
            "D7",
        ),
    ]
    for identity, name, description, invariant in criteria:
        b.node(
            identity,
            Kind.CRITERION,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("applies_to", identity, "reference-scene")
        owner = (
            "S1" if identity in {"A10", "A11"} else "architecture" if identity == "A12" else "B3"
        )
        b.edge("applies_to", identity, owner)
        if identity in {"A01", "A02", "A07", "A08", "A09"}:
            b.edge("applies_to", identity, "blood-glitter-objective")
        b.edge("governed_by", identity, invariant)
    b.node(
        "measurement-protocol",
        Kind.GOVERNANCE,
        "Measurement protocol",
        (
            "Acceptance targets require recorded measurement evidence. Verification "
            "state comes from assessments, not authored status labels."
        ),
        ScenarioScope.REFERENCE,
        [
            "Pin reference hardware, driver, scene, workload and declared tolerances.",
            (
                "Disable capture, tracing and offline analysis during production "
                "performance measurements."
            ),
            (
                "Measure frame presentation, GPU execution, CPU submission and "
                "input-to-display latency separately."
            ),
            (
                "Record paired baseline and transformed workload results, including "
                "distributions and negative cases."
            ),
            (
                "A known material replacement may require little recurring computation; "
                "an unseen semantic category may not."
            ),
        ],
    )
    failures = [
        (
            "T01",
            "Shared resource",
            (
                "Target effect shares a resource with desirable content; reject unsafe "
                "broad replacement."
            ),
            "S3",
        ),
        (
            "T02",
            "Shader identity changes",
            (
                "Application update changes shader identity; do not silently reuse an "
                "invalid policy."
            ),
            "S3",
        ),
        (
            "T03",
            "Unavailable capability",
            ("Policy references an unavailable capability; explicitly report unsupported."),
            "S3",
        ),
        (
            "T04",
            "Dynamic resource recreation",
            (
                "Resources are dynamically recreated; target tracking and installation "
                "must remain valid or fail observably."
            ),
            "S3",
        ),
        (
            "T05",
            "Unsupported graphics API",
            "Target uses an unsupported graphics API; do not claim compatibility.",
            "S3",
        ),
        (
            "T06",
            "Unrelated changes",
            (
                "Candidate changes unrelated objects; evaluation must reject unauthorized "
                "modification."
            ),
            "S2",
        ),
        (
            "T07",
            "Budget exceeded",
            ("Intervention exceeds frame-time budget; report failed performance conformance."),
            "S3",
        ),
        (
            "T08",
            "Protected rendering path",
            (
                "Protected or inaccessible rendering prevents observation; report "
                "limitation without circumvention."
            ),
            "S1",
        ),
    ]
    for identity, name, description, system in failures:
        b.node(
            identity,
            Kind.FAILURE,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("applies_to", identity, system)
    final = [
        (
            "E1",
            "Experimentation acceptance",
            (
                "Controlled equivalent experiences yield alternative native renderings "
                "with preserved causal correspondence."
            ),
            "S1",
        ),
        (
            "E2",
            "Synthesis acceptance",
            (
                "A policy is derived from evidence, evaluated against the objective, and "
                "published with applicability and capability requirements."
            ),
            "S2",
        ),
        (
            "E3",
            "Execution acceptance",
            (
                "A supported binding modifies normal production behavior without "
                "continuous full-frame classification for the reference policy."
            ),
            "S3",
        ),
        (
            "E4",
            "Interaction acceptance",
            (
                "A user expresses or corrects the transformation without knowing graphics "
                "implementation details."
            ),
            "S4",
        ),
        (
            "E5",
            "Substitution acceptance",
            (
                "Two realization bindings demonstrate compliance with the same relevant "
                "domain meanings and system contracts."
            ),
            "architecture",
        ),
        (
            "E6",
            "Performance acceptance",
            (
                "The modified reference workload meets declared 120 FPS frame-time, "
                "presentation-latency and correctness requirements."
            ),
            "S3",
        ),
    ]
    for identity, name, description, owner in final:
        b.node(
            identity,
            Kind.CRITERION,
            f"{identity} · {name}",
            description,
            ScenarioScope.REFERENCE,
        )
        b.edge("applies_to", identity, owner)


def add_delivery(b: Builder) -> None:
    phases = [
        (
            "phase-1",
            "1 · Architectural foundation",
            (
                "Exit: replace a system implementation without changing conceptual "
                "responsibility or contract semantics."
            ),
            [
                "Versioned domain ontology and system contracts.",
                "Realization ontology, capabilities and binding validity rules.",
                "Contract conformance tests; minimum evidence and policy definitions.",
            ],
            ["F01"],
            ["A12"],
        ),
        (
            "phase-2",
            "2 · Counterfactual experimentation",
            (
                "Exit: S1 produces comparable causally attributed representations and "
                "verifies their presentations."
            ),
            [
                "Controlled game scene and reproducible inputs/state.",
                "Original and transformed variants with native capture.",
                "Paired correspondence evidence; replay and verification procedure.",
            ],
            ["F02", "F03", "F04", "F05"],
            ["A10", "A11", "E1"],
        ),
        (
            "phase-3",
            "3 · Policy synthesis",
            (
                "Exit: S2 derives an executable policy from evidence and its observed "
                "effect is independently verified."
            ),
            [
                "Evidence consumption and replaceable synthesis.",
                "Candidate generation and controlled evaluation using S1.",
                "Versioned policy artifacts with validation evidence.",
            ],
            ["F06", "F07"],
            ["E2", "A09"],
        ),
        (
            "phase-4",
            "4 · Runtime mediation",
            (
                "Exit: the reference game in its original configuration presents the "
                "transformed effect while satisfying correctness and performance targets."
            ),
            [
                "Capability discovery; preparation and installation.",
                "Shader/resource-level intervention in a single normal production path.",
                "Performance instrumentation and negative tests.",
            ],
            ["F08", "F09", "F10", "F11", "F13"],
            ["E3", "E6", "A01", "A02", "A07", "A08"],
        ),
        (
            "phase-5",
            "5 · Preference interaction",
            (
                "Exit: a user identifies unwanted content, requests its replacement and "
                "experiences the evaluated transformation without manually editing "
                "graphics resources."
            ),
            [
                "Region selection and objective specification.",
                "Policy association and activation.",
                "Correction and feedback flow.",
            ],
            ["F12"],
            ["E4"],
        ),
        (
            "phase-6",
            "6 · Architectural substitution",
            (
                "Exit: unchanged domain and system models operate through different "
                "realization technologies for the same relevant contract."
            ),
            [
                "Second independently implemented observation or intervention binding.",
                "Conformance and capability compatibility tests.",
                "Explicit supported and unsupported policy scope.",
            ],
            ["F14"],
            ["E5", "A12"],
        ),
        (
            "phase-7",
            "7 · Cross-domain validation",
            (
                "Exit: the simulated phone-feed scenario needs new bindings/policies but "
                "no redefinition of shared ontologies; this remains a hypothesis to test."
            ),
            [
                ("Equivalent scrolling-feed alternatives with ads present and absent or replaced."),
                (
                    "Capture at available semantic, presentation-description and graphics "
                    "boundaries."
                ),
                "Evaluate shared contracts without changing their meaning.",
            ],
            ["P9"],
            [],
        ),
    ]
    for identity, name, description, statements, requirements, criteria in phases:
        b.node(
            identity,
            Kind.PHASE,
            name,
            description,
            ScenarioScope.FUTURE if identity == "phase-7" else ScenarioScope.REFERENCE,
            statements,
        )
        for requirement in requirements:
            b.edge("delivers", identity, requirement)
        for criterion in criteria:
            b.edge("evaluates", identity, criterion)
    for left, right in zip(phases, phases[1:], strict=False):
        b.edge("next", left[0], right[0])


def add_governance(b: Builder) -> None:
    rules = [
        (
            "validity",
            "Binding validity",
            (
                "A binding is valid only when its capabilities fulfill the assigned "
                "contract, execution preserves applicable invariants, limitations are "
                "explicit and performance is evaluated against declared constraints."
            ),
            [
                "One binding may use several boundaries.",
                "One technology may realize several systems.",
                (
                    "Different technologies may satisfy the same contract without sharing "
                    "native representations."
                ),
                ("An attempts_to_fulfill relation is an obligation, not a proof of satisfaction."),
            ],
        ),
        (
            "independence",
            "Independent meanings and responsibilities",
            (
                "Domain defines meaning; systems own responsibilities; realizations "
                "provide mechanisms."
            ),
            [
                (
                    "Changing engine, graphics API or operating system must not redefine "
                    "domain concepts or the four responsibilities."
                ),
                (
                    "Local system vocabularies reference canonical concepts, specializing "
                    "only when additional semantics exist."
                ),
                (
                    "Capability is defined once; architectural Binding and runtime Policy "
                    "Binding have distinct meanings."
                ),
            ],
        ),
        (
            "interoperability",
            "Boundary contracts and native representations",
            (
                "Standardize meaning at system boundaries without unnecessarily "
                "converting native payloads into a universal representation."
            ),
            [
                "Version system contracts and keep core contracts language-agnostic.",
                (
                    "Keep native payloads accessible and explicitly typed; large binary "
                    "observations may live separately from metadata."
                ),
                (
                    "C1–C5 specify information exchanged, whereas behavioral contracts "
                    "specify system obligations."
                ),
            ],
        ),
        (
            "implementation",
            "Implementation constraints",
            "Experimental machinery must remain separate from production execution.",
            [
                "Experimental capture is not required in production runtime.",
                "Prepare policies before activation wherever possible.",
                ("Published executable policies include evidence of validity and supported scope."),
                "Personal screen captures and preference data remain local by default.",
            ],
        ),
        (
            "reuse",
            "Project-specific work and reuse",
            ("Build only the semantics and coordination not provided by existing capabilities."),
            [
                (
                    "Project-specific: counterfactual evidence semantics, system contracts "
                    "and binding validity."
                ),
                ("Project-specific: policy-synthesis orchestration and preference semantics."),
                (
                    "Reuse simulation, graphics APIs/drivers, capture/replay, inspection, "
                    "shader tooling and compatible learning infrastructure."
                ),
                (
                    "Reference documentation categories: Godot rendering architecture, Vulkan "
                    "Layers, GFXReconstruct, RenderDoc, Mesa SPIR-V replacement and Vulkan "
                    "profiling. Candidate suitability remains unevaluated."
                ),
            ],
        ),
        (
            "investigation",
            "Questions for a new environment",
            "Investigate capability sufficiency before choosing a realization.",
            [
                "What information does this environment expose?",
                "What can be changed at each boundary?",
                "Can those capabilities satisfy an existing system contract?",
                "Does the intervention preserve correctness and performance?",
            ],
        ),
        (
            "validation-limit",
            "What the MCP can establish",
            (
                "The MCP enforces registered types, legal endpoints, cardinality, "
                "required references, uniqueness and evidence structure. It cannot "
                "establish causal equivalence, semantic preservation or measured "
                "performance from assertions alone."
            ),
            [
                ("Structural validation alone cannot establish binding conformance."),
                (
                    "Assessment completion is not proof; a passing result requires declared "
                    "evidence obligations, whose truth still needs independent evaluation."
                ),
                (
                    "Changes invalidate dependent assessments; explicit unsupported states "
                    "must not be replaced with weaker promises."
                ),
            ],
        ),
    ]
    for identity, name, description, statements in rules:
        b.node(
            identity,
            Kind.GOVERNANCE,
            name,
            description,
            ScenarioScope.REFERENCE,
            statements,
        )
    exclusions = [
        ("X01", "Custom operating system or kernel"),
        ("X02", "New rendering engine"),
        ("X03", "Universal graphics intermediate representation"),
        ("X04", "Foundation-model training from scratch"),
        ("X05", "Dual original/transformed full rendering in production"),
        ("X06", "Every commercial game compatibility"),
        ("X07", "Anti-cheat, DRM or protected-content circumvention"),
        ("X08", "Complete iOS or Android implementation"),
        ("X09", "Perfect recognition of previously unseen content"),
        ("X10", "Universal pre-exposure guarantees without environmental support"),
    ]
    for identity, name in exclusions:
        b.node(
            identity,
            Kind.EXCLUSION,
            f"{identity} · {name}",
            (
                "Not a prerequisite for the initial architectural proof. A future "
                "extension requires its own explicit scope and capability evaluation."
            ),
            ScenarioScope.REFERENCE,
        )


def add_independence(b: Builder) -> None:
    b.node(
        "recognition-capability",
        Kind.CAPABILITY,
        "Semantic recognition from composed pixels",
        "Infer the intended target from composed pixels with sufficient specificity; "
        "intrinsic object identity is not assumed. Recognition must satisfy the objective's "
        "preservation, latency and exposure constraints.",
        ScenarioScope.REFERENCE,
    )
    candidates = [
        (
            "B3-engine",
            "S3 · Engine-level intervention binding",
            "engine-boundary",
            "May modify identified materials or effects before rendering. Validity depends on "
            "demonstrated semantic targeting, preservation and performance through "
            "available engine controls.",
        ),
        (
            "B3-compositor",
            "S3 · Compositor intervention binding",
            "composition-boundary",
            "May modify composed pixels, but has no intrinsic blood-object identity. Additional "
            "recognition is required, and latency, preservation and exposure obligations "
            "still apply.",
        ),
    ]
    for identity, name, boundary, description in candidates:
        b.node(identity, Kind.BINDING, name, description, ScenarioScope.REFERENCE)
        b.edge("attempts_to_fulfill", identity, "S3-contract")
        b.edge("uses_boundary", identity, boundary)
        b.edge("produces", identity, "C5")
        for capability in [
            "targeting-capability",
            "substitution-capability",
            "protection-capability",
            "measurement-capability",
        ]:
            b.edge("requires_capability", identity, capability)
        if identity == "B3-compositor":
            b.edge("requires_capability", identity, "recognition-capability")
        for invariant in ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]:
            b.edge("must_preserve", identity, invariant)
    b.node(
        "independence-example",
        Kind.INDEPENDENCE,
        "One objective and contract, three candidate realizations",
        "The engine, graphics-API and compositor candidates attempt the same S3 contract. "
        "Their available information, control and costs differ; substitutability requires "
        "evidence that the unchanged objective, contract and applicable invariants "
        "remain satisfied.",
    )
    b.edge("demonstrates_objective", "independence-example", "blood-glitter-objective")
    b.edge("holds_contract", "independence-example", "S3-contract")
    for binding in ["B3-engine", "B3", "B3-compositor"]:
        b.edge("compares_binding", "independence-example", binding)
        b.edge("applies_to", "blood-glitter-objective", binding)


def write_artifacts() -> None:
    schema, nodes, edges = build()
    for name, value in [
        ("schema.json", schema),
        ("source.json", {"schema": schema, "nodes": nodes, "edges": edges}),
    ]:
        (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def rejected_changes(nodes: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    by_id = {node["id"]: node for node in nodes}
    duplicate = {**by_id["policy"], "id": "duplicate-policy"}
    orphan = {
        **by_id["S1"],
        "id": "orphan-system",
        "properties": {**by_id["S1"]["properties"], "name": "Unowned responsibility"},
    }
    unsupported_status = {
        "op": "update_node",
        **by_id["B3"],
        "properties": {**by_id["B3"]["properties"], "lifecycle": "verified"},
    }
    return [
        (
            "independence example changes its supposedly fixed contract",
            [
                {
                    "op": "update_edge",
                    "id": "holds_contract:independence-example:S3-contract",
                    "type": "holds_contract",
                    "source": "independence-example",
                    "target": "S2-contract",
                }
            ],
        ),
        (
            "domain relationship crosses into a technology",
            [
                {
                    "op": "create_edge",
                    "edge": {
                        "id": "invalid-domain-technology",
                        "type": "modifies",
                        "source": "experience",
                        "target": "vulkan",
                    },
                }
            ],
        ),
        ("duplicate canonical domain meaning", [{"op": "create_node", "node": duplicate}]),
        ("system without responsibility", [{"op": "create_node", "node": orphan}]),
        (
            "behavioral contract attached to system instead of responsibility",
            [
                {
                    "op": "create_edge",
                    "edge": {
                        "id": "illegal-contract",
                        "type": "specified_by",
                        "source": "S1",
                        "target": "S1-contract",
                    },
                }
            ],
        ),
        (
            "exchange confused with behavioral contract",
            [
                {
                    "op": "create_edge",
                    "edge": {
                        "id": "illegal-exchange",
                        "type": "attempts_to_fulfill",
                        "source": "B3",
                        "target": "C3",
                    },
                }
            ],
        ),
        (
            "binding without observation or control boundary",
            [{"op": "delete_edge", "id": "uses_boundary:B3:graphics-boundary"}],
        ),
        ("asserted verification without assessment", [unsupported_status]),
        (
            "behavioral contract without version",
            [
                {
                    "op": "update_node",
                    **by_id["S3-contract"],
                    "properties": {
                        key: value
                        for key, value in by_id["S3-contract"]["properties"].items()
                        if key != "version"
                    },
                }
            ],
        ),
    ]


async def author(workspace: Path) -> None:
    schema, nodes, edges = build()
    if workspace.exists():
        raise SystemExit(f"Refusing existing workspace: {workspace}; choose a fresh path")
    (workspace / "model").mkdir(parents=True)
    (workspace / "model" / "schema.json").write_text(
        json.dumps({"schema": schema, "nodes": [], "edges": []}, indent=2) + "\n"
    )
    transcript: list[dict[str, Any]] = []
    rejected: list[str] = []
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "typed_graph.adapters.mcp_server", str(workspace)]
    )
    async with Client(parameters, read_timeout_seconds=180) as client:

        async def call(
            name: str, arguments: dict[str, Any], expect_error: bool = False
        ) -> dict[str, Any]:
            response = await client.call_tool(name, arguments)
            if bool(response.is_error) != expect_error:
                raise RuntimeError(f"Unexpected {name} result: {response}")
            result = response.structured_content
            transcript.append(
                {
                    "tool": name,
                    "arguments": arguments,
                    "is_error": bool(response.is_error),
                    "result": result,
                    "messages": [item.model_dump(mode="json") for item in response.content]
                    if expect_error
                    else [],
                }
            )
            if expect_error:
                return {}
            assert isinstance(result, dict)
            return result

        indexed = await call("index_model", {})
        assert not (await call("query_graph", {"limit": 1000}))["nodes"]
        revision = indexed["revision"]
        created_nodes: set[str] = set()
        created_edges: set[str] = set()
        by_id = {node["id"]: node for node in nodes}
        desired_edges = {edge["id"]: edge for edge in edges}

        def targets(identity: str, relation: str, *, incoming: bool = False) -> list[str]:
            return [
                edge["source" if incoming else "target"]
                for edge in edges
                if edge["target" if incoming else "source"] == identity and edge["type"] == relation
            ]

        async def mutate(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal revision
            result = await call(name, {"expected_revision": revision, **arguments})
            revision = result["revision"]
            for change in result["applied_changes"]:
                if change["op"] == "create_node":
                    node = change["node"]
                    assert node == by_id[node["id"]], (name, node, by_id[node["id"]])
                    created_nodes.add(node["id"])
                elif change["op"] == "create_edge":
                    edge = change["edge"]
                    assert edge == desired_edges[edge["id"]], (name, edge)
                    created_edges.add(edge["id"])
            return result

        for node in nodes:
            if node["type"] == Kind.CONCEPT:
                await mutate("define_concept", {"id": node["id"], "concept": node["properties"]})
            elif node["type"] == Kind.LAYER:
                await mutate("add_layer", {"id": node["id"], "layer": node["properties"]})
        core_roles = {Kind.INVARIANT, Kind.CAPABILITY, Kind.ENVIRONMENT}
        await mutate(
            "apply_changes",
            {
                "changes": [
                    {"op": "create_node", "node": node}
                    for node in nodes
                    if node["type"] in core_roles
                ]
            },
        )
        for node in nodes:
            if node["type"] != Kind.BOUNDARY:
                continue
            arguments = {
                "id": node["id"],
                "boundary": node["properties"],
                "layers": targets(node["id"], "classified_by"),
            }
            environments = targets(node["id"], "exposes", incoming=True)
            if environments:
                assert len(environments) == 1
                arguments["environment"] = environments[0]
            await mutate("define_boundary", arguments)
        for node in nodes:
            if node["type"] != Kind.SYSTEM:
                continue
            responsibility = by_id[targets(node["id"], "owns")[0]]
            contract = by_id[targets(responsibility["id"], "specified_by")[0]]
            await mutate(
                "define_system",
                {
                    "id": node["id"],
                    "system": node["properties"],
                    "responsibility": responsibility["properties"],
                    "contract": contract["properties"],
                    "concerns": targets(responsibility["id"], "concerns"),
                    "invariants": targets(contract["id"], "must_preserve"),
                    "capabilities": targets(contract["id"], "requires_capability"),
                },
            )
        for node in nodes:
            if node["type"] == Kind.BINDING:
                await mutate(
                    "propose_binding",
                    {
                        "id": node["id"],
                        "binding": node["properties"],
                        "contract": targets(node["id"], "attempts_to_fulfill")[0],
                        "boundaries": targets(node["id"], "uses_boundary"),
                        "capabilities": targets(node["id"], "requires_capability"),
                        "invariants": targets(node["id"], "must_preserve"),
                    },
                )
        remaining = [
            {"op": "create_node", "node": node} for node in nodes if node["id"] not in created_nodes
        ]
        remaining += [
            {"op": "create_edge", "edge": edge} for edge in edges if edge["id"] not in created_edges
        ]
        await mutate("apply_changes", {"changes": remaining})
        observed = await call("query_graph", {"limit": 1000})
        assert len(observed["nodes"]) == len(nodes)
        registered = await call("get_graph_schema", {})
        assert registered["schema"]["node_types"] == schema["node_types"]
        for system in ["S1", "S2", "S3", "S4"]:
            responsibility_id, contract_id = f"{system}-responsibility", f"{system}-contract"
            path = await call(
                "trace_path",
                {"source": responsibility_id, "target": contract_id, "relation": "specified_by"},
            )
            assert path["path"] == [responsibility_id, contract_id]
        for source in ["C3", "A05", "F11"]:
            dependency = await call(
                "trace_path", {"source": source, "target": "B3", "mode": "dependency"}
            )
            assert dependency["path"][0] == source and dependency["path"][-1] == "B3"
        for name, invalid in rejected_changes(nodes):
            await call(
                "apply_changes",
                {"expected_revision": revision, "changes": invalid},
                expect_error=True,
            )
            rejected.append(name)
        await call(
            "submit_assessment",
            {
                "revision": revision,
                "interceptor_id": "binding-conformance",
                "target_id": "B3",
                "result": {"status": "pass", "findings": [], "evidence": []},
            },
            expect_error=True,
        )
        rejected.append("passing conformance without required evidence")
        await call(
            "apply_changes",
            {
                "expected_revision": revision - 1,
                "changes": [
                    {
                        "op": "update_node",
                        **by_id["S3"],
                        "properties": {
                            **by_id["S3"]["properties"],
                            "description": "Must not commit with stale revision",
                        },
                    }
                ],
            },
            expect_error=True,
        )
        rejected.append("stale expected revision cannot partially commit")
        final = await call("query_graph", {"limit": 1000})
        assert final["revision"] == revision and len(final["nodes"]) == len(nodes)
        assessments = (await call("get_assessments", {}))["assessments"]
        assert {item["target_id"] for item in assessments} <= {
            node["id"] for node in nodes if node["type"] == Kind.BINDING
        }
        assert all(
            item["state"] == "pending"
            and item["result"]["status"] == "indeterminate"
            and not item["result"]["evidence"]
            for item in assessments
        )
        diff = await call(
            "compare_graphs", {"from_revision": indexed["revision"], "to_revision": revision}
        )
        assert len(diff["nodes"]["added"]) == len(nodes)
        assert len(diff["edges"]["added"]) == len(edges)
    report = {
        "workspace": str(workspace),
        "transport": "MCP stdio / mcp.client.Client",
        "revision": revision,
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(sorted(Counter(node["type"] for node in nodes).items())),
        "relation_types": len(schema["relations"]),
        "tool_calls": len(transcript),
        "rejected_fallacies": rejected,
        "pending_assessments": sum(item["state"] == "pending" for item in assessments),
        "completed_assessments": sum(item["state"] == "completed" for item in assessments),
        "assessment_revisions": sorted({item["revision"] for item in assessments}),
        "stale_assessments": sum(item["stale"] for item in assessments),
        "semantic_tool_calls": sum(
            item["tool"]
            in {
                "define_concept",
                "add_layer",
                "define_boundary",
                "define_system",
                "propose_binding",
            }
            for item in transcript
        ),
        "implementation_or_performance_proven": False,
    }
    (workspace / "mcp-transcript.json").write_text(json.dumps(transcript, indent=2) + "\n")
    (workspace / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path, nargs="?")
    parser.add_argument("--write-artifacts", action="store_true")
    arguments = parser.parse_args()
    if arguments.write_artifacts:
        write_artifacts()
    if arguments.workspace:
        asyncio.run(author(arguments.workspace.resolve()))
    elif not arguments.write_artifacts:
        parser.error("Provide a fresh workspace or --write-artifacts")
