# Zero-project-context MCP experiment — 2026-11-01

## Setup

A fresh native agent inherited no conversation history. It received the user prompt below and transport instructions only. It discovered the two schemas through actual MCP `tools/list` and executed actual `tools/call` via `client.py`. The client is a shell-accessible stdio transport bridge, not a mock; the tools were not dynamically injected into the agent's native tool menu. Standard agent harness instructions and tools still existed, so “zero context” means zero prior project context, not absence of system instructions.

Prompt: “I want to build something that will intercept what’s rendered on a screen, and replace it. Use the define_product_boundary and decompose_system tools.”

The agent asked where replacement should happen (controlled app/browser, across apps, separate display/video feed) and what should be replaced with what. No authoring call preceded this clarification.

Parent's simulated user reply, under progressive-disclosure authorization: “For example, replace blood in a game with glitter. Eventually across the desktop, not just one application. I only want to change what I see, not how the game behaves or how I interact with it.”

## Actual result

Both calls succeeded and persisted revision 1. Full exact arguments/results are in `live-run/`; call IDs and timestamps are in `calls.jsonl`.

- define_product_boundary: 445f25be-c65c-45b0-b7de-f67059e89356
- decompose_system: 71c27eb6-65fa-49ab-bd1a-2d65b4deba35

Recorded product: Personal Visual Replacement System.

Constituent systems:
1. Experience Policy and Session Control
2. Visual Source Access
3. Target Recognition and Tracking
4. Replacement Synthesis and Composition
5. Presentation and Display Integration

The agent consulted Microsoft Desktop Duplication and Apple ScreenCaptureKit official documentation. It explicitly distinguished capture from display control and left pre-exposure guarantees unresolved. No transformation runtime or performance benchmark was implemented.

## Observation, not statistical conclusion

The tools elicited clarification, a product boundary, external research, decomposition, interfaces, assumptions, and unresolved questions. The agent still selected an image-based conceptual pipeline. Its boundary also excluded source-asset modification without the simulated user expressly requesting that exclusion. That exclusion is the agent's assumption, not an accepted requirement. Independence rationales leaned on independent testing/replacement. One run cannot establish reliability or show that this is the right architecture.

## Verification

Real MCP behavioral smoke test passed: 8 calls, 4 valid/persisted, 4 invalid/rejected; strict nested field validation, exact input logs, and revision persistence across restart checked. Prototype is intentionally not productionized. No production code was changed.
