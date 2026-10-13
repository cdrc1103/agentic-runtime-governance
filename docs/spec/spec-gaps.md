# Spec gaps and default decisions

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Spec gaps and default decisions

The paper leaves these open. Each default becomes an ADR and an entry in `spec-gaps.md`. **Do not contact anyone and do not draft issue text for external parties (D6).**

| ID | Gap | Our default |
|---|---|---|
| SG-01 | No envelope schema | Schema in section 6, versioned, JSON Schema exported |
| SG-02 | How "authenticated against origin" is achieved | Gateway-built envelopes are authentic by construction (action observed, identity from credentials). Native envelopes are signed by the adapter's agent-instance key. Honest limit: a compromised agent process shares the adapter's trust boundary, hence INT-04 |
| SG-03 | Conflict precedence between controls | DSP-06 |
| SG-04 | How aggregate exposure and rate state is kept | `StateStore.reserve()` atomic counters in fixed windows, keyed by agent and/or principal. Reserve at decision time, optional void on failed execution. Reservation and audit append succeed together or the reservation is released and the decision fails closed |
| SG-05 | What "structured observation" contains and who consumes it | `Observation{code, severity, details}` stored in the audit entry and emitted as an OTel event |
| SG-06 | Meaning of reviewer "modify" | ESC-05 |
| SG-07 | How outcomes are expressed to the agent or protocol | Decision response with `outcome`, `reason_codes`, `decision_id`, optional `token`, optional `escalation_id` (see section 6) |
| SG-08 | What "completeness and coherence" checks are | Completeness: required fields per action type. Coherence: schema version supported; `context.agent_id` equals the identity claim; trace non-empty where the action type requires it; trace timestamps monotonic; mandate reference resolves; for gateway origin, action-parameter hash equals the observed-call hash |
| SG-09 | Behaviour when SAFR is unavailable | INT-05 |
| SG-10 | Delegation chain representation | Mandate carries `delegation_chain[]` and `depth`; authorisation control enforces a configured max depth |

---
