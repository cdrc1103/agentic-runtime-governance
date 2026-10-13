"""MCP gateway demo (fictional Example Bank): governance with no agent code changes.

A toy upstream "MCP server" sits behind the gateway. Standalone mode decides on the observed
call; hybrid mode demands a one-time decision token from the agent's native decision.
Everything runs in-process (ASGI), no network. Not regulatory guidance; demo only.

Run: ``uv run python -m demo.gateway_demo``
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx2
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from arg.adapters.client import EmbeddedClient
from arg.gateway.app import create_gateway_app
from arg.gateway.backend import EmbeddedRedeemer
from arg.gateway.core import GatewayEngine
from arg.gateway.identity import StaticBearerIdentityResolver
from arg.gateway.mcp import McpGateway
from demo.example_bank import ExampleBank, build_example_bank, payment_envelope

CREDENTIALS = {
    "agent-credential": {
        "agent_id": "treasury-agent-1",
        "mandate_ref": "mandate-1",
        "network_context": "internal",
    },
    "ghost-credential": {
        "agent_id": "ghost-agent",
        "mandate_ref": "mandate-1",
        "network_context": "internal",
    },
}
WIRE = {
    "action_type": "payment.initiate",
    "scope": "account:{arguments.account}",
    "parameters": {
        "amount": "arguments.amount",
        "currency": "arguments.currency",
        "beneficiary": "arguments.beneficiary",
    },
    "signals": {"confidence": 0.95},
}


def toy_mcp_server(executed: list[str]) -> Starlette:
    """An upstream that "executes" wire transfers and records that it did."""

    async def endpoint(request: Request) -> JSONResponse:
        msg = json.loads(await request.body())
        if msg.get("method") == "tools/call":
            executed.append(json.dumps(msg["params"]["arguments"], sort_keys=True))
            text = f"wired {msg['params']['arguments']['amount']}"
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"content": [{"type": "text", "text": text}]},
                }
            )
        return JSONResponse({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"tools": []}})

    return Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])


def gateway(bank: ExampleBank, mode: str, executed: list[str]) -> TestClient:
    """A gateway over the bank's core and the toy upstream."""
    svc = bank.runtime.decision_service
    assert svc is not None
    engine = GatewayEngine(
        "gateway-1",
        mode,  # type: ignore[arg-type]
        client=EmbeddedClient(svc),
        redeemer=EmbeddedRedeemer(
            bank.runtime.components["token_service"],
            bank.runtime.components["state_store"],
            bank.clock,
        ),
        clock=bank.clock,
    )
    adapter = McpGateway(
        engine, StaticBearerIdentityResolver(CREDENTIALS), tools={"wire_transfer": WIRE}
    )
    upstream = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=toy_mcp_server(executed)), base_url="http://upstream"
    )
    return TestClient(create_gateway_app(adapter, "http://upstream", client=upstream))


def main() -> None:
    """Narrate standalone, then hybrid."""
    bank = build_example_bank(Path(tempfile.mkdtemp(prefix="arg-gw-")))
    executed: list[str] = []
    n = 0

    def call(
        client: TestClient,
        amount: float,
        *,
        who: str = "agent-credential",
        token: str | None = None,
        account: str = "ACME-001",
    ) -> str:
        nonlocal n
        n += 1
        headers = {
            "authorization": f"Bearer {who}",
            "content-type": "application/json",
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "tools/call",
            "mcp-name": "wire_transfer",
        }
        if token:
            headers["x-arg-decision-token"] = token
        body = {
            "jsonrpc": "2.0",
            "id": n,
            "method": "tools/call",
            "params": {
                "name": "wire_transfer",
                "arguments": {
                    "account": account,
                    "amount": amount,
                    "currency": "USD",
                    "beneficiary": "vendor-17",
                },
            },
        }
        before = len(executed)
        r = client.post("/mcp", content=json.dumps(body), headers=headers).json()
        if "error" in r:
            return f"HTTP-level refusal: {r['error']['message']}"
        if len(executed) > before:
            return f"EXECUTED upstream -> {r['result']['content'][0]['text']}"
        gov = r["result"]["structuredContent"]["governance"]
        return f"REFUSED ({gov['outcome']}): {', '.join(gov['reason_codes'])}"

    print("== standalone: the gateway decides on the observed call")
    standalone = gateway(bank, "standalone", executed)
    for label, kw in [
        ("500 within limits", {"amount": 500}),
        ("20,000 above limit", {"amount": 20000}),
        ("500 from unregistered agent", {"amount": 500, "who": "ghost-credential"}),
        ("500, no credential", {"amount": 500, "who": "nobody"}),
    ]:
        print(f"  {label:<30} {call(standalone, **kw)}")  # type: ignore[arg-type]
    print(f"  upstream executions so far: {len(executed)}")

    print("\n== hybrid: the gateway requires a one-time token matching the observed call")
    hybrid = gateway(bank, "hybrid", executed)
    print(f"  no token                       {call(hybrid, 500)}")
    # the agent's own (native) decision for exactly this action earns a token
    raw = payment_envelope(bank, 500, envelope_id="native-1")
    decision: Any = bank.runtime.decision_service.decide(raw)  # type: ignore[union-attr]
    token = decision.token
    print(f"  native decision                {decision.outcome} (token issued)")
    print(f"  token, altered amount (900)    {call(hybrid, 900, token=token)}")
    print(f"  token, different account       {call(hybrid, 500, token=token, account='EVIL-1')}")
    print(f"  token, exact action            {call(hybrid, 500, token=token)}")
    print(f"  same token again (replay)      {call(hybrid, 500, token=token)}")
    print(f"\n  upstream executions in total: {len(executed)}")


if __name__ == "__main__":
    main()
