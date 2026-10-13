# MCP gateway: spec findings and behaviour

Checked **2026-10-14** against the MCP specification revision **2026-07-28** (latest at the
time) at `modelcontextprotocol.io/specification/2026-07-28/…` (transports/streamable-http,
server/tools).

## What the spec says (relevant parts)

* One MCP endpoint accepting POST; **one JSON-RPC request or notification per POST**; no
  batching. Replies are `application/json` or a request-scoped `text/event-stream`.
  Notifications are answered `202 Accepted`.
* **Stateless:** this revision removed protocol-level sessions and the standalone GET stream.
  Earlier revisions (2025-03-26 to 2025-11-25) used `Mcp-Session-Id`, GET streams and
  server-initiated requests; 2024-11-05 used the deprecated HTTP+SSE transport.
* Request metadata is mirrored into headers: `MCP-Protocol-Version`, `Mcp-Method`,
  `Mcp-Name` (`params.name` for `tools/call`; Base64 sentinel `=?base64?…?=` for unsafe values),
  and `Mcp-Param-{Name}`. The body is the source of truth; processors **MUST** reject
  mismatches with `400` and JSON-RPC error `-32020` (`HeaderMismatch`).
* `tools/call` carries `params.name` and `params.arguments`. Results are
  `{content[], isError?, structuredContent?, resultType: "complete"}`. Tool *execution* errors
  are results with `isError: true`; protocol errors are JSON-RPC `error` objects.

## How the gateway uses it

| Situation | Behaviour |
|---|---|
| `tools/call` for a mapped tool | Governed. Action built from the mapping and the observed arguments. |
| `tools/call` for a tool in `passthrough_tools` | Forwarded untouched. |
| `tools/call` for an unmapped tool | **Refused** (`GW_UNMAPPED`, default deny). |
| Any other method (`initialize`, `tools/list`, notifications, …) | Forwarded untouched. |
| `Mcp-Method` / `Mcp-Name` disagree with the body | `400`, `-32020`, not forwarded (decision uses the body). |
| JSON array containing a `tools/call` | `400` `-32600`: batching is not governable (not in the spec revision). |
| Unparseable JSON, missing `params.name` | `-32700` / `-32602`, not forwarded. |
| Refusal (Deny/Escalate/no decision) | HTTP 200 with a tool execution error: `isError: true`, `structuredContent.governance{outcome, reason_codes, decision_id, escalation_id}`. `resultType` is added only when `MCP-Protocol-Version >= 2026-07-28`. |
| Upstream answers with SSE | Streamed through unchanged. |
| GET / DELETE | Forwarded (legacy transports); nothing to govern. |

Agent credentials (`Authorization`) and the decision token header never go upstream; static
`upstream_headers` can add the upstream's own credential. The request body forwarded is the
exact byte string that was governed.

## Limits (be honest about them)

* Verified against the spec text, **not** against any particular MCP SDK or server
  implementation; the tests use a hand-written upstream.
* Refusals are returned as tool execution errors so a model can read them. A client that
  ignores `isError` could misread a refusal; the text states the action was not executed.
* Identity is a static bearer-token map. mTLS and JWT claim mapping are not built.
* Legacy-session traffic (`Mcp-Session-Id`) is forwarded transparently but never interpreted.
