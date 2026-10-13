# Phased task plan and quality gates

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Phased task plan

Order matters; no schedule is implied. **Per-component rule (constitution 14):** define the abstract base class and its contract test suite first, then the reference implementation, then register it with the factory. Each phase ends with a **checkpoint**: summarise what was built, requirement coverage, deviations, and open questions, then wait for the owner.

### Phase 0: Bootstrap and gate
- T-001 Initialise `uv` project, `ruff`, `mypy --strict`, `pytest`, `pre-commit`, CI workflow.
- T-002 Split this document into the repo files in section 0.
- T-003 README skeleton with the disclaimer block and attribution (link to the paper, no copied content).
- T-004 Traceability tooling: `req` pytest marker, `pytest --req-report` writing `conformance/matrix.yaml`, `scripts/check_traceability.py` failing when a `[PAPER]` requirement lacks a test.
- T-005 Create base-class modules for every extension point in section 1A with `Condition:` docstrings, the `ComponentRegistry` and `register` decorator, `ComponentFactory`, and the composition root `build_runtime(config)` with a sample `runtime.yaml`. Implementations arrive in later phases.
- T-006 Contract-suite scaffolding: parametrised fixtures that discover every registered implementation of an abstract class.
- **Gate G0 (resolved by owner, D7):** private-person project; no client or employer information is involved. Constitution rule 6 still applies: nothing derived from any real engagement or organisation.
- **Checkpoint P0.**

### Phase 1: Contracts and primitives (ENV)
- T-101 Pydantic models for envelope, action, trace, context, provenance.
- T-102 Export JSON Schemas to `schemas/`; CI fails on drift.
- T-103 RFC 8785 canonicalisation and hashing; verify against published test vectors (check for a vetted library first).
- T-104 Ed25519 sign/verify helpers; key loading from files or env; test keys generated at test time.
- T-105 Completeness and coherence validators per SG-08.
- **Acceptance:** ENV-01..06 tests pass; identical inputs always hash identically.

### Phase 2: Agent identity (IDN)
- T-201 `AgentRecord` model; `AgentRegistry` interface; `FileRegistry` (YAML).
- T-202 `MultiRegistry` with authoritative-registry selection by `network_context` (config map).
- T-203 `IdentityVerifier`: resolve, check status, verify adapter signature (native) or gateway-attested identity; reason-coded `IdentityRejection`.
- **Acceptance:** IDN-01..06; rejection tested to occur before any controls retrieval.

### Phase 3: Controls repository and mandates (CTL)
- T-301 Models: `Control`, `Mandate`, `ControlBundle` with manifest hash.
- T-302 YAML loader with JSON Schema validation; production mode refuses non-approved controls.
- T-303 `ControlsRepository.retrieve(identity, action)` selecting by action type, agent class, source.
- T-304 Mandate validation: validity period, principal signature, revocation, delegation depth.
- T-305 `ControlEvaluator` abstract class and registry of control kinds (the Rego evaluator in T-405 plugs in here).
- **Acceptance:** CTL-01..07.

### Phase 4: Disposition engine (DSP)
- T-401 Evaluators: authorisation, exposure (per-action, aggregate), rate, evidence quality, validity.
- T-402 Risk profile from calibration file (reversibility, materiality, customer impact, regulatory sensitivity, novelty).
- T-403 Resolution with DSP-06 precedence; `evaluate(envelope, identity, controls, state_snapshot, signals) -> Disposition` as a pure function.
- T-404 Property tests (Hypothesis): determinism (DSP-07); monotonicity (raising financial materiality with everything else fixed never yields a less restrictive outcome); no authority carry-forward across steps (DSP-05).
- T-405 (optional extra `[rego]`, light integration, D4) `RegoControlEvaluator(ControlEvaluator)`. A control with `logic.type: rego` references a `.rego` file in the control bundle. Evaluation passes `{envelope, identity, mandate, state_snapshot, signals}` as input to OPA and expects `{effect, reason_codes}` back. Keep the integration minimal: call the OPA binary (`opa eval`) per evaluation, or its REST API if the binary route proves awkward. Verify current OPA documentation first and record the choice in an ADR. Ship two or three example Rego controls (authorisation, exposure) that mirror the built-in YAML controls, plus **parity tests**: the same scenarios produce identical dispositions through the built-in and Rego evaluators. Tests carry a `rego` marker and are skipped when `opa` is not installed; default CI does not require it. No Wasm, no bundling, no policy-management features.
- **Acceptance:** DSP-01..07.
- **Checkpoint P4:** demo the engine in a notebook or CLI over sample envelopes.

### Phase 5: Audit log (AUD)
- T-501 `AuditEntry`, `AuditStore` interface (`append(entry, expected_head)`, `read_stream`, `head`).
- T-502 In-memory and SQLite stores; hash chain; `verify()`.
- T-503 JSONL export; `AnchorSink` interface with a file implementation.
- T-504 Tamper tests: modified row, deleted row, reordered rows, truncated tail all detected.
- **Acceptance:** AUD-01..06.

### Phase 6: Decision service, state, escalation (ESC)
- T-601 `StateStore` interface: atomic `reserve` (fixed windows, keys by agent/principal), escalation records, consumed-token set; in-memory and SQLite.
- T-602 `DecisionService.decide()`: validate → identity → retrieve → evaluate → reserve → audit → respond, with per-stage timings, idempotency, fail-closed wrapper. If audit append fails after reserve, release the reservation and fail closed.
- T-603 Escalation manager: states `PENDING → APPROVED / MODIFIED / DECLINED / TIMED_OUT`; reviewer authority check against reviewer role and limit; timeout default (block or senior reviewer); volume cap (ESC-06); modify re-enters the pipeline (ESC-05).
- T-604 FastAPI service with the endpoints in section 6; OpenTelemetry spans and metrics.
- T-605 Shared contract test suites for `StateStore` and `AuditStore`.
- T-606 `Authenticator` abstract class (D5). `BearerTokenAuthenticator`: static role-scoped tokens from config or env, roles `submit`, `consume`, `review`, `admin`. `UnsafeNoAuthenticator`: tests only, refuses to start outside test mode. FastAPI dependency `require_role`. Reviewer resolution additionally checks the reviewer's identity and authority limit from `reviewers.yaml` (ESC-04). mTLS and OIDC are described in `docs/production-gaps.md` and not built.
- **Acceptance:** ESC-01..06, INT-05, ENV-06.
- **Checkpoint P6:** end-to-end decision via HTTP against the in-memory stack.

### Phase 7: Decision tokens (INT-04)
- T-701 Token issue and verify (EdDSA JWS), claims per section 6, behind the `TokenService` abstract class. Key rotation is documented in `docs/production-gaps.md`, not built.
- T-702 Atomic one-time consume through `StateStore`.
- T-703 Tests: replay, expiry, wrong agent, action-hash mismatch, tampered signature.

### Phase 8: Native adapters (INT-01, INT-06)
- T-800 Core client with two modes: embedded (in-process, no network hop) and HTTP.
- T-801 Generic `governed_tool` decorator/wrapper.
- For each framework below: **first** read the official documentation for the exact interception API at a pinned version and write `docs/adapters/<framework>.md` (hook name, signature, version, limits, how outcomes map). **Then** implement and test with a fake runtime, plus one real-framework integration test behind an extras marker.
  - T-810 Claude Agent SDK (candidate: pre-tool-use hook; verify)
  - T-820 LangGraph / LangChain (candidate: agent middleware; verify)
  - T-830 OpenAI Agents SDK (candidate: tool guardrail; verify)
  - T-840 Google ADK (optional)
- Outcome mapping for all adapters: Deny → block with structured reason; Escalate → structured pending result with `escalation_id`; Auto-Execute/Observe → proceed and attach token to the outbound call context.
- T-850 Action-trace capture from framework events; OpenTelemetry GenAI mapping (check current convention status first).
- **Acceptance:** INT-01, INT-06; per-adapter contract tests.

### Phase 9: Gateway adapters (INT-02, INT-04)
- T-901 MCP gateway: intercept `tools/call` over the MCP HTTP transport; config maps tool names to action types and extracts parameters; identity from credentials (mTLS or JWT claim mapping). **First verify the current MCP specification and transport** and record findings in `docs/adapters/mcp.md`.
- T-902 HTTP egress gateway (ASGI reverse proxy): route config maps method/path to action type, JSONPath for parameter extraction.
- T-903 Both modes (standalone, hybrid) for both gateways; Deny and Escalate return structured errors with `reason_codes` / `escalation_id`.
- T-904 Gateways are stateless, configured by env/files, fail closed.
- T-905 Tests against a mock upstream: token required and valid, missing token, mismatched hash, replay, forged envelope in standalone mode.
- **Acceptance:** INT-02, INT-04, T1-T4 scenarios.

### Phase 10: Demo and conformance
- T-1001 "Example Bank" mock rails: in-memory ledger that executes only with a valid token in hybrid mode.
- T-1002 Scripted deterministic agents (no LLM required) for treasury and payments actions; optional LLM-driven example later.
- T-1003 Scenario runner implementing S01-S18 (section 9) end to end through both integration patterns.
- T-1004 Generate the conformance matrix from `@req` markers; publish as `docs/conformance.md`.
- T-1005 Diagrams (Mermaid, our own).
- T-1006 `docs/extending.md` with the worked example from section 1A.
- T-1007 `docs/production-gaps.md`, including the Authenticator production options (mTLS, OIDC).
- **Acceptance:** all scenarios pass; every `[PAPER]` ID covered.
- **Checkpoint P10.**

### Phase 11: Packaging and portability (reference only, no cloud target, D2)
- T-1101 Multi-stage Dockerfile (non-root), compose file, env-driven config, health checks.
- T-1102 Keep the service stateless and ASGI-based so it can run behind any serverless or container runtime; no provider-specific code or IaC in this repo.
- T-1103 (optional) Postgres implementations of `StateStore` and `AuditStore` as a second, networked implementation that shows the contracts are not tied to SQLite, passing the shared contract suites (conditional write on stream head for the hash chain; atomic counters).
- T-1104 `docs/deployment.md`: how the design maps onto serverless (stateless compute, external state, sweeper invoked by any scheduler, minimum-instances consideration for the decision path). Considerations only; do not assert provider limits from memory.
- T-1105 `POST /v1/escalations/sweep` documented as the scheduler hook; compose file includes a simple scheduled caller for local use.

### Phase 12: Publication prep
- T-1201 README (what, why, unofficial disclaimer, attribution, quickstart), `LIMITATIONS.md` ("demo only, not production-grade, not certified, not regulatory guidance").
- T-1202 `docs/spec-gaps.md` only. No issue drafts and no outreach (D6).
- T-1203 `CONTRIBUTING.md`, `SECURITY.md`, licence file (decision D1).
- T-1204 Release checklist: G0 cleared, secrets scan, dependency audit, wording check against constitution rule 5, fictional-data check, CI green.

---

## Quality gates (CI)

- `ruff`, `mypy --strict`, `pytest` with coverage ≥ 90% on `arg/core`.
- Traceability check: every `[PAPER]` requirement has at least one test marked with its ID.
- JSON Schema drift check.
- Contract suites run against every `StateStore` / `AuditStore` implementation.
- `pip-audit` and a secrets scan.
- Wording lint: fails the build on forbidden phrases ("compliant with SAFR", "certified", "official", "MAS requires") in docs and README.

---
