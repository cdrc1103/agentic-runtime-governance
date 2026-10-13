# Gateways: standalone and hybrid

Both gateways (`arg.gateway.mcp.McpGateway`, `arg.gateway.http_egress.HttpEgressGateway`)
share one decision engine (`GatewayEngine`) and one ASGI proxy (`create_gateway_app`).

| | Standalone | Hybrid |
|---|---|---|
| Envelope | Built by the gateway from the **observed** call (authentic by construction; identity from credentials) | Not built; the native adapter already asked the core |
| Gateway needs | Decision API (`submit` role) | Token redemption (`consume` role) |
| Allows when | Core says Auto-Execute / Observe | A valid, unexpired, unconsumed token whose `act_hash` and subject match the observed call |
| Covers | Agents with no instrumentation | Agents with instrumentation, **plus** bypass and TOCTOU protection (INT-04) |
| Trace | One step: the observed call (thin by design) | Rich trace came from the native envelope |

Mapping contract for hybrid: the native adapter and the gateway must map the call to the
**same** `(action_type, scope, parameters)`; `action_hash` is `SHA-256(JCS(...))` of those
three. A mismatch means every call is refused, which is the safe failure.

## Things that follow from the design

* A gateway sees the call, not the reasoning. Controls that need agent-reported signals (for
  example evidence confidence) cannot be satisfied from a gateway; either scope them to native
  agents with `applies_to`, or let the operator assert static `signals` in the mapping (never
  agent-reported; documented as a [DESIGN] choice).
* A submit-role caller cannot claim to be a gateway: the API requires
  `provenance.adapter_id == authenticated principal` for gateway-origin envelopes, and the core
  only accepts adapter ids in `trusted_gateways`.
* Default deny: unmapped tools/routes are refused; passthrough must be explicit.
* Stateless: no per-request state; scale horizontally behind any load balancer.
* Fail closed: core unreachable, token backend unreachable, any exception → refusal, never a
  forward. An upstream failure *after* an allow is a 502 (the decision is still audited).
