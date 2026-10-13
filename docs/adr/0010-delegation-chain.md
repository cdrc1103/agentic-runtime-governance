# ADR-0010: Delegation chain representation

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-10 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: Delegation chain representation.

## Decision

Mandate carries `delegation_chain[]` and `depth`; authorisation control enforces a configured max depth

## Consequences

Requirements and tests that depend on this decision cite SG-10. Revisit if the paper's
authors publish clarifying material.
