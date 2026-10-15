# Scope and requirements

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Scope and non-goals

**In scope:** the four SAFR runtime components (Agent Identity, Controls Repository, Disposition Engine, Audit Log) plus the Governance Envelope; both integration patterns (native, gateway); human escalation with timeout and reviewer authority; a conformance suite; a demo with mock treasury rails; serverless-ready packaging.

**Non-goals:** content filtering or prompt-injection defence; real payment rails; ML anomaly detection (only a `signals` input); a production reviewer UI (API plus CLI only); any compliance certification; managed-service features (the paper says SAFR is an institution-deployed reference, not a managed service); production hardening (high availability, scaling, performance tuning, key management or rotation, multi-tenancy, database migrations, secrets management), which is documented in `docs/production-gaps.md` and not built.

**Stack defaults** (verify latest stable versions on PyPI before pinning): Python 3.12+, `uv` workspace, `pydantic` v2, `FastAPI`, `httpx`, `cryptography` (Ed25519), `PyYAML` or `ruamel.yaml`, `pytest`, `hypothesis`, `ruff`, `mypy`, OpenTelemetry API/SDK. Layout: repository and distribution name `agentic-runtime-governance`, import package `arg`, optional extras `[service]`, `[langgraph]`, `[claude]`, `[openai]`, `[gateway]`, `[rego]`, plus `demo/` and `conformance/`. The name keeps `safr` out of repo and package names (D3); SAFR appears only in descriptions as the paper this is based on.

---

## Requirements

Section column = the paper section it comes from.

### 3.1 Governance Envelope (ENV)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| ENV-01 | PAPER | Every proposed agent action is packaged in an envelope before execution. No action reaches execution without having been declared, authorised, and assessed. | The SAFR Framework |
| ENV-02 | PAPER | Envelope contains three classes of information: **action** (type, scope, parameters), **action trace** (steps executed, tool calls, data retrieved, checks performed), **context metadata** (agent identity, applicable mandate, current account/system state, operative policy constraints). | Governance Envelope |
| ENV-03 | PAPER | Envelope is validated for completeness and coherence before later stages. | Action Lifecycle |
| ENV-04 | PAPER | The envelope is treated as a document to be authenticated against its origin, not merely as the agent's own report, because action and trace can be fabricated together by an adversarial injection. | Governance Envelope |
| ENV-05 | DESIGN | Envelope schema is versioned; hashing uses RFC 8785 canonical JSON plus SHA-256. | n/a |
| ENV-06 | DESIGN | Submission is idempotent by `envelope_id`: a duplicate returns the original decision and never re-reserves exposure. | n/a |

### 3.2 Agent Identity (IDN)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| IDN-01 | PAPER | Each proposed action is bound to a recognised, registered agent, verified against its registry entry before any other evaluation. | Agent Identity |
| IDN-02 | PAPER | An envelope failing identity verification is rejected at this stage and the rejection is recorded in the audit log. | Agent Identity, Action Lifecycle |
| IDN-03 | PAPER | Closed-loop context: identity resolution is a direct lookup in the institution's own registry. | Agent Identity |
| IDN-04 | PAPER | Open-network context: an agent may be registered in several registries; the component determines which registry is authoritative for the action's context and retrieves the appropriate identifier. | Agent Identity |
| IDN-05 | PAPER | Output is either a confirmed identity binding carried to the Controls Repository, or a recorded rejection. | Agent Identity |
| IDN-06 | DESIGN | Registry entry holds: `agent_id`, agent class, status (active/suspended/revoked), named human principal, public key(s), allowed network contexts. | n/a |

### 3.3 Controls Repository (CTL)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| CTL-01 | PAPER | The repository is the institution's configurable rulebook; controls come from organisational policy, regulatory requirements, product rules, and user-provided mandates. | Controls Repository |
| CTL-02 | PAPER | Controls are generic (apply to any actor, typically deterministic, fixed thresholds or categorical rules) or AI-specific (e.g. evidence quality, envelope integrity; may be probabilistic or semantic). | Controls Repository |
| CTL-03 | PAPER | A mandate is the machine-readable, explicit delegation of authority from a user to an agent: what it may do, within what limits, under what conditions. An agent cannot extend a mandate by its own reasoning or inference. | Controls Repository |
| CTL-04 | PAPER | A control encodes: permitted action types, decision logic (rules and thresholds), escalation conditions, validity period, principal authority (hierarchy from which it derives force, and authority to update or revoke it). | Controls Repository |
| CTL-05 | PAPER | Control categories are independently configurable: **Authorisation** (which agents may act for which principals; who may delegate to whom and to what depth; permitted action types per agent class), **Exposure limits** (per-action and aggregate; below threshold autonomous, above it human review or block; set to mirror existing delegated authority frameworks), **Rate limits** (max action rate per time window), **Evidence quality** (minimum confidence and required evidence; below threshold routed to human review regardless of value). | How Institutions Implement SAFR |
| CTL-06 | PAPER | Control configuration is owned by the institution's risk and compliance leadership. | How Institutions Implement SAFR |
| CTL-07 | DESIGN | Controls are versioned files in a bundle with a manifest hash. Production mode loads only bundles whose controls carry `review_status: approved`. | n/a |

### 3.4 Disposition Engine (DSP)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| DSP-01 | PAPER | The engine evaluates each in-scope action deterministically against the controls retrieved from the repository. | Disposition Engine |
| DSP-02 | PAPER | Every action resolves to exactly one of four outcomes: **Deny** (violates a hard constraint or exceeds risk thresholds; rejected before execution with a recorded reason), **Escalate** (in scope and under hard constraints but above the autonomous threshold; held for human review), **Auto-Execute** (in scope, under hard constraints, within risk thresholds; proceeds), **Observe** (proceeds, while a structured observation is logged for later review; used where a configured pattern or signal warrants attention but not escalation). | Disposition Engine |
| DSP-03 | PAPER | Outcome is calibrated to risk. Calibration factors: action reversibility, financial materiality, customer impact severity, regulatory sensitivity, novelty or anomaly relative to patterns within the mandate. Higher risk shifts toward Deny/Escalate, lower toward Auto-Execute/Observe. | Disposition Engine |
| DSP-04 | PAPER | Calibration (threshold-setting) is defined at design time through governance parameters and is subject to review before deployment. | Disposition Engine |
| DSP-05 | PAPER | In multi-step workflows each action is evaluated independently. An Auto-Execute or Observe at one step grants no authority at the next. | Action Lifecycle |
| DSP-06 | DESIGN | Resolution precedence when several controls fire: Deny > Escalate > Observe > Auto-Execute. | n/a |
| DSP-07 | DESIGN | Determinism: identical (envelope, state snapshot, controls bundle, signals) always yields identical outcome and reasons. | n/a |

### 3.5 Audit Log (AUD)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| AUD-01 | PAPER | Every governance decision produces an audit entry, for every outcome including identity-stage rejections. | Audit Log, Action Lifecycle |
| AUD-02 | PAPER | The log is tamper-evident and append-only. An entry cannot be modified by the agent or any downstream system after it is written. | Audit Log |
| AUD-03 | PAPER | Each entry captures: the envelope as submitted, the mandate checked against, the outcome, the specific rules applied, the basis for the outcome, and the time elapsed at each stage. | Audit Log |
| AUD-04 | PAPER | Every action and decision can be reconstructed and reviewed without relying on the agent's own account. | Audit Log |
| AUD-05 | PAPER | The record is structured so existing compliance platforms (AML/KYC, transaction monitoring, sanctions screening) can consume it. | Audit Log |
| AUD-06 | DESIGN | Per-agent hash chain (`entry_hash = SHA-256(prev_hash ‖ canonical(entry))`), a `verify` tool, JSONL export, and a periodic head anchor written to an external sink. | n/a |

### 3.6 Human escalation (ESC)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| ESC-01 | PAPER | An escalated action is held pending human review before it proceeds. | Disposition Engine |
| ESC-02 | PAPER | The institution assesses how many escalations it can meaningfully review; an escalation function that generates more reviews than can be processed defeats its purpose. | Activating Human Reviewer Escalation |
| ESC-03 | PAPER | Escalations carry a timeout window. With no decision in time, the action defaults to block or goes to a senior reviewer. | Activating Human Reviewer Escalation |
| ESC-04 | PAPER | Reviewers have clear authority to approve, modify, or decline, and their decisions carry the same institutional weight as the original agent decision. Escalating to someone without authority is not effective oversight. | Activating Human Reviewer Escalation |
| ESC-05 | DESIGN | A reviewer's "modify" produces a new action that re-enters the full pipeline as a new envelope with a parent reference. Every reviewer decision is itself an audit entry. | n/a |
| ESC-06 | DESIGN | Configurable cap on open escalations per queue, with queue-depth metrics; beyond the cap new escalations are blocked and the event is logged. | n/a |

### 3.7 Integration (INT)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| INT-01 | PAPER | **Native:** the agent is instrumented to emit an envelope before each proposed action; the validator returns an outcome before the agent acts. | Integration patterns |
| INT-02 | PAPER | **Gateway:** a gateway intercepts outbound API calls at the infrastructure layer, wraps each in an envelope, and evaluates it, with no change to agent code. | Integration patterns |
| INT-03 | PAPER | SAFR sits after content filtering and before execution, and complements (does not replace) guardrails, settlement rails, and compliance engines. | SAFR and Broader Ecosystem |
| INT-04 | DESIGN | **Decision-token binding (hybrid mode):** Auto-Execute/Observe returns a short-lived, one-time, signed token bound to the hash of the action. Gateways and rails can require it, so skipping instrumentation or altering the call after the decision fails. | n/a |
| INT-05 | DESIGN | Fail closed on any decision-path failure. | n/a |
| INT-06 | DESIGN | Native adapters for LangGraph/LangChain, Claude Agent SDK, OpenAI Agents SDK, plus a generic wrapper. OpenTelemetry GenAI span mapping for the action trace. | n/a |


### 3.8 Documentation (DOC)

| ID | Tag | Requirement | Paper section |
|---|---|---|---|
| DOC-01 | DESIGN | The interactive demo page (`docs/demo/index.html`) replays recorded runs of the real engine over fictional data and re-implements no decision logic. Its embedded data is regenerated by `scripts/gen_demo_page.py`, and a test fails if it drifts from the engine. | n/a |
---
