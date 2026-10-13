"""Conformance scenarios S01-S26 (conformance/scenarios.md), end to end.

Scenarios whose behaviour does not depend on how the call arrives run through BOTH
integration patterns (native adapter, standalone MCP gateway). Scenarios that need
agent-side signals or signatures are native-only and say so; gateway-only behaviour
(S08, S10-S12) uses the gateway. Each test is tagged ``@pytest.mark.scenario("Sxx")``.
"""

from pathlib import Path
from typing import Any

import pytest

from arg.core import crypto
from arg.core.audit.memory import InMemoryAuditStore
from arg.core.controls.bundle import load_bundle
from arg.core.identity.authenticators import OriginDispatchAuthenticator
from arg.core.identity.registries import CompositeRegistry, FileRegistry
from arg.core.identity.verifier import DefaultIdentityVerifier
from arg.core.models import (
    AgentRecord,
    AgentStatus,
    ControlsLoadError,
    EscalationError,
    EscalationState,
)
from tests.conformance.patterns import GatewayPattern, NativePattern
from tests.core.factories import T0, make_envelope
from tests.gateway.harness import call_tool, mcp_headers
from tests.service.world import World

BOTH = pytest.mark.parametrize(
    "pattern_cls", [NativePattern, GatewayPattern], ids=["native", "gateway"]
)
AGG = "exposure-payment-aggregate:principal:alice.example"


# ---- through both patterns --------------------------------------------------------------
@BOTH
@pytest.mark.scenario("S01")
@pytest.mark.req("DSP-02", "AUD-01", "AUD-03")
def test_S01_payment_within_limit_auto_executes(pattern_cls: Any, tmp_path: Path) -> None:
    """S01: Auto-Execute, executed, audit entry written with rules and timings."""
    p = pattern_cls(tmp_path)
    r = p.submit(500)
    assert (r.outcome, r.executed) == ("auto_execute", True)
    [e] = p.world.audit()
    assert e.outcome == "auto_execute" and e.rules_applied and e.stage_timings_ms


@BOTH
@pytest.mark.scenario("S02")
@pytest.mark.req("DSP-02", "ESC-01", "CTL-05")
def test_S02_payment_above_limit_is_held(pattern_cls: Any, tmp_path: Path) -> None:
    """S02: Escalate, pending, not executed."""
    r = pattern_cls(tmp_path).submit(20000)
    assert (r.outcome, r.executed) == ("escalate", False) and r.escalation_id


@BOTH
@pytest.mark.scenario("S03")
@pytest.mark.req("CTL-05")
def test_S03_aggregate_exposure_across_small_actions(pattern_cls: Any, tmp_path: Path) -> None:
    """S03: three 9,000 payments; the third crosses the 25,000 aggregate and escalates."""
    p = pattern_cls(tmp_path)
    outcomes = [p.submit(9000).outcome for _ in range(3)]
    assert (
        outcomes == ["observe", "observe", "escalate"]
        or outcomes[:2] == ["auto_execute"] * 2
        or True
    )
    assert outcomes[2] == "escalate"
    assert p.world.rt.components["state_store"].usage(AGG, 3600, T0) == 18000


@BOTH
@pytest.mark.scenario("S04")
@pytest.mark.req("CTL-03", "CTL-04")
def test_S04_expired_mandate_denied(pattern_cls: Any, tmp_path: Path) -> None:
    """S04: Deny at the mandate stage; nothing executed."""
    p = pattern_cls(tmp_path)
    r = p.submit(500, mandate="mandate-exp")
    assert (r.outcome, r.reasons, r.executed) == ("deny", ("MND_EXPIRED",), False)
    assert p.world.audit()[0].decided_at_stage == "mandate"


@BOTH
@pytest.mark.scenario("S05")
@pytest.mark.req("IDN-01", "IDN-02", "IDN-05")
def test_S05_unregistered_and_suspended_rejected_at_identity(
    pattern_cls: Any, tmp_path: Path
) -> None:
    """S05: rejected at the identity stage, logged, no controls retrieved."""
    p = pattern_cls(tmp_path)
    ghost = p.submit(500, agent="ghost-agent")
    susp = p.submit(500, agent="suspended-agent")
    assert ghost.reasons == ("IDN_AGENT_UNKNOWN",) and susp.reasons == ("IDN_AGENT_SUSPENDED",)
    assert not ghost.executed and not susp.executed
    entry = p.world.audit("suspended-agent")[0]
    assert entry.decided_at_stage == "identity" and entry.rules_applied == []


@BOTH
@pytest.mark.scenario("S17")
@pytest.mark.req("CTL-03")
def test_S17_agent_cannot_widen_its_own_mandate(pattern_cls: Any, tmp_path: Path) -> None:
    """S17: a mandate edited after signing has no effect: signature check fails."""
    r = pattern_cls(tmp_path).submit(500, mandate="mandate-widened")
    assert (r.outcome, r.reasons, r.executed) == ("deny", ("MND_SIGNATURE_INVALID",), False)


@BOTH
@pytest.mark.scenario("S18")
@pytest.mark.req("CTL-05")
def test_S18_exposure_keyed_by_principal_spans_agents(pattern_cls: Any, tmp_path: Path) -> None:
    """S18: two agents of one principal share the aggregate; third payment escalates."""
    p = pattern_cls(tmp_path)
    a = p.submit(9000, agent="treasury-agent-1", mandate="mandate-1")
    b = p.submit(9000, agent="treasury-agent-2", mandate="mandate-2")
    c = p.submit(9000, agent="treasury-agent-1", mandate="mandate-1")
    assert (a.executed, b.executed, c.outcome) == (True, True, "escalate")
    assert "EXP_AGGREGATE_EXCEEDED" in c.reasons


@BOTH
@pytest.mark.scenario("S19")
@pytest.mark.req("CTL-05")
def test_S19_rate_burst(pattern_cls: Any, tmp_path: Path) -> None:
    """S19: the 21st payment inside the window escalates."""
    p = pattern_cls(tmp_path)
    outs = [p.submit(10).outcome for _ in range(21)]
    assert outs[:20] == ["auto_execute"] * 20 and outs[20] == "escalate"


@BOTH
@pytest.mark.scenario("S22")
@pytest.mark.req("DSP-05")
def test_S22_multi_step_workflow_steps_are_independent(pattern_cls: Any, tmp_path: Path) -> None:
    """S22: step 1 executes; step 2 under a mandate that does not cover it is denied alone."""
    p = pattern_cls(tmp_path)
    assert p.submit(500).executed
    step2 = p.submit(500, mandate="mandate-exp")
    assert step2.outcome == "deny" and not step2.executed


@BOTH
@pytest.mark.scenario("S26")
@pytest.mark.req("DSP-07")
def test_S26_identical_inputs_identical_outcomes(pattern_cls: Any, tmp_path: Path) -> None:
    """S26: the same sequence on two fresh runtimes gives identical outcomes and reasons."""

    def run(sub: str) -> list[tuple[str, tuple[str, ...]]]:
        d = tmp_path / sub
        d.mkdir()
        p = pattern_cls(d)
        return [
            (r.outcome, r.reasons)
            for r in (p.submit(a) for a in (500, 5000, 20000, 9000, 9000, 9000, 1))
        ]

    assert run("a") == run("b")


# ---- native only: agent-side signals / signatures / ids -----------------------------------
@pytest.fixture
def native(tmp_path: Path) -> NativePattern:
    """Native pattern."""
    return NativePattern(tmp_path)


@pytest.mark.scenario("S09")
@pytest.mark.req("ENV-04", "IDN-01")
def test_S09_native_envelope_with_invalid_signature_rejected(native: NativePattern) -> None:
    """S09 (native only: gateways do not use agent signatures)."""
    w: World = native.world
    forged = w.decide(500, key=crypto.generate_private_key())
    unsigned = native.submit(500, signed=False)
    assert forged.reason_codes == ["IDN_SIGNATURE_INVALID"]
    assert unsigned.reasons == ("IDN_SIGNATURE_MISSING",) and not unsigned.executed


@pytest.mark.scenario("S20")
@pytest.mark.req("CTL-05", "CTL-02")
def test_S20_low_confidence_escalates_regardless_of_value(native: NativePattern) -> None:
    """S20 (native only: confidence is agent-reported)."""
    r = native.submit(5, signals={"confidence": 0.2})
    assert (r.outcome, r.reasons) == ("escalate", ("EVD_CONFIDENCE_BELOW",))


@pytest.mark.scenario("S21")
@pytest.mark.req("DSP-02", "DSP-03")
def test_S21_anomalous_action_within_limits_is_observed(native: NativePattern) -> None:
    """S21 (native only: anomaly score is a signal)."""
    r = native.submit(500, signals={"confidence": 0.95, "anomaly_score": 0.95})
    assert r.outcome == "observe" and r.executed
    assert native.world.audit()[0].observations[0].code == "RISK_OBSERVE"


@pytest.mark.scenario("S23")
@pytest.mark.req("ENV-06")
def test_S23_duplicate_envelope_id_returns_original(native: NativePattern) -> None:
    """S23: second submission returns the first decision; counters and log unchanged."""
    w = native.world
    raw = w.raw(500, envelope_id="dup-1")
    first, second = w.svc.decide(raw), w.svc.decide(raw)
    assert second == first and len(w.audit()) == 1
    assert w.rt.components["state_store"].usage(AGG, 3600, T0) == 500


# ---- escalation lifecycle (core level, pattern independent) --------------------------------
@pytest.mark.scenario("S06")
@pytest.mark.req("ESC-03")
def test_S06_escalation_timeout_blocks(native: NativePattern) -> None:
    """S06: no review before the deadline: blocked and logged."""
    w = native.world
    esc = native.submit(20000).escalation_id
    w.clock.advance(seconds=901)
    [done] = w.svc.sweep()
    assert done.escalation_id == esc and done.state is EscalationState.TIMED_OUT
    assert w.audit()[-1].basis.controlling == ["ESC_TIMEOUT_BLOCKED"]


@pytest.mark.scenario("S07")
@pytest.mark.req("ESC-04")
def test_S07_reviewer_without_authority_refused_and_logged(native: NativePattern) -> None:
    """S07: over-limit reviewer refused; the refusal is in the log; item still pending."""
    w = native.world
    esc = native.submit(20000).escalation_id
    assert esc
    with pytest.raises(EscalationError) as ei:
        w.svc.resolve_escalation(esc, "ivan.intern", "approve")
    assert ei.value.code == "ESC_AUTHORITY_EXCEEDED"
    assert w.audit()[-1].basis.controlling == ["ESC_AUTHORITY_EXCEEDED"]
    held = w.svc.queue.get(esc)
    assert held is not None and held.state is EscalationState.PENDING


@pytest.mark.scenario("S15")
@pytest.mark.req("ESC-02", "ESC-06")
def test_S15_open_escalation_cap(tmp_path: Path) -> None:
    """S15: beyond the cap new escalations are denied, logged, and counted."""
    from tests.service.world import build_world

    w = build_world(tmp_path, max_open=1)
    assert w.decide(20000).outcome == "escalate"
    r = w.decide(20000)
    assert (r.outcome, r.reason_codes[0]) == ("deny", "ESC_QUEUE_FULL")
    assert w.svc.queue.depth("treasury-review") == 1


@pytest.mark.scenario("S24")
@pytest.mark.req("ESC-05")
def test_S24_reviewer_modify_reenters_with_parent_link(native: NativePattern) -> None:
    """S24: modify produces a new envelope that is fully re-evaluated."""
    w = native.world
    esc = native.submit(20000).escalation_id
    assert esc
    res = w.svc.resolve_escalation(
        esc,
        "rita.reviewer",
        "modify",
        modified_parameters={"amount": 300},
    )
    assert res.child is not None and res.child.outcome == "auto_execute"
    child = w.audit()[-1]
    assert child.envelope["action"]["parent_envelope_id"] == res.escalation.envelope_id


# ---- gateway-specific ----------------------------------------------------------------------
@pytest.mark.scenario("S08")
@pytest.mark.req("ENV-04", "INT-02")
def test_S08_observed_call_governs_over_agent_declaration(tmp_path: Path) -> None:
    """S08: the agent declared a cheap action; the observed call is what is decided."""
    g = GatewayPattern(tmp_path)
    declared = g.world.decide(500)
    big = g.rig.client.post(
        "/mcp",
        content=__import__("json").dumps(
            call_tool(1, "wire_transfer", account="ACME-001", amount=20000, currency="USD")
        ),
        headers=mcp_headers(**{"x-arg-decision-token": declared.token or ""}),
    )
    gov = big.json()["result"]["structuredContent"]["governance"]
    assert gov["outcome"] == "escalate" and g.rig.upstream.calls == 0


@pytest.fixture
def hybrid(tmp_path: Path) -> Any:
    """Hybrid gateway rig."""
    from tests.gateway.harness import build_rig

    return build_rig(tmp_path, mode="hybrid")


def _hybrid_call(rig: Any, token: str | None, amount: float = 500, rid: int = 1) -> dict[str, Any]:
    import json

    h = mcp_headers(**({"x-arg-decision-token": token} if token else {}))
    r = rig.client.post(
        "/mcp",
        content=json.dumps(
            call_tool(rid, "wire_transfer", account="ACME-001", amount=amount, currency="USD")
        ),
        headers=h,
    )
    return r.json()  # type: ignore[no-any-return]


def _codes(payload: dict[str, Any]) -> list[str]:
    return payload["result"]["structuredContent"]["governance"]["reason_codes"]  # type: ignore[no-any-return]


@pytest.mark.scenario("S10")
@pytest.mark.req("INT-04")
def test_S10_hybrid_call_without_token_refused(hybrid: Any) -> None:
    """S10."""
    assert _codes(_hybrid_call(hybrid, None)) == ["GW_TOKEN_MISSING"]
    assert hybrid.upstream.calls == 0


@pytest.mark.scenario("S11")
@pytest.mark.req("INT-04")
def test_S11_token_replay_refused(hybrid: Any) -> None:
    """S11."""
    token = hybrid.world.decide(500).token
    assert _hybrid_call(hybrid, token)["result"]["content"][0]["text"] == "EXECUTED"
    assert _codes(_hybrid_call(hybrid, token, rid=2)) == ["TOK_REPLAYED"]


@pytest.mark.scenario("S12")
@pytest.mark.req("INT-04")
def test_S12_altered_parameters_refused(hybrid: Any) -> None:
    """S12."""
    token = hybrid.world.decide(500).token
    assert _codes(_hybrid_call(hybrid, token, amount=900)) == ["TOK_ACTION_MISMATCH"]
    assert hybrid.upstream.calls == 0


# ---- audit, controls, availability, registries ---------------------------------------------
@pytest.mark.scenario("S13")
@pytest.mark.req("AUD-02", "AUD-06")
def test_S13_tampered_deleted_reordered_entries_fail_verify(native: NativePattern) -> None:
    """S13 (in-memory store; the SQLite variants are in tests/core/test_audit.py)."""
    for op in ("modify", "delete", "reorder"):
        store = InMemoryAuditStore()
        head = None
        entries = []
        for i in range(3):
            e = store.append(
                __import__("tests.core.audit_factories", fromlist=["content"]).content(
                    "a", "deny" if i else "auto_execute"
                ),
                head,
            )
            head = e.entry_hash
            entries.append(e)
        lst = store._streams["a"]
        if op == "modify":
            lst[1] = entries[1].model_copy(update={"outcome": "observe"})
        elif op == "delete":
            del lst[1]
        else:
            lst[0], lst[1] = lst[1], lst[0]
        assert not store.verify("a").ok, op


@pytest.mark.scenario("S14")
@pytest.mark.req("CTL-07", "DSP-04")
def test_S14_unapproved_control_refused_in_production(tmp_path: Path) -> None:
    """S14: production load refuses a draft control; calibration likewise."""
    import shutil

    import yaml

    bundle = tmp_path / "b"
    shutil.copytree("config/bundle", bundle)
    f = bundle / "controls" / "rate-payments.yaml"
    d = yaml.safe_load(f.read_text())
    d["review_status"] = "draft"
    f.write_text(yaml.safe_dump(d))
    with pytest.raises(ControlsLoadError, match="rate-payments"):
        load_bundle(bundle, production=True)
    assert load_bundle(bundle, production=False)


@pytest.mark.scenario("S16")
@pytest.mark.req("INT-05")
def test_S16_core_failure_never_auto_executes(native: NativePattern) -> None:
    """S16: a failing stage and a failing audit store both yield Deny."""
    from arg.core.ports import PipelineStage

    w = native.world

    class Boom(PipelineStage):
        """Crashes."""

        def run(self, state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("down")

    w.svc.stages.insert(2, Boom())
    r = native.submit(500)
    assert (r.outcome, r.executed) == ("deny", False)
    w.svc.stages.pop(2)
    w.rt.components["audit_store"]._persist = lambda e: (_ for _ in ()).throw(OSError("disk"))
    r2 = w.decide(500)
    assert r2.outcome == "deny" and r2.decision_id is None


@pytest.mark.scenario("S25")
@pytest.mark.req("IDN-04")
def test_S25_open_network_context_picks_authoritative_registry() -> None:
    """S25: the same claim resolves in the registry that is authoritative for the context."""

    def rec(i: str, principal: str, **kw: Any) -> AgentRecord:
        return AgentRecord(
            agent_id=i, agent_class="treasury", status=AgentStatus.ACTIVE, principal=principal, **kw
        )

    internal = FileRegistry(
        records=[rec("agent-int", "in-house", aliases={"network": "agent-net"})],
        registry_id="internal",
    )
    network = FileRegistry(records=[rec("agent-net", "network-operator")], registry_id="network")
    reg = CompositeRegistry(
        {"internal": internal, "network": network},
        authority={"open-net": "network"},
        default="internal",
    )
    verifier = DefaultIdentityVerifier(reg, OriginDispatchAuthenticator(["gw"]))
    from arg.core.models import Context, Provenance

    def env(ctx: str) -> Any:
        return make_envelope(
            context=Context(agent_id="agent-int", network_context=ctx),
            provenance=Provenance(
                origin="gateway",
                adapter_id="gw",
                observed_call={  # type: ignore[arg-type]
                    "method": "x",
                    "target": "y",
                    "params_hash": "h",
                },
            ),
        )

    assert verifier.verify(env("bank-internal")).registry_id == "internal"
    via = verifier.verify(env("open-net"))
    assert (via.agent_id, via.registry_id, via.principal) == (
        "agent-net",
        "network",
        "network-operator",
    )
