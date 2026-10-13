# ADR-0005: What "structured observation" contains and who consumes it

- Status: accepted (default decision, owner may revise at a checkpoint)
- Spec gap: SG-05 (see `docs/spec/spec-gaps.md`)
- Tag: [DESIGN]. The SAFR paper is silent here; this is not part of SAFR.

## Context

The paper leaves this open: What "structured observation" contains and who consumes it.

## Decision

`Observation{code, severity, details}` stored in the audit entry and emitted as an OTel event

## Consequences

Requirements and tests that depend on this decision cite SG-05. Revisit if the paper's
authors publish clarifying material.
