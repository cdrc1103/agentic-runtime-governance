# ADR-0014: Decision service ownership of audit, idempotency, and reviewer re-entry

- Status: accepted (default decision)
- Tag: [DESIGN]; refines SG-04, SG-06, SG-09.

## Decisions

- **Audit is not a configurable pipeline stage.** AUD-01 needs an entry on every path,
  including rejections raised by earlier stages, so `DecisionService` always audits.
  The remaining stages (validate, identity, mandate, retrieve, evaluate, reserve) are
  ordered `PipelineStage`s built from `runtime.yaml`.
- **Reservation and audit succeed together.** Reserve happens before the audit append; if the
  append fails the reservation is released and the decision fails closed (Deny).
  Escalations hold no reservation; the intended reservations are stored on the escalation
  record and applied unconditionally when an authorised reviewer approves.
- **Idempotency** is first-writer-wins on `envelope_id` in the state store (ENV-06).
- **Reviewer "modify"** ends the original (audited as Deny with a child reference) and
  submits a new envelope: `parent_envelope_id` set, `envelope_id = <orig>-m1`, provenance
  `reviewer:<id>`. Because it carries no agent signature, it enters through an internal
  `internal_identity` parameter that reuses the verified binding of the original and skips
  only the identity stage; validation, mandate, controls, and reservation all run again.
  This parameter is not exposed by the HTTP API.
- **Refused reviewer attempts are audited** in the escalated agent's stream (outcome stays
  `escalate`), so ESC-04 failures are visible.
- `escalation_id = "esc-" + envelope_id`; the record's `decision_id` is filled in after the
  audit append.

## Consequences

Known reference-grade limits: no cross-store transaction (an anchor/audit failure after a
successful `put_decision` race is not reconciled), and reviewer re-entry trusts the service
process. Both go in `docs/production-gaps.md`.
