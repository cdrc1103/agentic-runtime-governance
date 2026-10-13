# ADR-0011: Rego control evaluator calls the OPA CLI

- Status: accepted (decision D4)
- Tag: [DESIGN]; optional, not part of SAFR.

## Context

Institutions may already express policy in Rego. The plan asks for a light integration
(T-405) behind the `ControlEvaluator` port, with parity tests against the built-in evaluators.

## Decision

- One `opa eval --data <policy> --stdin-input --format json <query>` subprocess per
  evaluation (verified against OPA v1.21.2, Oct 2026: JSON output is
  `{"result":[{"expressions":[{"value":...}]}]}`, an undefined query yields `{}`).
  REST API route not needed. Rego v1 syntax is the default; policies need no imports.
- Policy files live in the controls bundle and are covered by the manifest hash, so a Rego
  change changes the policy version.
- Input: `{envelope, identity, mandate, state, signals, at, logic, effect}`. Output:
  `{effect, reason_codes}`; undefined means pass. Any error fails closed through dispatch.
- Parity scope: per-action exposure and authorisation (all conditions except the mandate
  validity window, which the mandate resolver already enforces). Tests carry the `rego`
  marker and skip when `opa` is not on PATH.

## Consequences

Per-call process start is slow (acceptable for a reference). No Wasm, bundling, or policy
management is built.
