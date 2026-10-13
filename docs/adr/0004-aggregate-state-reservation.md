# ADR-0004: How aggregate exposure and rate state is kept

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-04 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: How aggregate exposure and rate state is kept.

## Decision

`StateStore.reserve()` atomic counters in fixed windows, keyed by agent and/or principal. Reserve at decision time, optional void on failed execution. Reservation and audit append succeed together or the reservation is released and the decision fails closed

## Consequences

Requirements and tests that depend on this decision cite SG-04. Revisit if the paper's
authors publish clarifying material.
