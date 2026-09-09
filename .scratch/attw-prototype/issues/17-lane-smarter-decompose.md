# 17 — Lane: smarter idea decomposition

Status: resolved

## Answer

Splitter real (capability families, confidence scaling, repo path
identical); demo idea yields 3–4 components. Critic PASS; verifier
verified. Merged via PR (trickle).
Type: task
Lane: 4 of 4. File claim: `src/attw/understand.py`, `tests/test_understand.py`.

## Question

Fix demo lesson 2: "an app that rewrites AI-generated text to sound human"
became ONE blob component. Split ideas into genuinely separable components.

## Spec

Improve the idea-text splitter (no LLM available: deterministic rules):
split on capability boundaries (verbs + objects: rewrite/paraphrase,
score/readability, detect/AI-likelihood, CLI/API surface), emit one
component per capability with kind addition and confidence scaled by
specificity (vague blobs get low confidence, which the quality floor can
then decline). The demo idea must yield ≥2 components. Keep repo-path
behavior identical (all existing tests stay green unmodified unless they
pinned blob behavior — if so, say why). Fixture tests over several idea
strings incl. single-capability (stays one) and multi-capability (splits).

## Done-criteria

Splitter improved + unit tests; demo idea yields ≥2 components; gate green;
checker happy before integrator. Then merge via PR, trickle.
