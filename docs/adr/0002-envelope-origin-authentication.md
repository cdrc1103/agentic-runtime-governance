# ADR-0002: How "authenticated against origin" is achieved

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-02 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: How "authenticated against origin" is achieved.

## Decision

Gateway-built envelopes are authentic by construction (action observed, identity from credentials). Native envelopes are signed by the adapter's agent-instance key. Honest limit: a compromised agent process shares the adapter's trust boundary, hence INT-04

## Consequences

Requirements and tests that depend on this decision cite SG-02. Revisit if the paper's
authors publish clarifying material.
