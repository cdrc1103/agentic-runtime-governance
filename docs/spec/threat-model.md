# Threat model

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Threat model (document and test)

| # | Threat | Mitigation | Tests |
|---|---|---|---|
| T1 | Forged envelope (action and trace fabricated together) | Gateway-observed binding, adapter signature, coherence checks, token action hash | S08, S09 |
| T2 | Agent bypasses native instrumentation | Hybrid gateway requires token | S10 |
| T3 | Token replay | One-time `jti`, short TTL | S11 |
| T4 | Action altered after decision (TOCTOU) | `act_hash` binding | S12 |
| T5 | Audit tampering (modify / delete / reorder) | Hash chain, external anchor, verify tool | S13 |
| T6 | Unreviewed or stale controls | Approved-only load, bundle hash in every entry | S14 |
| T7 | Escalation flooding / reviewer fatigue | ESC-06 cap, timeout defaults | S06, S15 |
| T8 | SAFR unavailable | Fail closed | S16 |
| T9 | Agent extends its own mandate | Mandates and controls are read-only inputs, agent has no write path | S17 |
| T10 | Limit evasion via many agent identities | Exposure and rate keys configurable by agent and by principal | S18 |

---
