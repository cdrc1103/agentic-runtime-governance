# Conformance scenarios

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Conformance scenarios (all end to end; each lists the IDs it proves)

| ID | Scenario | Expected | Proves |
|---|---|---|---|
| S01 | Payment within exposure limit | Auto-Execute, token, audit entry | DSP-02, AUD-01/03 |
| S02 | Payment above per-action limit | Escalate, pending, held | DSP-02, ESC-01, CTL-05 |
| S03 | Aggregate exposure exceeded across several small actions | Escalate or Deny per config | CTL-05, SG-04 |
| S04 | Expired mandate | Deny | CTL-03/04 |
| S05 | Unregistered or suspended agent | Rejected at identity stage, logged, no controls retrieved | IDN-01/02/05 |
| S06 | Escalation timeout | Blocked (or senior reviewer), logged | ESC-03 |
| S07 | Reviewer without sufficient authority | Resolution refused, logged | ESC-04 |
| S08 | Gateway standalone: agent-declared action differs from observed call | Observed call governs; mismatch Denied | ENV-04, INT-02 |
| S09 | Native envelope with invalid signature | Rejected | ENV-04, IDN-01 |
| S10 | Hybrid: call without token | Gateway refuses | INT-04 |
| S11 | Token replay | Second use refused | INT-04 |
| S12 | Token valid but call parameters altered | Hash mismatch, refused | INT-04 |
| S13 | Audit row tampered, deleted, reordered | `verify` fails | AUD-02/06 |
| S14 | Controls bundle containing unapproved control (production mode) | Load refused | CTL-07, DSP-04 |
| S15 | Open-escalation cap reached | New escalation blocked, metric raised | ESC-02/06 |
| S16 | Core unreachable or erroring | Deny, never Auto-Execute | INT-05 |
| S17 | Agent attempts to widen its own mandate | No effect | CTL-03 |
| S18 | Many agent identities of one principal, exposure keyed by principal | Aggregate enforced | CTL-05, SG-04 |
| S19 | Rate burst | Escalate or Deny after threshold | CTL-05 |
| S20 | Evidence below confidence threshold, low value | Escalate regardless of value | CTL-05 |
| S21 | Anomalous action within limits | Observe, observation recorded | DSP-02/03, SG-05 |
| S22 | Multi-step workflow: step 2 beyond mandate after step 1 auto-executed | Step 2 independently evaluated and denied | DSP-05 |
| S23 | Duplicate `envelope_id` | Original decision returned, no second reservation | ENV-06 |
| S24 | Reviewer "modify" | New envelope re-evaluated with parent link | ESC-05 |
| S25 | Open-network context with two registries | Authoritative registry chosen by context | IDN-04 |
| S26 | Same inputs run repeatedly (property test) | Identical outcome | DSP-07 |

---
