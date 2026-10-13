"""HTTP API end to end: auth, decisions, escalation, audit verify, telemetry (T-604, T-606)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from arg.core.audit.anchor import FileAnchorSink
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator, UnsafeNoAuthenticator
from arg.service.telemetry import OtelObserver
from tests.service.world import World, build_world

TOKENS = {
    "t-submit": {"principal": "orchestrator", "roles": ["submit"]},
    "t-rita": {"principal": "rita.reviewer", "roles": ["review"]},
    "t-ivan": {"principal": "ivan.intern", "roles": ["review"]},
    "t-nobody": {"principal": "mallory", "roles": ["review"]},
    "t-admin": {"principal": "ops", "roles": ["admin"]},
}


def hdr(token: str) -> dict[str, str]:
    """Authorization header."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(tmp_path: Path) -> World:
    """In-memory world with a file anchor sink."""
    w = build_world(tmp_path)
    w.rt.components["anchor_sink"] = FileAnchorSink(tmp_path / "anchors.jsonl")
    return w


@pytest.fixture
def client(world: World) -> TestClient:
    """Test client over the app."""
    return TestClient(create_app(world.rt, BearerTokenAuthenticator(TOKENS)))


def test_healthz_is_open_everything_else_needs_a_token(client: TestClient, world: World) -> None:
    """401 without/with a bad token; 403 with the wrong role."""
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.post("/v1/decisions", json=world.raw()).status_code == 401
    assert client.post("/v1/decisions", json=world.raw(), headers=hdr("nope")).status_code == 401
    bad_scheme = {"Authorization": "Basic t-submit"}
    assert client.post("/v1/decisions", json=world.raw(), headers=bad_scheme).status_code == 401
    assert client.post("/v1/decisions", json=world.raw(), headers=hdr("t-rita")).status_code == 403
    assert client.post("/v1/escalations/sweep", headers=hdr("t-submit")).status_code == 403
    assert client.get("/v1/audit/x/verify", headers=hdr("t-rita")).status_code == 403


@pytest.mark.req("INT-05", "AUD-01")
def test_decision_roundtrip_and_malformed_bodies_are_decided_not_crashed(
    client: TestClient, world: World
) -> None:
    """Valid envelope: 200 + decision; garbage bodies: 200 + Deny, audited."""
    r = client.post("/v1/decisions", json=world.raw(500), headers=hdr("t-submit"))
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "auto_execute" and body["decision_id"] == "treasury-agent-1#1"
    junk = client.post("/v1/decisions", content=b"{not json", headers=hdr("t-submit"))
    arr = client.post("/v1/decisions", json=[1, 2], headers=hdr("t-submit"))
    for resp in (junk, arr):
        assert resp.status_code == 200 and resp.json()["outcome"] == "deny"
        assert resp.json()["reason_codes"] == ["ENV_SCHEMA_INVALID"]
    assert len(world.audit("_unattributed")) == 2


def test_internal_reentry_is_not_reachable_over_http(client: TestClient, world: World) -> None:
    """Smuggling an identity into the body changes nothing: unknown fields fail validation."""
    raw = world.raw(500)
    raw["internal_identity"] = {"agent_id": "treasury-agent-1"}
    r = client.post("/v1/decisions", json=raw, headers=hdr("t-submit")).json()
    assert r["outcome"] == "deny" and r["reason_codes"] == ["ENV_SCHEMA_INVALID"]


@pytest.mark.req("ESC-01", "ESC-04", "ESC-05")
def test_escalation_flow_over_http(client: TestClient, world: World) -> None:
    """Submit → pending; submitter sees a summary, reviewer the envelope; approve; refusals."""
    esc = client.post("/v1/decisions", json=world.raw(20000), headers=hdr("t-submit")).json()
    assert esc["outcome"] == "escalate"
    eid = esc["escalation_id"]
    summary = client.get(f"/v1/escalations/{eid}", headers=hdr("t-submit")).json()
    assert set(summary) == {"escalation_id", "state", "queue", "deadline", "decision_id"}
    full = client.get(f"/v1/escalations/{eid}", headers=hdr("t-rita")).json()
    assert full["envelope"]["envelope_id"] == "env-0001" and full["state"] == "PENDING"
    assert client.get("/v1/escalations/nope", headers=hdr("t-rita")).status_code == 404

    url = f"/v1/escalations/{eid}/resolution"
    approve = {"action": "approve", "note": "ok"}
    assert client.post(url, json=approve, headers=hdr("t-submit")).status_code == 403  # role
    assert client.post(url, json=approve, headers=hdr("t-nobody")).status_code == 403  # unknown
    over = client.post(url, json=approve, headers=hdr("t-ivan"))
    assert over.status_code == 403 and over.json()["detail"]["code"] == "ESC_AUTHORITY_EXCEEDED"
    assert client.post(url, json={"action": "nope"}, headers=hdr("t-rita")).status_code == 422
    done = client.post(url, json=approve, headers=hdr("t-rita"))
    assert done.status_code == 200 and done.json()["escalation"]["state"] == "APPROVED"
    assert done.json()["escalation"]["resolved_by"] == "rita.reviewer"  # from the credential
    again = client.post(url, json=approve, headers=hdr("t-rita"))
    assert again.status_code == 409


@pytest.mark.req("ESC-05")
def test_modify_over_http_returns_child_decision(client: TestClient, world: World) -> None:
    """Modify re-enters the pipeline; the response carries the child decision."""
    eid = client.post("/v1/decisions", json=world.raw(20000), headers=hdr("t-submit")).json()[
        "escalation_id"
    ]
    r = client.post(
        f"/v1/escalations/{eid}/resolution",
        json={"action": "modify", "modified_parameters": {"amount": 300}},
        headers=hdr("t-rita"),
    ).json()
    assert r["escalation"]["state"] == "MODIFIED" and r["child"]["outcome"] == "auto_execute"


@pytest.mark.req("ESC-03")
def test_sweep_endpoint_applies_timeouts(client: TestClient, world: World) -> None:
    """The scheduler hook blocks overdue escalations."""
    eid = client.post("/v1/decisions", json=world.raw(20000), headers=hdr("t-submit")).json()[
        "escalation_id"
    ]
    assert client.post("/v1/escalations/sweep", headers=hdr("t-admin")).json() == []
    world.clock.advance(seconds=1000)
    swept = client.post("/v1/escalations/sweep", headers=hdr("t-admin")).json()
    assert swept == [{"escalation_id": eid, "state": "TIMED_OUT"}]


@pytest.mark.req("AUD-06")
def test_audit_verify_and_anchor_endpoints(client: TestClient, world: World) -> None:
    """Verify passes; anchoring publishes the head; verification then uses the anchor."""
    for _ in range(3):
        client.post("/v1/decisions", json=world.raw(10), headers=hdr("t-submit"))
    assert client.get("/v1/audit/treasury-agent-1/verify", headers=hdr("t-admin")).json() == {
        "ok": True,
        "checked": 3,
        "code": None,
        "seq": None,
    }
    a = client.post("/v1/audit/treasury-agent-1/anchor", headers=hdr("t-admin")).json()
    assert a["seq"] == 3
    world.rt.components["audit_store"]._streams["treasury-agent-1"].pop()  # truncate the tail
    v = client.get("/v1/audit/treasury-agent-1/verify", headers=hdr("t-admin")).json()
    assert v["ok"] is False and v["code"] == "AUD_ANCHOR_MISMATCH"
    assert client.post("/v1/audit/ghost/anchor", headers=hdr("t-admin")).status_code == 404


# ---- authenticators ---------------------------------------------------------------------
def test_unsafe_authenticator_refuses_outside_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """UnsafeNoAuthenticator must not start unless ARG_TEST_MODE=1."""
    monkeypatch.delenv("ARG_TEST_MODE", raising=False)
    with pytest.raises(RuntimeError, match="ARG_TEST_MODE"):
        UnsafeNoAuthenticator()
    monkeypatch.setenv("ARG_TEST_MODE", "1")
    who = UnsafeNoAuthenticator().authenticate(None)
    assert who is not None and "admin" in who[1]


def test_bearer_authenticator_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tokens from env JSON; unknown roles, empty config, and missing env are errors."""
    monkeypatch.setenv("ARG_TOKENS", json.dumps(TOKENS))
    auth = BearerTokenAuthenticator(tokens_env="ARG_TOKENS")
    assert auth.authenticate("t-rita") == ("rita.reviewer", frozenset({"review"}))
    assert auth.authenticate("t-rit") is None and auth.authenticate(None) is None
    with pytest.raises(ValueError, match="unknown roles"):
        BearerTokenAuthenticator({"x": {"principal": "p", "roles": ["root"]}})
    with pytest.raises(ValueError, match="no tokens"):
        BearerTokenAuthenticator({})
    with pytest.raises(ValueError, match="not set"):
        BearerTokenAuthenticator(tokens_env="ARG_MISSING")


def test_create_app_requires_a_decision_service(tmp_path: Path) -> None:
    """A runtime without pipeline/stores cannot be served."""
    from arg.runtime import GovernanceRuntime

    with pytest.raises(ValueError, match="decision service"):
        create_app(GovernanceRuntime(), UnsafeNoAuthenticatorStub())


class UnsafeNoAuthenticatorStub(BearerTokenAuthenticator):
    """Valid authenticator for construction-only tests."""

    def __init__(self) -> None:
        """One token."""
        super().__init__({"t": {"principal": "p", "roles": ["admin"]}})


# ---- telemetry --------------------------------------------------------------------------
def test_otel_spans_and_metrics(tmp_path: Path) -> None:
    """Spans per stage under one decision span; counters, histogram, gauge, blocked count."""
    spans = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    mp = MeterProvider(metric_readers=[reader])
    w = build_world(tmp_path, max_open=1)
    w.svc.observer = OtelObserver(tp, mp)
    assert w.decide(500).outcome == "auto_execute"
    assert w.decide(20000).outcome == "escalate"
    assert w.decide(20000).reason_codes[0] == "ESC_QUEUE_FULL"

    names = [s.name for s in spans.get_finished_spans()]
    assert names.count("arg.decide") == 3
    for stage in ("validate", "identity", "mandate", "retrieve", "evaluate", "reserve"):
        assert f"arg.stage.{stage}" in names
    first = spans.get_finished_spans()[0]
    decide = next(s for s in spans.get_finished_spans() if s.name == "arg.decide")
    assert first.parent is not None and first.parent.span_id == decide.context.span_id

    data: dict[str, Any] = {}
    for rm in reader.get_metrics_data().resource_metrics:  # type: ignore[union-attr]
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                data[m.name] = m.data.data_points
    assert sum(p.value for p in data["arg.decisions"]) == 3
    outcomes = {p.attributes["outcome"] for p in data["arg.decisions"]}
    assert outcomes == {"auto_execute", "escalate", "deny"}
    assert data["arg.escalation.queue_depth"][0].value == 1
    assert data["arg.escalation.blocked"][0].value == 1
    assert sum(p.count for p in data["arg.stage.duration"]) >= 18


def test_sample_runtime_yaml_builds_the_service() -> None:
    """The shipped config composes a working service (keys come from the environment)."""
    import os

    from arg.runtime import build_runtime, load_config

    os.environ["ARG_TOKENS"] = json.dumps(TOKENS)
    rt = build_runtime(load_config(Path("config/runtime.yaml")))
    assert rt.decision_service is not None and "authenticator" in rt.components
    app = create_app(rt, rt.components["authenticator"])
    assert TestClient(app).get("/healthz").status_code == 200
    del os.environ["ARG_TOKENS"]
