# Data contracts

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Data contracts (implement as pydantic models; export JSON Schema to `schemas/`)

**Envelope**

| Field | Notes |
|---|---|
| `schema_version`, `envelope_id`, `created_at` | `envelope_id` unique; ENV-06 |
| `action` | `type`, `scope`, `parameters`, optional `parent_envelope_id` |
| `action_trace` | `steps[]`: `step_id`, `kind` (tool_call / retrieval / check / model_call), `name`, `input_hash`, `output_hash`, `started_at`, `ended_at`, optional `otel_span_id` |
| `context` | `agent_id`, `network_context`, `mandate_ref`, `system_state`, `policy_constraints[]`, `workflow_id`, `step_index`, `signals{}` (confidence, anomaly score, etc.) |
| `provenance` | `origin` (native / gateway), `adapter_id`, `signature`, `observed_call{method, target, params_hash}` for gateway origin |

**Mandate:** `mandate_id`, `principal`, `agent_id`, `permitted_actions[]`, `limits` (per-action, aggregate, rate), `conditions`, `not_before`, `not_after`, `delegation_chain[]`, `depth`, `revocation_ref`, `signature` (principal key).

**Control:** `control_id`, `version`, `source` (regulatory / policy / product / mandate), `category` (authorisation / exposure / rate / evidence / custom), `kind` (generic / ai_specific), `applies_to` (action types, agent classes), `logic` (type-specific), `effect` (deny / escalate / observe), `escalation` (queue, timeout, reviewer_role), `validity`, `owner`, `review_status`.

**Calibration file:** thresholds per action type for materiality bands, enums for reversibility / customer impact / regulatory sensitivity, novelty rules; `review_status` required.

**Decision response:** `decision_id`, `outcome`, `reason_codes[]`, `rules_applied[]`, `policy_version` (bundle hash), `observations[]`, `stage_timings_ms{}`, `token?`, `escalation_id?`.

**Decision token** (compact JWS, EdDSA): `jti`, `iss`, `sub` (agent_id), `decision_id`, `outcome`, `act_hash` (SHA-256 of canonical action), `policy_version`, `iat`, `exp` (short TTL). One-time use via atomic consume on the state store.

**Audit entry:** `entry_id`, `agent_stream`, `seq`, `prev_hash`, `entry_hash`, `recorded_at`, `envelope` (as submitted), `mandate_snapshot`, `identity_result`, `policy_version`, `rules_applied[{control_id, version, result, inputs}]`, `outcome`, `basis`, `observations[]`, `stage_timings_ms{}`, `token_jti?`, `escalation_id?`, `reviewer_decision?`.

**Decision API**

| Endpoint | Purpose |
|---|---|
| `POST /v1/decisions` | Submit envelope, receive decision |
| `GET /v1/escalations/{id}` | Escalation status |
| `POST /v1/escalations/{id}/resolution` | Reviewer approve / decline / modify (authority checked) |
| `POST /v1/tokens/consume` | Atomic one-time token consumption |
| `GET /v1/audit/{agent_id}/verify` | Verify chain |
| `POST /v1/escalations/sweep` | Apply timeouts (for scheduled invocation) |
| `GET /healthz` | Liveness |

Service-to-service auth for the API is an open decision (section 11); v1 uses a shared bearer behind an interface.

---
