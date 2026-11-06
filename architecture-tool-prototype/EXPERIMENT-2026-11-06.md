# Challenge the decomposition: wording experiment, 2026-11-06

## Minimal change

Only the two tool-description strings in `server.py` changed. The additions total 33 words:

- `define_product_boundary`: **Surface ambiguities and missing intent rather than silently resolving them.**
- `decompose_system`: **Treat the decomposition as a hypothesis: challenge whether these are the right systems for the intended experience, including plausible alternative interpretations and boundaries.**

No fields, schemas, validation, persistence, model invocation, or runtime architecture logic were added. The server still only records supplied artifacts. This tests the caller's response to wording, not a semantic validator.

## Method

Ran two fresh callers with no prior project conversation. Each discovered its tools through the real `client.py` MCP stdio bridge and authored actual `tools/call` arguments. The tool descriptions were not injected into their native tool menu. Standard agent harness context and tools remained present.

- Baseline: the source from PR head `751af2402d8361c1b94d4543b8fb5e69ab4c86ac`.
- Revised: that source with only the two description additions above.
- Both used Python 3.12.14, MCP 1.29.0, Pydantic 2.13.4, identical input schemas, transport instructions, initial prompt, and simulated clarification. Neither caller was told the comparison hypothesis or the other case's output. There was no model override; the inherited model configuration was the same. Random seeds and sampling were not controlled.
- Cases ran separately and approximately concurrently, with separate empty output directories. Research was allowed but not scripted, so the pages consulted differed.
- The original November 1 result remains intact in `live-run/` and [EXPERIMENT.md](EXPERIMENT.md). It is historical context, not the fresh baseline.

Initial prompt:

> I want to build something that will intercept what’s rendered on a screen, and replace it. Use the define_product_boundary and decompose_system tools.

Both callers asked what should be replaced and where before making an authoring call. Each received the same simulated reply from the original experiment:

> For example, replace blood in a game with glitter. Eventually across the desktop, not just one application. I only want to change what I see, not how the game behaves or how I interact with it.

Exact clarification questions and scenario text are in [wording-run/scenario.json](wording-run/scenario.json). No further requirements were supplied.

## Observed comparison

The useful distinction is questions **about** a decomposition, whose answers could remove, merge, split, or replace its constituent systems, versus questions **within** an assumed structure.

The fresh baseline proposed five systems: Display Mediation, Visual Interpretation, Visual Substitution, User Policy and Control, and Live Session Coordination. It surfaced platform, latency, failure, and fidelity uncertainties. It also left the presentation mechanism undecided and acknowledged that a never-show-original requirement could materially change the display path. It was not wholly uncritical. However, it did not explicitly connect an alternative interpretation of the user's intent to eliminating or merging its proposed constituent systems.

The revised case proposed four systems: Viewing Integration, Visual Interpretation, Replacement Synthesis, and Experience Control. More importantly, it directly challenged the need for its own boundaries:

- **Could a system disappear?** “A simple color transform could meet a stylized recoloring requirement with no separately realized semantic interpreter.” It also notes that this would alter unrelated similarly colored content and would not establish blood understanding.
- **Could systems merge or expand?** “Is approximate stylization sufficient, or must the replacement remove blood convincingly while preserving scene context and motion? This can merge or expand the interpretation and synthesis boundaries.”
- **Could the integration boundary be wrong?** If the altered view cannot preserve visibility, focus, input, and feedback behavior, “the viewing integration boundary must change.” It considers a game-native visual mod, permitted compositor/display-path integration, and an external video processor. These alternatives are hypotheses, not established solutions.
- **Is the starting phrase an implementation assumption?** The boundary is “the personal viewing experience, not necessarily an interception hook, capture utility, or application modification.”

Both fresh cases combined acquisition and presentation. The reduction from five systems to four is not itself evidence of improvement; it could be ordinary run-to-run variation. The stronger observation is the revised artifact's explicit connection between uncertain intent and a removable or changeable constituent boundary.

## Remaining weaknesses and limits

- Both outputs still select an image-processing conceptual architecture. The revised case challenges it more explicitly but does not prove it is the right architecture or sufficiently explore every alternative.
- The fresh baseline excludes game-asset changes outright, repeating a narrowing assumption seen in the original run. The revised boundary excludes game-asset changes “as the intended product behavior” yet later considers a game-native mod. Whether an asset-based implementation is acceptable remains unresolved; the user's statement about unchanged behavior does not settle it.
- Independence arguments in both still rely substantially on isolated testing and substitutable implementations. This is useful engineering evidence, not proof that the systems are the right conceptual decomposition.
- Both researched Microsoft capture documentation and distinguished capture access from control of the final displayed view. Neither built a transformation runtime or demonstrated latency, recognition quality, unchanged interaction, or desktop-wide feasibility.
- This is one stochastic pair, qualitatively reviewed after execution, with uncontrolled research choices and no fixed random seed. It supports “the intended critical behavior appeared in this revised run,” not a causal effect size or a reliability claim. The historical run is not a controlled replicate of the current runtime.

## Evidence and verification

Exact tool descriptions/input schemas, immutable revision-1 results, and received/persisted call logs are saved under [wording-run/baseline/](wording-run/baseline/) and [wording-run/revised/](wording-run/revised/). Logs retain their original local result paths as provenance; those paths are not needed to read the adjacent saved results.

Each fresh case made two successful authoring calls, with no rejected calls:

- Baseline boundary: `e6575e05-0875-4384-8e60-e04000b18d04`.
- Baseline decomposition: `9fc52f30-e29e-400e-8f6d-6cf55c2b8ae9`.
- Revised boundary: `8e4251ea-c737-47c0-b049-260cde76fb2a`.
- Revised decomposition: `3406aa70-9364-45f5-86f3-6fb9024fa09a`.

Verified exact argument/result agreement and matching call IDs in both saved traces. A source-AST comparison with the description values masked found no other code changes; discovered input schemas were identical.

Local checks passed:

- `python architecture-tool-prototype/smoke_test.py` using the pinned MCP 1.x environment: 8 real calls, 4 persisted, 4 rejected; strict schema validation and revision persistence across restart passed.
- Repository environment: `ruff format --check .`, `ruff check .`, `mypy src`, `pytest` (95 passed), and `python -m build --no-isolation` (source and wheel builds passed).

To repeat, prepare separate baseline and revised copies of `server.py` and the unchanged `client.py`, install `requirements.txt`, and give fresh callers only the scenario and transport commands described in [README.md](README.md). Use separate empty output directories and the same clarification. Inspect the resulting artifacts rather than treating successful persistence as evidence of architectural correctness.
