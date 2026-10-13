"""Integration patterns for the conformance scenarios: native adapter and MCP gateway.

Each pattern exposes ``submit(...)`` returning the same ``Result`` so a scenario is written
once and run through both (S01-S05, S18-S19, S22 and others).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arg.adapters import EmbeddedClient, GenericToolAdapter, ToolCallEvent
from tests.gateway.harness import Rig, build_rig, call_tool, mcp_headers

TOKEN_FOR = {
    ("treasury-agent-1", "mandate-1"): "agent-tok",
    ("treasury-agent-1", "mandate-exp"): "expired-tok",
    ("treasury-agent-1", "mandate-widened"): "widened-tok",
    ("treasury-agent-2", "mandate-2"): "agent2-tok",
    ("ghost-agent", "mandate-1"): "ghost-tok",
    ("suspended-agent", "mandate-1"): "suspended-tok",
}


@dataclass(frozen=True)
class Result:
    """Pattern-independent view of one submission."""

    outcome: str
    reasons: tuple[str, ...]
    executed: bool
    escalation_id: str | None = None
    token: str | None = None


class NativePattern:
    """Agent process with an in-process adapter (INT-01)."""

    name = "native"

    def __init__(self, tmp: Path) -> None:
        """Build the Example Bank core with a (unused) gateway rig for the world."""
        self.rig = build_rig(tmp)
        self.world = self.rig.world

    def submit(
        self,
        amount: float = 500,
        *,
        agent: str = "treasury-agent-1",
        mandate: str = "mandate-1",
        signals: dict[str, Any] | None = None,
        signed: bool = True,
        account: str = "ACME-001",
    ) -> Result:
        """One payment through a fresh adapter (fresh trace)."""
        w = self.world
        assert w.rt.decision_service is not None
        adapter = GenericToolAdapter(
            EmbeddedClient(w.rt.decision_service),
            agent_id=agent,
            mandate_ref=mandate,
            network_context="internal",
            signer=w.agent_key if signed else None,
            clock=w.clock,
            signals=lambda: signals if signals is not None else {"confidence": 0.95},
        )
        adapter.recorder.record("check", "precheck")
        ran: list[str] = []
        event = ToolCallEvent(
            "payment.initiate", f"account:{account}", {"amount": amount, "currency": "USD"}
        )
        result = adapter.guard(event)
        if result.allowed:
            ran.append("x")
        return Result(
            result.outcome, result.reason_codes, bool(ran), result.escalation_id, result.token
        )


class GatewayPattern:
    """MCP gateway in standalone mode: no agent code, identity from credentials (INT-02)."""

    name = "gateway"

    def __init__(self, tmp: Path) -> None:
        """Build core + gateway + upstream."""
        self.rig: Rig = build_rig(tmp)
        self.world = self.rig.world
        self._rid = 0

    def submit(
        self,
        amount: float = 500,
        *,
        agent: str = "treasury-agent-1",
        mandate: str = "mandate-1",
        signals: dict[str, Any] | None = None,
        signed: bool = True,
        account: str = "ACME-001",
    ) -> Result:
        """One tools/call through the gateway (signals/signing are agent-side, so ignored)."""
        self._rid += 1
        before = self.rig.upstream.calls
        body = call_tool(self._rid, "wire_transfer", account=account, amount=amount, currency="USD")
        r = self.rig.client.post(
            "/mcp", content=json.dumps(body), headers=mcp_headers(TOKEN_FOR[(agent, mandate)])
        )
        executed = self.rig.upstream.calls > before
        payload = r.json()
        if executed:
            return Result("auto_execute", (), True)
        gov = payload["result"]["structuredContent"]["governance"]
        return Result(gov["outcome"], tuple(gov["reason_codes"]), False, gov["escalation_id"])
