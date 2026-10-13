"""HTTP egress gateway: standalone and hybrid (INT-02, INT-04)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.gateway.harness import Rig, build_rig

AUTH = {"authorization": "Bearer agent-tok", "content-type": "application/json"}


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """Standalone HTTP egress gateway."""
    return build_rig(tmp_path, protocol="http")


def pay(rig: Rig, account: str = "ACME-001", amount: Any = 500, headers: Any = None) -> Any:
    """POST /payments/{account}."""
    body = json.dumps({"amount": amount, "currency": "USD"}).encode()
    return rig.client.post(f"/payments/{account}", content=body, headers=headers or AUTH)


@pytest.mark.req("INT-02")
def test_allowed_call_forwarded_with_original_body(rig: Rig) -> None:
    """Route match + extraction + decision; upstream sees the exact request."""
    r = pay(rig)
    assert r.status_code == 200 and r.json() == {"executed": True, "path": "/payments/ACME-001"}
    seen = rig.upstream.seen[0]
    assert json.loads(seen["body"]) == {"amount": 500, "currency": "USD"}
    assert (
        "authorization" not in seen["headers"] and seen["headers"]["x-upstream-key"] == "gw-secret"
    )
    [entry] = rig.world.audit()
    assert entry.envelope["action"]["scope"] == "account:ACME-001"
    assert entry.envelope["provenance"]["observed_call"] == {
        "method": "POST",
        "target": "/payments/ACME-001",
        "params_hash": entry.envelope["provenance"]["observed_call"]["params_hash"],
    }


def test_query_parameters_and_passthrough_route(rig: Rig) -> None:
    """Extraction reads path, query, body; explicit passthrough routes are forwarded."""
    body = json.dumps({"amount": 10, "currency": "USD"})
    r = rig.client.post("/transfers?account=ACME-001", content=body, headers=AUTH)
    assert r.status_code == 200
    assert rig.world.audit()[0].envelope["action"]["scope"] == "account:ACME-001"
    assert rig.client.get("/health").status_code == 200  # no credentials needed


@pytest.mark.req("INT-02", "INT-05")
def test_denied_and_pending_are_403_with_structured_reasons(rig: Rig) -> None:
    """Never a 2xx for a refused action; escalation id also in a header."""
    held = pay(rig, amount=20000)
    body = held.json()
    assert held.status_code == 403 and body["error"] == "pending_review"
    assert held.headers["x-arg-escalation-id"] == body["escalation_id"]
    expired = rig.client.post(
        "/payments/ACME-001",
        content=json.dumps({"amount": 1, "currency": "USD"}),
        headers={**AUTH, "authorization": "Bearer expired-tok"},
    )
    assert expired.status_code == 403
    assert expired.json()["error"] == "governance_denied"
    assert expired.json()["reason_codes"] == ["MND_EXPIRED"]
    assert rig.upstream.calls == 0


def test_default_deny_auth_and_bad_bodies(rig: Rig) -> None:
    """Unmapped route, missing credentials, unparseable body, unreadable parameter."""
    assert rig.client.delete("/accounts/ACME-001", headers=AUTH).status_code == 403
    assert (
        rig.client.post(
            "/payments/A", content=b"{}", headers={"content-type": "application/json"}
        ).status_code
        == 401
    )
    assert rig.client.post("/payments/A", content=b"{nope", headers=AUTH).status_code == 400
    missing = rig.client.post("/payments/A", content=b'{"amount": 5}', headers=AUTH)
    assert missing.status_code == 403 and missing.json()["reason_codes"] == [
        "GW_PARAMETER_UNREADABLE"
    ]
    assert rig.upstream.calls == 0


@pytest.mark.req("INT-04")
def test_hybrid_requires_matching_one_time_token(tmp_path: Path) -> None:
    """S10-S12 over REST: missing, altered, valid, replayed."""
    rig = build_rig(tmp_path, protocol="http", mode="hybrid")
    assert pay(rig).json()["reason_codes"] == ["GW_TOKEN_MISSING"]
    token = rig.world.decide(500).token
    assert token
    h = {**AUTH, "x-arg-decision-token": token}
    assert pay(rig, amount=900, headers=h).json()["reason_codes"] == ["TOK_ACTION_MISMATCH"]
    assert pay(rig, account="OTHER", headers=h).json()["reason_codes"] == ["TOK_ACTION_MISMATCH"]
    assert pay(rig, headers=h).status_code == 200
    assert pay(rig, headers=h).json()["reason_codes"] == ["TOK_REPLAYED"]
    assert rig.upstream.calls == 1
    assert "x-arg-decision-token" not in rig.upstream.seen[0]["headers"]


def test_upstream_unreachable_is_502_not_a_decision(tmp_path: Path) -> None:
    """If the upstream fails after an allow, the client gets 502 (and the decision is audited)."""
    import httpx2
    from starlette.testclient import TestClient

    from arg.gateway.app import create_gateway_app

    rig = build_rig(tmp_path, protocol="http")

    def boom(request: Any) -> Any:
        raise httpx2.ConnectError("down")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(boom), base_url="http://u")
    adapter_app = create_gateway_app(_adapter(rig), "http://u", client=client)
    r = TestClient(adapter_app).post(
        "/payments/A", content=json.dumps({"amount": 1, "currency": "USD"}), headers=AUTH
    )
    assert r.status_code == 502


def _adapter(rig: Rig) -> Any:
    """Re-create the egress adapter for the rig's engine."""
    from arg.gateway.http_egress import HttpEgressGateway
    from arg.gateway.identity import StaticBearerIdentityResolver
    from tests.gateway.harness import CREDS

    return HttpEgressGateway(
        rig.engine,
        StaticBearerIdentityResolver(CREDS),
        routes=[
            {
                "name": "pay",
                "method": "POST",
                "path": "/payments/{account}",
                "action_type": "payment.initiate",
                "scope": "account:{path.account}",
                "parameters": {"amount": "body.amount", "currency": "body.currency"},
                "signals": {"confidence": 0.95},
            }
        ],
    )
