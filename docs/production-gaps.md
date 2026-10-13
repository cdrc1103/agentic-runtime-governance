# What a production deployment would additionally need

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.
> This repository is a readable, traceable reference. Everything below is **not built** and
> is listed so nobody mistakes the reference for a product.

## Not built, by design (reference scope)

| Area | Gap |
|---|---|
| Availability | No high availability, failover, or health-based routing. Stores are single-process (in-memory, SQLite). A `PostgresStateStore` / `PostgresAuditStore` would be the first step; the contract suites exist to qualify them. Not implemented. |
| Scale and performance | No tuning, connection pooling, batching, or load testing. The Rego evaluator starts one `opa` process per control per decision. |
| Key management | Keys are PEM files or environment variables. No HSM/KMS, no rotation, no key IDs beyond an optional `kid`, no revocation list for agent-instance or token keys. Token verification trusts exactly one key. |
| Secrets | Bearer tokens come from config/env. No secret manager integration, no token rotation or expiry for API credentials. |
| Multi-tenancy | One institution per deployment; no tenant isolation of state, audit, or controls. |
| Database migrations | SQLite schemas are created on first use; no versioned migrations. |
| API protection | No TLS termination, rate limiting, request size limits, or WAF. No parsing hardening beyond schema validation and JCS's integer range. |
| API authentication | `BearerTokenAuthenticator` only (static role-scoped tokens). mTLS and OIDC/JWT are **not built**; implement `Authenticator` / `IdentityResolver`. Gateways map static bearer tokens to agents; mTLS and JWT claim mapping are not built. |
| Reviewer experience | API only: no UI, notifications, assignment, SLAs, or out-of-band reviewer authentication (the API trusts the reviewer's bearer token). |
| Operations | No runbooks, SLOs, alert rules, dashboards, or on-call. Telemetry exports spans/metrics through the OpenTelemetry API only. |

## Known limits of the reference design

* **Native envelopes share a trust boundary with the agent process.** The adapter signs with an
  agent-instance key held in that process; a compromised agent can sign fabricated envelopes.
  Hybrid mode (a gateway or rail that demands a decision token) is the mitigation, not a
  cure. Documented in `docs/spec/spec-gaps.md` (SG-02).
* **Audit anchoring is manual/scheduled by the operator.** A hash chain alone cannot reveal
  truncation; the anchor sink must be a separate trust domain, written periodically (see
  `POST /v1/audit/{agent}/anchor`). The file sink is a stand-in. No retention or archival policy.
* **No cross-store transaction.** Reservation, audit append, and idempotency record are
  separate writes. Failure handling releases reservations and fails closed, but a crash between
  steps can leave a counter high (conservative) or an idempotency record missing.
* **Reviewer "modify" re-entry trusts the service process** (`internal_identity`, ADR-0014);
  it is not reachable over the API, but a compromised service could misuse it.
* **Tokens are stored in the idempotency record** so duplicate submissions return the same
  token; they are short-lived (default 300 s) and one-time, but are present in the state store.
* **Clock trust.** Validity windows, token expiry and escalation deadlines use the service
  clock; there is no clock-skew handling or secure time source.
* **Gateway blind spots.** A gateway sees the call, not the reasoning: agent-reported signals
  (confidence, anomaly score) are unavailable, so evidence controls need native adapters or
  operator-asserted static signals. SSE is passed through but not inspected. Legacy session
  traffic is forwarded uninterpreted. Batched `tools/call` is refused.
* **Evidence of correctness is test-based.** The conformance suite shows each requirement and
  scenario has a test in this repo; it is not an independent assessment.
* **Framework adapters are not shipped** (`docs/adapters/README.md`); no real agent framework
  has been tested against the docking point.
* **Risk calibration is deliberately simple** (ADR-0012): an additive ordinal score. Real
  institutions would calibrate with richer, validated models behind `RiskCalibrator`.
* **Numbers.** RFC 8785 refuses integers beyond ±(2^53−1); monetary amounts should travel as
  strings or integers within range.

## If you take this further

1. Replace stores with Postgres (contract suites first), run the gateways behind a real
   ingress with mTLS, and move keys to a KMS.
2. Put the anchor sink in another account/tenant, schedule anchoring, and verify on a schedule.
3. Build reviewer tooling and wire notifications to the sweeper's timeouts.
4. Have your risk and compliance owners review every control and the calibration file; the
   sample bundle is fictional and illustrative only.
