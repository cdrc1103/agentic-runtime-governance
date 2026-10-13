"""MCP gateway: standalone and hybrid modes (INT-02, INT-04; S08, S10-S12)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arg.adapters.client import GovernanceClient, GovernanceUnavailable
from arg.core.models import DecisionResponse
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from tests.gateway.harness import Rig, build_rig, call_tool, mcp_headers


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """Standalone MCP gateway."""
    return build_rig(tmp_path)


def post(rig: Rig, body: Any, **kw: Any) -> Any:
    """POST a JSON-RPC message through the gateway."""
    headers = kw.pop("headers", mcp_headers())
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return rig.client.post("/mcp", content=content, headers=headers)


def result_of(resp: Any) -> dict[str, Any]:
    """The JSON-RPC result object."""
    return resp.json()["result"]  # type: ignore[no-any-return]


# ---- standalone ----------------------------------------------------------------------------
@pytest.mark.req("INT-02")
def test_allowed_call_is_forwarded_untouched_and_audited(rig: Rig) -> None:
    """Auto-Execute: upstream sees the exact bytes; agent credentials do not leak upstream."""
    body = json.dumps(
        call_tool(7, "wire_transfer", account="ACME-001", amount=500, currency="USD")
    ).encode()
    r = post(rig, body, headers=mcp_headers(**{"x-arg-decision-token": "ignored"}))
    assert r.status_code == 200 and result_of(r)["content"][0]["text"] == "EXECUTED"
    seen = rig.upstream.seen[0]
    assert seen["body"] == body and seen["path"] == "/mcp"
    assert "authorization" not in seen["headers"]
    assert "x-arg-decision-token" not in seen["headers"]
    assert seen["headers"]["x-upstream-key"] == "gw-secret"
    assert seen["headers"]["mcp-method"] == "tools/call"
    [entry] = rig.world.audit()
    assert entry.outcome == "auto_execute" and entry.envelope["provenance"]["origin"] == "gateway"
    assert entry.envelope["provenance"]["observed_call"]["target"] == "wire_transfer"
    assert entry.identity_result.agent_id == "treasury-agent-1"
    assert entry.envelope["action"]["scope"] == "account:ACME-001"


def test_non_governed_messages_pass_through(rig: Rig) -> None:
    """tools/list, initialize, notifications and passthrough tools reach the upstream."""
    h = mcp_headers(None, **{"mcp-method": "tools/list"})
    assert (
        post(rig, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=h).status_code == 200
    )
    note = post(rig, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
    assert note.status_code == 202
    weather = post(
        rig,
        call_tool(2, "get_weather", city="Oslo"),
        headers=mcp_headers(None, **{"mcp-name": "get_weather"}),
    )
    assert weather.status_code == 200 and rig.upstream.calls == 3
    assert rig.world.audit() == []


@pytest.mark.req("INT-02", "INT-05")
def test_denied_and_escalated_calls_get_structured_tool_errors(rig: Rig) -> None:
    """Refusals are MCP tool execution errors with reasons; upstream is never called."""
    held = post(
        rig, call_tool(3, "wire_transfer", account="ACME-001", amount=20000, currency="USD")
    )
    r = result_of(held)
    gov = r["structuredContent"]["governance"]
    assert held.status_code == 200 and r["isError"] is True and r["resultType"] == "complete"
    assert gov["outcome"] == "escalate" and gov["escalation_id"].startswith("esc-gw-")
    assert "held for human review" in r["content"][0]["text"]
    denied = post(
        rig,
        call_tool(4, "wire_transfer", account="ACME-001", amount=5, currency="USD"),
        headers=mcp_headers("expired-tok"),
    )
    d = result_of(denied)["structuredContent"]["governance"]
    assert d["outcome"] == "deny" and d["reason_codes"] == ["MND_EXPIRED"]
    assert denied.json()["id"] == 4
    assert rig.upstream.calls == 0


def test_legacy_protocol_version_gets_result_without_result_type(rig: Rig) -> None:
    """Clients on older revisions get the same refusal minus the 2026-07-28 field."""
    h = mcp_headers(**{"mcp-protocol-version": "2025-06-18"})
    r = result_of(
        post(
            rig, call_tool(5, "wire_transfer", account="A", amount=20000, currency="USD"), headers=h
        )
    )
    assert "resultType" not in r and r["isError"] is True


def test_unmapped_tool_and_missing_parameters_are_refused(rig: Rig) -> None:
    """Default deny: unknown tools and unreadable parameters never reach the upstream."""
    unknown = result_of(post(rig, call_tool(1, "delete_everything", force=True)))
    assert unknown["structuredContent"]["governance"]["reason_codes"] == ["GW_UNMAPPED"]
    missing = result_of(post(rig, call_tool(2, "wire_transfer", account="A", amount=5)))
    assert missing["structuredContent"]["governance"]["reason_codes"] == ["GW_PARAMETER_UNREADABLE"]
    assert rig.upstream.calls == 0


def test_authentication_is_required_for_governed_calls(rig: Rig) -> None:
    """No or unknown credential: 401 and no forwarding."""
    body = call_tool(1, "wire_transfer", account="A", amount=1, currency="USD")
    for token in (None, "nope"):
        r = post(rig, body, headers=mcp_headers(token))
        assert r.status_code == 401 and r.json()["error"]["code"] == -32001
    assert rig.upstream.calls == 0


def test_header_body_mismatch_is_rejected_with_32020(rig: Rig) -> None:
    """The body is the source of truth; disagreeing mirrors are a 400 HeaderMismatch."""
    body = call_tool(9, "wire_transfer", account="A", amount=1, currency="USD")
    r = post(rig, body, headers=mcp_headers(**{"mcp-name": "get_weather"}))
    assert r.status_code == 400 and r.json()["error"]["code"] == -32020 and r.json()["id"] == 9
    r = post(rig, body, headers=mcp_headers(**{"mcp-method": "tools/list"}))
    assert r.status_code == 400 and r.json()["error"]["code"] == -32020
    # a name smuggled through the Base64 sentinel must also match after decoding
    import base64

    enc = "=?base64?" + base64.b64encode(b"get_weather").decode() + "?="
    r = post(rig, body, headers=mcp_headers(**{"mcp-name": enc}))
    assert r.status_code == 400
    ok = "=?base64?" + base64.b64encode(b"wire_transfer").decode() + "?="
    assert post(rig, body, headers=mcp_headers(**{"mcp-name": ok})).status_code == 200


def test_malformed_requests_are_never_forwarded(rig: Rig) -> None:
    """Bad JSON, bad params, and batched calls are refused locally."""
    assert post(rig, b"{nope").json()["error"]["code"] == -32700
    assert (
        post(rig, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}).json()[
            "error"
        ]["code"]
        == -32602
    )
    batch = [
        call_tool(1, "wire_transfer", account="A", amount=1, currency="USD"),
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    r = post(rig, batch)
    assert r.status_code == 400 and r.json()["error"]["code"] == -32600
    assert rig.upstream.calls == 0
    assert post(rig, [{"jsonrpc": "2.0", "id": 3, "method": "tools/list"}]).status_code in (
        200,
        202,
    )


def test_sse_responses_stream_through(rig: Rig) -> None:
    """An allowed call whose upstream answers with SSE is streamed back intact."""
    r = post(rig, call_tool(11, "stream_tool", account="A", amount=10, currency="USD"))
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"notifications/progress" in r.content and b'"id":11' in r.content


@pytest.mark.req("INT-05")
def test_core_unreachable_fails_closed_at_the_gateway(tmp_path: Path) -> None:
    """S16 at the gateway: no decision, no forwarding."""

    class Down(GovernanceClient):
        def decide(self, envelope: Any) -> DecisionResponse:
            raise GovernanceUnavailable("core down")

    rig = build_rig(tmp_path, core_client=Down())
    r = result_of(post(rig, call_tool(1, "wire_transfer", account="A", amount=1, currency="USD")))
    assert r["structuredContent"]["governance"]["reason_codes"] == ["GW_NO_DECISION"]
    assert rig.upstream.calls == 0


@pytest.mark.req("ENV-04", "INT-02")
def test_s08_observed_call_governs_and_forged_gateway_envelopes_are_refused(rig: Rig) -> None:
    """S08: what the agent declared is irrelevant; a forged observed-call hash is denied."""
    w = rig.world
    declared = w.decide(500)  # the agent's own (cheap) declaration earns a token
    assert declared.token
    big = call_tool(1, "wire_transfer", account="ACME-001", amount=20000, currency="USD")
    r = result_of(post(rig, big, headers=mcp_headers(**{"x-arg-decision-token": declared.token})))
    assert r["structuredContent"]["governance"]["outcome"] == "escalate"  # observed call governs
    assert rig.upstream.calls == 0

    # a gateway-origin envelope whose parameters do not match its observed-call hash
    tokens = {
        "gw": {"principal": "gateway-1", "roles": ["submit"]},
        "other": {"principal": "orchestrator", "roles": ["submit"]},
    }
    api = TestClient(create_app(w.rt, BearerTokenAuthenticator(tokens)))
    env = w.raw(500, sign=False)
    env["provenance"] = {
        "origin": "gateway",
        "adapter_id": "gateway-1",
        "signature": None,
        "observed_call": {
            "method": "tools/call",
            "target": "wire_transfer",
            "params_hash": "0" * 64,
        },
    }
    forged = api.post("/v1/decisions", json=env, headers={"Authorization": "Bearer gw"}).json()
    assert forged["outcome"] == "deny" and forged["reason_codes"] == ["ENV_OBSERVED_CALL_MISMATCH"]
    stolen = api.post("/v1/decisions", json=env, headers={"Authorization": "Bearer other"})
    assert stolen.status_code == 403  # a non-gateway cannot claim to be one


# ---- hybrid --------------------------------------------------------------------------------
@pytest.fixture
def hybrid(tmp_path: Path) -> Rig:
    """Hybrid MCP gateway: requires a decision token."""
    return build_rig(tmp_path, mode="hybrid")


def native_token(rig: Rig, amount: float = 500) -> str:
    """Token from the agent's own native decision for the same action."""
    r = rig.world.decide(amount)
    assert r.token
    return r.token


@pytest.mark.req("INT-04")
def test_s10_call_without_token_is_refused(hybrid: Rig) -> None:
    """S10: skipping instrumentation does not get a call through."""
    r = result_of(
        post(hybrid, call_tool(1, "wire_transfer", account="ACME-001", amount=500, currency="USD"))
    )
    assert r["structuredContent"]["governance"]["reason_codes"] == ["GW_TOKEN_MISSING"]
    assert hybrid.upstream.calls == 0


@pytest.mark.req("INT-04")
def test_hybrid_forwards_with_matching_token_then_refuses_replay_s11(hybrid: Rig) -> None:
    """A matching token is consumed and the call forwarded; reuse is refused (S11)."""
    token = native_token(hybrid)
    body = call_tool(1, "wire_transfer", account="ACME-001", amount=500, currency="USD")
    h = mcp_headers(**{"x-arg-decision-token": token})
    ok = post(hybrid, body, headers=h)
    assert result_of(ok)["content"][0]["text"] == "EXECUTED" and hybrid.upstream.calls == 1
    assert "x-arg-decision-token" not in hybrid.upstream.seen[0]["headers"]
    replay = result_of(post(hybrid, body, headers=h))
    assert replay["structuredContent"]["governance"]["reason_codes"] == ["TOK_REPLAYED"]
    assert hybrid.upstream.calls == 1


@pytest.mark.req("INT-04")
def test_s12_altered_parameters_or_agent_refused_and_token_survives(hybrid: Rig) -> None:
    """S12: the call differs from what was decided; the token is not burned by the attempt."""
    token = native_token(hybrid)
    h = mcp_headers(**{"x-arg-decision-token": token})
    altered = call_tool(1, "wire_transfer", account="ACME-001", amount=50000, currency="USD")
    r = result_of(post(hybrid, altered, headers=h))
    assert r["structuredContent"]["governance"]["reason_codes"] == ["TOK_ACTION_MISMATCH"]
    other_scope = call_tool(2, "wire_transfer", account="EVIL-999", amount=500, currency="USD")
    r = result_of(post(hybrid, other_scope, headers=h))
    assert r["structuredContent"]["governance"]["reason_codes"] == ["TOK_ACTION_MISMATCH"]
    assert hybrid.upstream.calls == 0
    exact = call_tool(3, "wire_transfer", account="ACME-001", amount=500, currency="USD")
    assert post(hybrid, exact, headers=h).status_code == 200 and hybrid.upstream.calls == 1


def test_token_for_other_action_type_cannot_be_borrowed(hybrid: Rig) -> None:
    """The hash binds type, scope and parameters together."""
    token = native_token(hybrid)
    body = call_tool(1, "wire_transfer", account="ACME-001", amount=500, currency="EUR")
    r = result_of(post(hybrid, body, headers=mcp_headers(**{"x-arg-decision-token": token})))
    assert r["structuredContent"]["governance"]["reason_codes"] == ["TOK_ACTION_MISMATCH"]
