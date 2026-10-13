"""Tokens through the decision service and API (INT-04; scenarios S11, S12; hybrid mode primitive)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arg.core.models import Action
from arg.core.tokens.service import action_hash
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from tests.service.world import World, build_world

TOKENS = {
    "t-submit": {"principal": "orchestrator", "roles": ["submit"]},
    "t-gw": {"principal": "gateway-1", "roles": ["consume"]},
    "t-rita": {"principal": "rita.reviewer", "roles": ["review"]},
}


def hdr(t: str) -> dict[str, str]:
    """Authorization header."""
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def w(tmp_path: Path) -> World:
    """World with a token service."""
    return build_world(tmp_path)


@pytest.fixture
def client(w: World) -> TestClient:
    """API over the world."""
    return TestClient(create_app(w.rt, BearerTokenAuthenticator(TOKENS)))


def act_hash(raw: dict[str, Any]) -> str:
    """Hash of the action in a raw envelope."""
    a = raw["action"]
    return action_hash(Action(type=a["type"], scope=a["scope"], parameters=a["parameters"]))


@pytest.mark.req("INT-04")
def test_tokens_only_for_proceeding_outcomes_and_recorded_in_audit(w: World) -> None:
    """Auto-Execute and Observe carry a token (jti audited); Escalate and Deny do not."""
    ok = w.decide(500)
    obs = w.decide(500, signals={"confidence": 0.95, "anomaly_score": 0.9})
    held = w.decide(20000)
    denied = w.decide(500, agent="ghost-agent")
    assert ok.token and obs.token and held.token is None and denied.token is None
    entries = {e.decision_id if hasattr(e, "decision_id") else e.entry_id: e for e in w.audit()}
    assert w.svc.tokens is not None
    claims = w.svc.tokens.verify(
        ok.token, act_hash=act_hash(w.raw(500)), agent_id="treasury-agent-1", at=w.clock.now
    )
    assert entries[ok.decision_id].token_jti == claims.jti
    assert claims.decision_id == ok.decision_id and claims.outcome == "auto_execute"
    assert claims.policy_version == ok.policy_version


@pytest.mark.req("INT-04", "ENV-06")
def test_duplicate_submission_returns_the_same_token(w: World) -> None:
    """Idempotent decisions replay the original response, token included."""
    raw = w.raw(500, envelope_id="dup")
    assert w.svc.decide(raw).token == w.svc.decide(raw).token


@pytest.mark.req("INT-04")
def test_reviewer_approval_issues_a_token_bound_to_the_held_action(w: World) -> None:
    """Approve returns a token for the original escalated action; decline does not."""
    held_raw = w.raw(20000)
    held = w.svc.decide(held_raw)
    res = w.svc.resolve_escalation(held.escalation_id, "rita.reviewer", "approve")  # type: ignore[arg-type]
    assert res.token is not None
    claims = w.svc.tokens.verify(  # type: ignore[union-attr]
        res.token, act_hash=act_hash(held_raw), agent_id="treasury-agent-1", at=w.clock.now
    )
    assert claims.decision_id == held.decision_id
    assert w.audit()[-1].token_jti == claims.jti
    other = w.svc.decide(w.raw(20000))
    declined = w.svc.resolve_escalation(other.escalation_id, "rita.reviewer", "decline")  # type: ignore[arg-type]
    assert declined.token is None


@pytest.mark.req("INT-04")
def test_consume_endpoint_s11_s12(client: TestClient, w: World) -> None:
    """S12 altered params refused (token survives); S11 replay refused; wrong agent refused."""
    raw = w.raw(500)
    token = client.post("/v1/decisions", json=raw, headers=hdr("t-submit")).json()["token"]
    body = {"token": token, "act_hash": act_hash(raw), "agent_id": "treasury-agent-1"}
    altered = {**body, "act_hash": act_hash(w.raw(50000))}
    r = client.post("/v1/tokens/consume", json=altered, headers=hdr("t-gw"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "TOK_ACTION_MISMATCH"
    wrong = client.post("/v1/tokens/consume", json={**body, "agent_id": "x"}, headers=hdr("t-gw"))
    assert wrong.json()["detail"]["code"] == "TOK_SUBJECT_MISMATCH"
    ok = client.post("/v1/tokens/consume", json=body, headers=hdr("t-gw"))
    assert ok.status_code == 200 and ok.json()["sub"] == "treasury-agent-1"
    replay = client.post("/v1/tokens/consume", json=body, headers=hdr("t-gw"))
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "TOK_REPLAYED"
    assert client.post("/v1/tokens/consume", json=body, headers=hdr("t-submit")).status_code == 403


@pytest.mark.req("INT-04")
def test_expired_token_refused_at_consume(client: TestClient, w: World) -> None:
    """The short TTL is enforced against the service clock."""
    raw = w.raw(500)
    token = client.post("/v1/decisions", json=raw, headers=hdr("t-submit")).json()["token"]
    w.clock.advance(seconds=301)
    r = client.post(
        "/v1/tokens/consume",
        json={"token": token, "act_hash": act_hash(raw), "agent_id": "treasury-agent-1"},
        headers=hdr("t-gw"),
    )
    assert r.json()["detail"]["code"] == "TOK_EXPIRED"


def test_runtime_without_token_service_has_no_tokens_and_no_endpoint(tmp_path: Path) -> None:
    """Tokens are optional: no service configured means none issued and consume is 404."""
    w = build_world(tmp_path, tokens=False)
    assert w.decide(500).token is None
    c = TestClient(create_app(w.rt, BearerTokenAuthenticator(TOKENS)))
    r = c.post(
        "/v1/tokens/consume",
        json={"token": "x", "act_hash": "0" * 64, "agent_id": "a"},
        headers=hdr("t-gw"),
    )
    assert r.status_code == 404
