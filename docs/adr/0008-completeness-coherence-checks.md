# ADR-0008: What "completeness and coherence" checks are

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-08 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: What "completeness and coherence" checks are.

## Decision

Completeness: required fields per action type. Coherence: schema version supported; `context.agent_id` equals the identity claim; trace non-empty where the action type requires it; trace timestamps monotonic; mandate reference resolves; for gateway origin, action-parameter hash equals the observed-call hash

## Consequences

Requirements and tests that depend on this decision cite SG-08. Revisit if the paper's
authors publish clarifying material.
