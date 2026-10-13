# Docking an agent framework

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Status (read this first)

| Item | Status |
|---|---|
| Framework-specific adapters (Claude Agent SDK, LangGraph/LangChain, OpenAI Agents SDK, Google ADK) | **Not implemented.** Deliberately skipped by the owner's decision of 2026-10-14. No code in this repo touches any of those frameworks, and nothing here has been tested against them. |
| Docking point (`arg.adapters`) | **Implemented and tested** against a fake framework: `NativeAdapter` template, `GovernanceClient` (embedded and HTTP), `TraceRecorder`, OTel GenAI span mapping. |
| Generic wrapper (`governed_tool`) | **Implemented and tested** for plain sync/async Python callables. |
| Gateway interception (no agent code change) | Phase 9, separate mechanism (`docs/spec/architecture.md`). |

What is proven: the contract an adapter author codes against (INT-01), fail-closed behaviour
(INT-05), outcome mapping, token attachment, and the ordering guardrail → governance → rail
(INT-03). What is **not** proven: that any real framework's hook can host it. That is exactly
the work left for whoever docks a framework.

## The contract

```
framework event ──► build_envelope(event) ──► [sign] ──► GovernanceClient.decide() ──► decision
                                                                                         │
 framework behaviour ◄── enforce(result, event) ◄── allow / block / pending ◄────────────┘
```

You implement two hooks on `arg.adapters.NativeAdapter`; everything else is a template method
you should not override:

| You implement | Purpose |
|---|---|
| `build_envelope(event) -> Envelope` | Map the framework's tool-call/step event to an unsigned envelope: `action` (type, scope, parameters), `action_trace` (steps so far), `context` (agent id, mandate ref, signals). |
| `enforce(result, event)` | (Optional override.) How to stop or park the action natively. Default raises `ActionBlocked` / returns `PendingAction`. |

Provided by the base class and not skippable:

* `guard(event)` signs the envelope with the agent-instance key, asks the core, and **never
  raises**: any failure to get a decision yields a `block` with `ADAPTER_NO_DECISION` (INT-05).
* `run(event, execute)` calls `execute(result)` only for `allow` (Auto-Execute / Observe).
* Mapping: Deny → `block`; Escalate with an `escalation_id` → `pending`;
  Auto-Execute/Observe → `allow` carrying `result.token`; anything else → `block`.
  `require_token=True` (hybrid mode) turns an allow without a token into a block.

## Wiring recipe

1. **Identity.** Register the agent in the registry with the public key of the instance that
   will sign (`config/agents.yaml`, `public_keys`). Native envelopes are authenticated against
   it (ENV-04); the signer lives in the agent process, so a compromised process shares that
   trust boundary. Hybrid mode (a gateway or rail that demands the token) is the mitigation.
2. **Client.** In-process: `EmbeddedClient(runtime.decision_service)`. Remote:
   `HttpClient("https://…", token)` with a `submit`-role bearer token.
3. **Hook.** Put `adapter.run(event, execute)` (or `guard` + your own control flow) in the
   framework's *pre-execution* hook for tools, so the answer exists before the tool runs.
4. **Trace.** Feed `TraceRecorder.record(...)` from framework events (or
   `arg.adapters.otel_genai.step_from_span` from GenAI spans) so envelopes carry what the agent
   did so far. Validation can require a non-empty trace per action type.
5. **Token.** Pass `result.token` to the rail/gateway call. A rail in hybrid mode redeems it via
   `POST /v1/tokens/consume` with the observed action hash (`arg.core.tokens.service.action_hash`).
6. **Pending.** On `pending`, surface `escalation_id` to the agent/user; a reviewer resolves via
   `/v1/escalations/{id}/resolution`; on approval the agent retries with the token from the
   resolution response.

Minimal example (see `tests/adapters/test_docking.py` for a complete fake framework):

```python
class MyFrameworkAdapter(NativeAdapter):
    def build_envelope(self, event):  # framework event -> Envelope
        ...
    def enforce(self, result, event):  # optional: framework-native refusal
        return {"is_error": True, "reasons": list(result.reason_codes)}


adapter = MyFrameworkAdapter(EmbeddedClient(runtime.decision_service), signer=agent_key)
# inside the framework's pre-tool hook:
return adapter.run(event, execute=lambda result: real_tool(**args, token=result.token))
```

For plain callables, `governed_tool` does all of the above:

```python
@governed_tool(adapter, action_type="payment.initiate", scope="account:ACME-001")
def pay(amount: float, currency: str = "USD", decision_token: str | None = None): ...
```

## Candidate interception points (unverified)

These come from the project plan, written before any framework docs were read. **They have not
been checked against current framework documentation or versions.** Verify each before use
and record findings in a `docs/adapters/<framework>.md` file.

| Framework | Candidate hook (unverified) |
|---|---|
| Claude Agent SDK | pre-tool-use hook |
| LangGraph / LangChain | agent middleware around tool calls |
| OpenAI Agents SDK | tool guardrail |
| Google ADK | callback before tool execution |

## What an adapter author should test

Copy the pattern in `tests/adapters/test_docking.py`: the tool body does not run on Deny,
Escalate, or when the core is unreachable; it runs after an allow with the token; the decision
exists in the audit log; `build_envelope` output passes `validate_envelope` for your action
types.

## Where this sits (INT-03)

Governance runs *after* content filtering and guardrails and *before* execution; it neither
inspects content nor replaces the rail's own checks. `test_governance_sits_between_guardrail_
and_rail_and_replaces_neither` demonstrates the ordering.
