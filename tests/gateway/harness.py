"""Gateway test harness: in-process upstream, gateway app, Example Bank core."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from arg.adapters.client import EmbeddedClient
from arg.gateway.app import create_gateway_app
from arg.gateway.backend import EmbeddedRedeemer
from arg.gateway.core import GatewayEngine
from arg.gateway.http_egress import HttpEgressGateway
from arg.gateway.identity import StaticBearerIdentityResolver
from arg.gateway.mcp import McpGateway
from tests.service.world import World, build_world

CREDS = {
    "agent-tok": {
        "agent_id": "treasury-agent-1",
        "mandate_ref": "mandate-1",
        "network_context": "internal",
    },
    "expired-tok": {
        "agent_id": "treasury-agent-1",
        "mandate_ref": "mandate-exp",
        "network_context": "internal",
    },
}
WIRE = {
    "action_type": "payment.initiate",
    "scope": "account:{arguments.account}",
    "parameters": {"amount": "arguments.amount", "currency": "arguments.currency"},
    "signals": {"confidence": 0.95},
}


@dataclass
class Upstream:
    """Records what reached the upstream and answers like a tiny MCP / REST server."""

    seen: list[dict[str, Any]] = field(default_factory=list)

    def app(self) -> Starlette:
        """ASGI app."""

        async def mcp(request: Request) -> Response:
            body = await request.body()
            self.seen.append(
                {
                    "path": request.url.path,
                    "method": request.method,
                    "headers": {k.lower(): v for k, v in request.headers.items()},
                    "body": body,
                }
            )
            msg = json.loads(body) if body else {}
            if isinstance(msg, dict) and msg.get("method") == "tools/call":
                if msg["params"]["name"] == "stream_tool":

                    async def events() -> Any:
                        yield b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
                        yield (
                            b'event: message\ndata: {"jsonrpc":"2.0","id":%d,"result":{"content":[]}}\n\n'
                            % msg["id"]
                        )

                    return StreamingResponse(events(), media_type="text/event-stream")
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "result": {"content": [{"type": "text", "text": "EXECUTED"}]},
                    }
                )
            if isinstance(msg, dict) and "id" in msg:
                return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": []}})
            return Response(status_code=202)

        async def rest(request: Request) -> Response:
            body = await request.body()
            self.seen.append(
                {
                    "path": request.url.path,
                    "method": request.method,
                    "headers": {k.lower(): v for k, v in request.headers.items()},
                    "body": body,
                }
            )
            return JSONResponse({"executed": True, "path": request.url.path})

        return Starlette(
            routes=[
                Route("/mcp", mcp, methods=["POST", "GET", "DELETE"]),
                Route("/{p:path}", rest, methods=["GET", "POST", "PUT", "DELETE"]),
            ]
        )

    @property
    def calls(self) -> int:
        """Number of requests that reached the upstream."""
        return len(self.seen)


@dataclass
class Rig:
    """A gateway in front of an upstream, wired to the Example Bank core."""

    world: World
    upstream: Upstream
    client: TestClient
    engine: GatewayEngine


def _upstream_client(upstream: Upstream) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=upstream.app()), base_url="http://upstream"
    )


def build_rig(
    tmp: Path,
    *,
    protocol: str = "mcp",
    mode: str = "standalone",
    world: World | None = None,
    core_client: Any = None,
) -> Rig:
    """Assemble core + gateway + upstream."""
    w = world or build_world(tmp)
    assert w.rt.decision_service is not None
    tokens = w.rt.components["token_service"]
    engine = GatewayEngine(
        "gateway-1",
        mode,  # type: ignore[arg-type]
        client=core_client or EmbeddedClient(w.rt.decision_service),
        redeemer=EmbeddedRedeemer(tokens, w.rt.components["state_store"], w.clock),
        clock=w.clock,
    )
    resolver = StaticBearerIdentityResolver(CREDS)
    adapter: Any
    if protocol == "mcp":
        adapter = McpGateway(
            engine,
            resolver,
            tools={"wire_transfer": WIRE, "stream_tool": WIRE},
            passthrough_tools=["get_weather"],
        )
    else:
        adapter = HttpEgressGateway(
            engine,
            resolver,
            routes=[
                {
                    "name": "pay",
                    "method": "POST",
                    "path": "/payments/{account}",
                    "action_type": "payment.initiate",
                    "scope": "account:{path.account}",
                    "parameters": {"amount": "body.amount", "currency": "body.currency"},
                    "signals": {"confidence": 0.95},
                },
                {
                    "name": "pay-q",
                    "method": "POST",
                    "path": "/transfers",
                    "action_type": "payment.initiate",
                    "scope": "account:{query.account}",
                    "parameters": {"amount": "body.amount", "currency": "body.currency"},
                    "signals": {"confidence": 0.95},
                },
                {"name": "health", "method": "GET", "path": "/health", "passthrough": True},
            ],
        )
    up = Upstream()
    app = create_gateway_app(
        adapter,
        "http://upstream",
        client=_upstream_client(up),
        upstream_headers={"x-upstream-key": "gw-secret"},
    )
    return Rig(w, up, TestClient(app), engine)


def call_tool(rid: int, name: str, **arguments: Any) -> dict[str, Any]:
    """A JSON-RPC tools/call request body."""
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def mcp_headers(token: str | None = "agent-tok", **extra: str) -> dict[str, str]:
    """Headers a modern MCP client would send."""
    h = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2026-07-28",
        "mcp-method": "tools/call",
        **extra,
    }
    if token:
        h["authorization"] = f"Bearer {token}"
    return h
