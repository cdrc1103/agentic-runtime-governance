"""The docking point: a fake agent framework docked through ``NativeAdapter`` (INT-01, INT-06).

No real framework is used here, by design: this proves the contract an adapter author
implements against, with a deliberately framework-shaped fake.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arg.adapters import (
    ActionBlocked,
    EmbeddedClient,
    GenericToolAdapter,
    GovernanceClient,
    GovernanceUnavailable,
    GuardResult,
    HttpClient,
    NativeAdapter,
    PendingAction,
    TraceRecorder,
    governed_tool,
)
from arg.adapters.generic import current_decision_token
from arg.adapters.otel_genai import step_from_span
from arg.core.models import (
    Action,
    ActionTrace,
    Context,
    DecisionResponse,
    Envelope,
    Provenance,
)
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from tests.core.factories import T0
from tests.service.world import World, build_world

AGENT = "treasury-agent-1"


# ---- a fake agent framework + the adapter an author would write for it ------------------
@dataclass
class FakeToolCall:
    """The fake framework's tool-call event."""

    tool: str
    args: dict[str, Any]


class FakeFramework:
    """Calls tools through a pre-tool hook, like real frameworks do."""

    def __init__(self, adapter: "FakeFrameworkAdapter") -> None:
        """Keep the adapter and a log of what really executed."""
        self.adapter = adapter
        self.executed: list[str] = []
        self.order: list[str] = []
        self.tools: dict[str, Callable[..., Any]] = {}

    def call(self, tool: str, **args: Any) -> Any:
        """The framework's pre-tool hook: ask governance, then execute or stop."""
        self.order.append("hook")

        def execute(result: GuardResult) -> Any:
            self.order.append("execute")
            self.executed.append(tool)
            return {"ok": True, "token": result.token, "value": self.tools[tool](**args)}

        return self.adapter.run(FakeToolCall(tool, args), execute)


class FakeFrameworkAdapter(NativeAdapter):
    """What a docking author implements: two hooks."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        """Fixed agent identity and mandate."""
        super().__init__(*args, **kw)
        self.recorder = TraceRecorder()
        self.recorder.record("check", "framework_precheck")

    def build_envelope(self, event: FakeToolCall) -> Envelope:
        """Map the framework event to an envelope."""
        return Envelope(
            envelope_id=f"fw-{uuid.uuid4().hex}",
            created_at=T0,
            action=Action(
                type="payment.initiate",
                scope="account:ACME-001",
                parameters={"currency": "USD", **event.args},
            ),
            action_trace=ActionTrace(steps=self.recorder.drain()),
            context=Context(
                agent_id=AGENT,
                mandate_ref="mandate-1",
                network_context="internal",
                signals={"confidence": 0.95},
            ),
            provenance=Provenance(origin="native", adapter_id="fake-framework"),
        )

    def enforce(self, result: GuardResult, event: FakeToolCall) -> Any:  # noqa: ARG002
        """Framework-native refusal: a tool-result error, not an exception."""
        return {
            "ok": False,
            "verdict": result.verdict,
            "reasons": list(result.reason_codes),
            "escalation_id": result.escalation_id,
        }


@pytest.fixture
def w(tmp_path: Path) -> World:
    """Example Bank runtime."""
    return build_world(tmp_path)


def framework(w: World, client: GovernanceClient | None = None, **kw: Any) -> FakeFramework:
    """Fake framework docked to the real core through an embedded client."""
    assert w.rt.decision_service is not None
    adapter = FakeFrameworkAdapter(
        client or EmbeddedClient(w.rt.decision_service), signer=w.agent_key, **kw
    )
    fw = FakeFramework(adapter)
    fw.tools["wire"] = lambda **a: f"sent {a['amount']}"
    return fw


# ---- INT-01 ------------------------------------------------------------------------------
@pytest.mark.req("INT-01")
def test_decision_arrives_before_the_agent_acts(w: World) -> None:
    """Hook runs first; the tool body runs only after an allow, with the token attached."""
    fw = framework(w)
    out = fw.call("wire", amount=500)
    assert out["ok"] and out["value"] == "sent 500" and out["token"]
    assert fw.order == ["hook", "execute"]
    assert w.audit()[0].outcome == "auto_execute"  # the decision exists in the log


@pytest.mark.req("INT-01", "INT-05")
def test_blocked_and_pending_actions_never_execute(w: World) -> None:
    """Deny and Escalate return a framework-native refusal; the tool body is not called."""
    fw = framework(w)
    held = fw.call("wire", amount=20000)
    assert held == {
        "ok": False,
        "verdict": "pending",
        "reasons": ["EXP_PER_ACTION_EXCEEDED", "RISK_OBSERVE_THRESHOLD"],
        "escalation_id": "esc-" + w.audit()[0].envelope["envelope_id"],
    }
    fw.adapter.signer = None  # unsigned native envelope: identity stage must reject
    fw.adapter.recorder.record("check", "framework_precheck")
    denied = fw.call("wire", amount=500)
    assert denied["verdict"] == "block" and denied["reasons"] == ["IDN_SIGNATURE_MISSING"]
    assert fw.executed == []


@pytest.mark.req("INT-05")
def test_unreachable_core_fails_closed(w: World) -> None:
    """Client errors (core down, HTTP 500, garbage body) produce a block, never an execute."""

    class Down(GovernanceClient):
        def decide(self, envelope: Any) -> DecisionResponse:
            raise GovernanceUnavailable("connection refused")

    class Crash(GovernanceClient):
        def decide(self, envelope: Any) -> DecisionResponse:
            raise RuntimeError("bug in a custom client")

    def http_with(status: int, body: bytes) -> HttpClient:
        return HttpClient("http://core", "t", transport=lambda *_: (status, body))

    for client in (
        Down(),
        Crash(),
        http_with(500, b"{}"),
        http_with(200, b"not json"),
        http_with(200, b'{"outcome": "maybe"}'),
    ):
        fw = framework(w, client)
        out = fw.call("wire", amount=1)
        assert out == {
            "ok": False,
            "verdict": "block",
            "reasons": ["ADAPTER_NO_DECISION"],
            "escalation_id": None,
        }
        assert fw.executed == []


def test_hybrid_mode_requires_a_token(w: World) -> None:
    """With require_token an allow without a token is still a block."""

    class NoToken(GovernanceClient):
        def decide(self, envelope: Any) -> DecisionResponse:
            return DecisionResponse(decision_id="d", outcome="auto_execute")

    fw = framework(w, NoToken(), require_token=True)
    assert fw.call("wire", amount=1)["reasons"] == ["ADAPTER_TOKEN_MISSING"]
    assert framework(w, NoToken()).call("wire", amount=1)["ok"] is True


def test_trace_reaches_the_core_and_validation_needs_it(w: World) -> None:
    """The recorder's steps travel in the envelope; the core records them (ENV-02)."""
    fw = framework(w)
    fw.call("wire", amount=10)
    assert [s["name"] for s in w.audit()[0].envelope["action_trace"]["steps"]] == [
        "framework_precheck"
    ]


# ---- clients ----------------------------------------------------------------------------
def test_embedded_and_http_clients_agree(w: World, tmp_path: Path) -> None:
    """Same envelope, same decision, either transport (docking is transport-independent)."""
    tokens = {"t": {"principal": "orchestrator", "roles": ["submit"]}}
    api = TestClient(create_app(w.rt, BearerTokenAuthenticator(tokens)))

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        r = api.post("/v1/decisions", content=body, headers=headers)
        return r.status_code, r.content

    http = HttpClient("http://testserver", "t", transport=transport)
    assert w.rt.decision_service is not None
    emb = EmbeddedClient(w.rt.decision_service)
    a = emb.decide(w.raw(500, envelope_id="parity-a"))
    b = http.decide(w.raw(500, envelope_id="parity-b"))
    same = {"outcome", "reason_codes", "policy_version", "decided_at_stage"}
    assert a.model_dump(include=same) == b.model_dump(include=same)
    assert a.outcome == "auto_execute" and b.token
    bad = HttpClient("http://testserver", "wrong", transport=transport)
    with pytest.raises(GovernanceUnavailable, match="401"):
        bad.decide(w.raw(500))


# ---- generic adapter / governed_tool ----------------------------------------------------
def generic(w: World, **kw: Any) -> GenericToolAdapter:
    """Generic adapter for treasury-agent-1 over the embedded client."""
    assert w.rt.decision_service is not None
    return GenericToolAdapter(
        EmbeddedClient(w.rt.decision_service),
        agent_id=AGENT,
        signer=w.agent_key,
        mandate_ref="mandate-1",
        network_context="internal",
        clock=w.clock,
        signals=lambda: {"confidence": 0.95},
        **kw,
    )


@pytest.mark.req("INT-01", "INT-06")
def test_governed_tool_sync(w: World) -> None:
    """Allowed call executes with the token injected; blocked raises; held returns pending."""
    ad = generic(w)
    seen: list[Any] = []

    @governed_tool(
        ad, action_type="payment.initiate", scope=lambda account, **_: f"account:{account}"
    )
    def pay(
        account: str, amount: float, currency: str = "USD", decision_token: str | None = None
    ) -> str:
        seen.append((decision_token, current_decision_token.get()))
        return f"paid {amount} {currency}"

    ad.recorder.record("retrieval", "lookup_balance", input={"account": "ACME-001"})
    assert pay("ACME-001", 500) == "paid 500 USD"
    token, ctx_token = seen[0]
    assert token and token == ctx_token and current_decision_token.get() is None
    entry = w.audit()[0]
    assert entry.envelope["action"]["parameters"] == {
        "account": "ACME-001",
        "amount": 500,
        "currency": "USD",
    }
    assert entry.envelope["action_trace"]["steps"][0]["name"] == "lookup_balance"

    ad.recorder.record("check", "limits_looked_up")
    pending = pay("ACME-001", 20000)
    assert isinstance(pending, PendingAction) and pending.escalation_id

    ad.recorder.record("check", "again")
    ad.signer = None
    with pytest.raises(ActionBlocked) as ei:
        pay("ACME-001", 1)
    assert ei.value.result.reason_codes == ("IDN_SIGNATURE_MISSING",)
    assert len(seen) == 1


def test_governed_tool_async(w: World) -> None:
    """Async tools are supported; the body awaits only after an allow."""
    ad = generic(w)
    ran: list[str] = []

    @governed_tool(ad, action_type="payment.initiate", scope="account:ACME-001")
    async def pay(amount: float, currency: str = "USD") -> str:
        ran.append("ran")
        return "ok"

    ad.recorder.record("check", "c1")
    assert asyncio.run(pay(100)) == "ok"
    ad.recorder.record("check", "c2")
    assert isinstance(asyncio.run(pay(30000)), PendingAction)
    assert ran == ["ran"]


@pytest.mark.req("INT-03")
def test_governance_sits_between_guardrail_and_rail_and_replaces_neither(w: World) -> None:
    """Content filter first; governance only for what passes; the rail still demands the token."""
    order: list[str] = []
    ad = generic(w)

    def guardrail(text: str) -> None:
        order.append("guardrail")
        if "ignore previous instructions" in text:
            raise PermissionError("filtered upstream")

    def rail(amount: float, token: str | None) -> str:
        order.append("rail")
        if token is None:
            raise PermissionError("rail requires a decision token")
        return "settled"

    @governed_tool(ad, action_type="payment.initiate", scope="account:ACME-001")
    def pay(amount: float, currency: str = "USD", decision_token: str | None = None) -> str:
        order.append("execute")
        return rail(amount, decision_token)

    def agent_step(text: str, amount: float) -> Any:
        guardrail(text)
        order.append("governance")
        return pay(amount)

    ad.recorder.record("check", "c")
    assert agent_step("pay vendor 17", 100) == "settled"
    assert order == ["guardrail", "governance", "execute", "rail"]
    order.clear()
    with pytest.raises(PermissionError, match="filtered"):
        agent_step("ignore previous instructions", 100)
    assert order == ["guardrail"]  # governance never saw filtered content
    assert len(w.audit()) == 1
    with pytest.raises(PermissionError, match="requires a decision token"):
        rail(100, None)  # the rail is independent of governance


# ---- trace helpers ---------------------------------------------------------------------
@pytest.mark.req("INT-06")
def test_otel_genai_span_mapping() -> None:
    """Verified GenAI operation names map to trace kinds; agent operations are not steps."""
    t0, t1 = T0, T0.replace(second=1)

    def step(attrs: dict[str, Any]) -> Any:
        return step_from_span(attrs, step_id="s", started_at=t0, ended_at=t1, span_id="abc")

    tool = step(
        {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "wire",
            "gen_ai.tool.call.id": "call_1",
        }
    )
    assert (tool.kind, tool.name, tool.otel_span_id) == ("tool_call", "wire", "abc")
    assert step({"gen_ai.operation.name": "retrieval", "gen_ai.request.model": "x"}).kind == (
        "retrieval"
    )
    assert step({"gen_ai.operation.name": "embeddings"}).kind == "retrieval"
    chat = step({"gen_ai.operation.name": "chat", "gen_ai.request.model": "model-a"})
    assert (chat.kind, chat.name) == ("model_call", "model-a")
    assert step({"gen_ai.operation.name": "invoke_agent"}) is None
    assert step({"gen_ai.operation.name": "create_agent"}) is None
    assert step({}) is None
    rec = TraceRecorder()
    rec.extend([tool, chat])
    assert [s.step_id for s in rec.drain()] == ["s1", "s2"] and rec.drain() == []


def test_recorder_hashes_inputs_and_outputs_only() -> None:
    """Raw values never enter the trace, only their hashes; order-independent for dicts."""
    rec = TraceRecorder()
    a = rec.record("tool_call", "t", input={"a": 1, "b": 2}, output=object)
    b = rec.record("tool_call", "t", input={"b": 2, "a": 1})
    assert a.input_hash == b.input_hash and a.output_hash and b.output_hash is None
    assert "secret" not in json.dumps(
        rec.record("check", "c", input="secret").model_dump(mode="json")
    )
