"""MCP gateway: intercepts ``tools/call`` on the Streamable HTTP transport (T-901).

Behaviour verified against MCP revision 2026-07-28 (see ``docs/adapters/mcp.md``):
one JSON-RPC request per POST, single endpoint, reply as JSON or SSE, mirrored
``Mcp-Method`` / ``Mcp-Name`` headers that must match the body. The body is the source of
truth; header/body mismatches are refused with HTTP 400 and error ``-32020``.
"""

import base64
import json
from typing import Any

from arg.core.registry import register
from arg.gateway.base import (
    GatewayAdapter,
    GatewayRequest,
    Passthrough,
    Rejection,
    Respond,
)
from arg.gateway.core import ActionMapping, GatewayEngine, Observation, Verdict
from arg.gateway.identity import IdentityResolver

HEADER_MISMATCH = -32020
_JSON = {"content-type": "application/json"}


def _decode_header_value(value: str) -> str:
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[len("=?base64?") : -2]).decode("utf-8")
    return value


def _rpc_error(request_id: Any, code: int, message: str) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    ).encode()


@register(GatewayAdapter, "mcp")
class McpGateway(GatewayAdapter):
    """Governs ``tools/call``; everything else (list, initialize, ...) passes through."""

    def __init__(
        self,
        engine: GatewayEngine,
        identity: IdentityResolver,
        tools: dict[str, Any],
        passthrough_tools: list[str] | None = None,
    ) -> None:
        """``tools``: tool name -> mapping; unmapped tools are refused unless passthrough."""
        super().__init__(engine, identity)
        self.tools = {k: ActionMapping.model_validate(v) for k, v in tools.items()}
        self.passthrough_tools = set(passthrough_tools or [])

    def observe(self, request: GatewayRequest) -> Observation | Passthrough | Rejection:
        """Parse one JSON-RPC message; only ``tools/call`` is governed."""
        if request.method != "POST":
            return Passthrough()  # GET/DELETE belong to legacy transports; upstream decides
        try:
            message = json.loads(request.body)
        except ValueError:
            return Rejection("parse_error", "body is not JSON")
        if isinstance(message, list):  # batching: removed from the spec, refuse if it hides calls
            if any(isinstance(m, dict) and m.get("method") == "tools/call" for m in message):
                return Rejection("batch_not_supported", "batched tools/call is not governable")
            return Passthrough()
        if not isinstance(message, dict):
            return Rejection("invalid_request", "body is not a JSON-RPC object")
        if message.get("method") != "tools/call":
            return Passthrough()
        rid = message.get("id")
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return Rejection("invalid_params", "params.name is required", status=200)
        name: str = params["name"]
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return Rejection("invalid_params", "arguments must be an object", status=200)
        header_method = request.headers.get("mcp-method")
        if header_method is not None and header_method != "tools/call":
            return Rejection("header_mismatch", "Mcp-Method does not match body")
        header_name = request.headers.get("mcp-name")
        if header_name is not None:
            try:
                decoded = _decode_header_value(header_name)
            except ValueError:
                return Rejection("header_mismatch", "Mcp-Name is not valid base64")
            if decoded != name:
                return Rejection("header_mismatch", "Mcp-Name does not match body")
        if name in self.passthrough_tools:
            return Passthrough()
        mapping = self.tools.get(name)
        return Observation(
            label="tools/call",
            target=name,
            mapping=mapping,
            document={"name": name, "arguments": arguments, "params": params},
            request_id=rid,
        )

    def render_rejection(self, rejection: Rejection, request: GatewayRequest) -> Respond:
        """JSON-RPC error; header mismatch uses the spec's -32020 and HTTP 400."""
        rid = None
        try:
            parsed = json.loads(request.body)
            rid = parsed.get("id") if isinstance(parsed, dict) else None
        except ValueError:
            pass
        code = {
            "header_mismatch": HEADER_MISMATCH,
            "parse_error": -32700,
            "invalid_request": -32600,
            "batch_not_supported": -32600,
            "invalid_params": -32602,
        }.get(rejection.code, -32600)
        return Respond(rejection.status, _rpc_error(rid, code, rejection.detail), dict(_JSON))

    def render_refusal(
        self, obs: Observation, verdict: Verdict, request: GatewayRequest
    ) -> Respond:
        """A tool execution error (``isError: true``): the model can read and react to it."""
        pending = verdict.outcome == "escalate" and verdict.escalation_id
        text = (
            f"Action held for human review (escalation {verdict.escalation_id}); it was not executed."
            if pending
            else f"Action refused by governance: {', '.join(verdict.reason_codes) or verdict.outcome}."
        )
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": True,
            "structuredContent": {
                "governance": {
                    "outcome": verdict.outcome,
                    "reason_codes": list(verdict.reason_codes),
                    "decision_id": verdict.decision_id,
                    "escalation_id": verdict.escalation_id,
                }
            },
        }
        if request.headers.get("mcp-protocol-version", "") >= "2026-07-28":
            result = {"resultType": "complete", **result}
        body = json.dumps({"jsonrpc": "2.0", "id": obs.request_id, "result": result}).encode()
        return Respond(200, body, dict(_JSON))

    def render_unauthenticated(self, request: GatewayRequest) -> Respond:
        """HTTP 401 with a JSON-RPC error body."""
        rid = None
        try:
            rid = json.loads(request.body).get("id")
        except (ValueError, AttributeError):
            pass
        return Respond(
            401,
            _rpc_error(rid, -32001, "authentication required"),
            {**_JSON, "www-authenticate": "Bearer"},
        )
