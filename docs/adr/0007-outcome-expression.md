# ADR-0007: How outcomes are expressed to the agent or protocol

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-07 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: How outcomes are expressed to the agent or protocol.

## Decision

Decision response with `outcome`, `reason_codes`, `decision_id`, optional `token`, optional `escalation_id` (see section 6)

## Consequences

Requirements and tests that depend on this decision cite SG-07. Revisit if the paper's
authors publish clarifying material.
