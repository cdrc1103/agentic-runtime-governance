"""End-to-end decisions through the wired pipeline (scenarios S01-S06, S09, S15-S19, S22-S24)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from arg.core.decision.stages import ReserveStage
from arg.core.models import (
    EscalationState,
    Outcome,
    Reservation,
    StageRejection,
)
from arg.core.ports import PipelineStage
from arg.core.state.memory import InMemoryStateStore
from tests.core.factories import T0
from tests.service.world import World, build_world

AGG_KEY = "exposure-payment-aggregate:principal:alice.example"
RATE_KEY = "rate-payments:agent:treasury-agent-1"


@pytest.fixture(params=["memory", "sqlite"])
def w(request: Any, tmp_path: Path) -> World:
    """A world over each pair of store implementations."""
    return build_world(tmp_path, state=request.param, audit=request.param)


@pytest.mark.req("DSP-02", "AUD-01", "AUD-03")
def test_s01_auto_execute_is_audited_and_reserved(w: World) -> None:
    """S01: in-limit payment proceeds; entry carries rules and timings; counters move."""
    r = w.decide(500)
    assert r.outcome == "auto_execute" and r.decision_id == "treasury-agent-1#1"
    assert (
        r.policy_version and r.rules_applied and set(r.stage_timings_ms) >= {"identity", "evaluate"}
    )
    [e] = w.audit()
    assert e.outcome == "auto_execute" and e.decided_at_stage == "engine"
    assert e.identity_result.principal == "alice.example" and e.mandate_snapshot is not None
    store = w.rt.components["state_store"]
    assert store.usage(AGG_KEY, 3600, T0) == 500 and store.usage(RATE_KEY, 60, T0) == 1
    assert w.rt.components["audit_store"].verify("treasury-agent-1").ok


@pytest.mark.req("ENV-06")
def test_s23_duplicate_envelope_returns_original_without_second_reservation(w: World) -> None:
    """S23: same envelope_id twice yields the first decision; one audit entry; one reservation."""
    raw = w.raw(500, envelope_id="dup-1")
    first = w.svc.decide(raw)
    second = w.svc.decide(raw)
    assert second == first and len(w.audit()) == 1
    assert w.rt.components["state_store"].usage(AGG_KEY, 3600, T0) == 500


@pytest.mark.req("ESC-01", "DSP-02", "CTL-05")
def test_s02_escalation_holds_action(w: World) -> None:
    """S02: above the per-action limit the action is held pending; nothing reserved."""
    r = w.decide(20000)
    assert r.outcome == "escalate" and r.escalation_id == "esc-env-0001"
    rec = w.svc.queue.get(r.escalation_id)
    assert rec is not None and rec.state is EscalationState.PENDING
    assert rec.decision_id == r.decision_id and rec.amount == 20000
    assert w.rt.components["state_store"].usage(AGG_KEY, 3600, T0) == 0
    assert w.audit()[0].escalation_id == r.escalation_id


@pytest.mark.req("IDN-01", "IDN-02", "IDN-05", "AUD-01")
def test_s05_unregistered_and_suspended_rejected_at_identity_and_logged(w: World) -> None:
    """S05: rejection at identity stage; audited; controls never retrieved."""
    retrieved: list[str] = []

    class Spy(PipelineStage):
        """Records that controls retrieval was reached."""

        def run(self, state: dict[str, Any]) -> dict[str, Any]:
            retrieved.append("x")
            return state

    w.svc.stages.insert(2, Spy())  # right after identity
    ghost = w.decide(500, agent="ghost-agent")
    susp = w.decide(500, agent="suspended-agent")
    assert (ghost.outcome, ghost.decided_at_stage, ghost.reason_codes) == (
        "deny",
        "identity",
        ["IDN_AGENT_UNKNOWN"],
    )
    assert susp.reason_codes == ["IDN_AGENT_SUSPENDED"] and retrieved == []
    [e] = w.audit("suspended-agent")
    assert (
        e.identity_result.status == "rejected" and e.identity_result.code == "IDN_AGENT_SUSPENDED"
    )


@pytest.mark.req("ENV-04", "IDN-01")
def test_s09_invalid_signature_rejected(w: World) -> None:
    """S09: wrong key, and unsigned, native envelopes are rejected."""
    from arg.core import crypto

    forged = w.decide(500, key=crypto.generate_private_key())
    unsigned = w.decide(500, sign=False)
    assert forged.reason_codes == ["IDN_SIGNATURE_INVALID"]
    assert unsigned.reason_codes == ["IDN_SIGNATURE_MISSING"]


@pytest.mark.req("CTL-03", "CTL-04", "AUD-01")
def test_s04_expired_mandate_denied_at_mandate_stage(w: World) -> None:
    """S04: an expired mandate denies before controls are applied; recorded."""
    r = w.decide(500, mandate="mandate-exp")
    assert (r.outcome, r.decided_at_stage, r.reason_codes) == ("deny", "mandate", ["MND_EXPIRED"])
    assert w.audit()[0].identity_result.status == "confirmed"


@pytest.mark.req("ENV-03", "AUD-01")
def test_validation_failures_are_recorded(w: World) -> None:
    """Incomplete and malformed envelopes are denied at validation and still audited."""
    raw = w.raw(500)
    del raw["action"]["parameters"]["currency"]
    missing = w.svc.decide(raw)
    garbage = w.svc.decide({"nonsense": 1})
    assert missing.decided_at_stage == "validation" and missing.reason_codes == [
        "ENV_PARAMETER_MISSING"
    ]
    assert garbage.reason_codes == ["ENV_SCHEMA_INVALID"]
    assert w.audit("_unattributed")[0].envelope == {"nonsense": 1}


@pytest.mark.req("INT-05")
def test_s16_internal_error_fails_closed_and_is_audited(w: World) -> None:
    """S16: a crashing stage yields Deny SYSTEM_ERROR, never Auto-Execute."""

    class Boom(PipelineStage):
        """Always fails."""

        def run(self, state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    w.svc.stages.insert(3, Boom())
    r = w.decide(500)
    assert (r.outcome, r.reason_codes) == ("deny", ["SYSTEM_ERROR"])
    assert w.audit()[0].basis.controlling == ["SYSTEM_ERROR"]
    assert w.rt.components["state_store"].usage(AGG_KEY, 3600, T0) == 0


@pytest.mark.req("INT-05", "AUD-02")
def test_audit_failure_releases_reservation_and_denies(w: World) -> None:
    """SG-04: if the audit append fails after reserving, the reservation is released."""
    audit = w.rt.components["audit_store"]
    audit._persist = lambda entry: (_ for _ in ()).throw(RuntimeError("disk full"))
    r = w.decide(500)
    assert r.outcome == "deny" and r.decision_id is None and r.reason_codes == ["SYSTEM_ERROR"]
    assert w.rt.components["state_store"].usage(AGG_KEY, 3600, T0) == 0
    assert w.rt.components["state_store"].usage(RATE_KEY, 60, T0) == 0


@pytest.mark.req("CTL-05")
def test_s03_aggregate_exposure_across_small_actions(w: World) -> None:
    """S03: individually fine payments add up; the one that crosses the aggregate escalates."""
    outcomes = [w.decide(9000).outcome for _ in range(3)]
    assert outcomes == ["observe", "observe", "escalate"]
    assert w.rt.components["state_store"].usage(AGG_KEY, 3600, T0) == 18000
    nxt = w.clock.now + timedelta(hours=1)
    w.clock.now = nxt  # new fixed window: capacity is back
    assert w.decide(9000).outcome == "observe"


@pytest.mark.req("CTL-05")
def test_s18_principal_keyed_exposure_spans_agent_identities(w: World) -> None:
    """S18: two agents of one principal share the aggregate; another principal does not."""
    a1 = w.decide(9000, agent="treasury-agent-1", mandate="mandate-1")
    a2 = w.decide(9000, agent="treasury-agent-2", mandate="mandate-2")
    a3 = w.decide(9000, agent="treasury-agent-1", mandate="mandate-1")
    assert (a1.outcome, a2.outcome, a3.outcome) == ("observe", "observe", "escalate")
    assert "EXP_AGGREGATE_EXCEEDED" in a3.reason_codes


@pytest.mark.req("CTL-05")
def test_s19_rate_burst_escalates_after_threshold(w: World) -> None:
    """S19: the 21st payment inside a minute escalates; a minute later it is fine."""
    outcomes = [w.decide(10).outcome for _ in range(21)]
    assert outcomes[:20] == ["auto_execute"] * 20 and outcomes[20] == "escalate"
    w.clock.advance(seconds=61)
    assert w.decide(10).outcome == "auto_execute"


@pytest.mark.req("CTL-05", "CTL-02")
def test_s20_low_confidence_escalates_regardless_of_value(w: World) -> None:
    """S20: tiny amount, weak evidence: escalate."""
    r = w.decide(5, signals={"confidence": 0.3})
    assert r.outcome == "escalate" and r.reason_codes == ["EVD_CONFIDENCE_BELOW"]


@pytest.mark.req("DSP-02", "DSP-03")
def test_s21_anomaly_observed_and_recorded(w: World) -> None:
    """S21: anomalous but within limits: proceeds, observation recorded."""
    r = w.decide(500, signals={"confidence": 0.95, "anomaly_score": 0.9})
    assert r.outcome == "observe" and r.observations
    assert w.audit()[0].observations[0].code == "RISK_OBSERVE"


@pytest.mark.req("DSP-05")
def test_s22_each_step_evaluated_independently(w: World) -> None:
    """S22: step 1 auto-executes; step 2 (mandate lacks permission) is denied on its own."""
    assert w.decide(500).outcome == "auto_execute"
    w.rt.components["mandate_resolver"]._mandates["mandate-1"] = w.rt.components[
        "mandate_resolver"
    ]._mandates["mandate-exp"]
    step2 = w.decide(500)
    assert step2.outcome == "deny"


def test_reserve_stage_all_or_nothing() -> None:
    """A refused reservation releases those already made and rejects (SG-04)."""
    store = InMemoryStateStore()
    store.reserve("b", 95, 100, 60, T0)
    stage = ReserveStage(store)
    from arg.core.models import Disposition, Level, RiskProfile

    profile = RiskProfile(None, Level.LOW, None, None, False, 0, Outcome.AUTO_EXECUTE)
    disp = Disposition(Outcome.AUTO_EXECUTE, (), (), profile)
    specs = [
        Reservation(key="a", amount=10, limit=100, window_seconds=60),
        Reservation(key="b", amount=10, limit=100, window_seconds=60),
    ]
    with pytest.raises(StageRejection, match="STATE_RESERVATION_REFUSED"):
        stage.run({"disposition": disp, "specs": specs, "now": T0})
    assert store.usage("a", 60, T0) == 0 and store.usage("b", 60, T0) == 95
    held = Disposition(Outcome.ESCALATE, (), (), profile)
    assert stage.run({"disposition": held, "specs": specs, "now": T0})["reserved"] == []


@pytest.mark.req("ENV-01")
def test_no_action_proceeds_without_declaration_authorisation_and_assessment(w: World) -> None:
    """Only a well-formed, authenticated, assessed envelope can reach Auto-Execute."""
    bare_action = {"type": "payment.initiate", "amount": 500}  # no envelope around it
    assert w.svc.decide(bare_action).outcome == "deny"
    ok = w.decide(500)
    assert ok.outcome == "auto_execute"
    [entry] = [e for e in w.audit() if e.outcome == "auto_execute"]
    assert entry.identity_result.status == "confirmed"  # declared + authenticated
    assert entry.mandate_snapshot is not None  # authorised
    assert entry.rules_applied and entry.policy_version  # assessed against controls
    # every proceeding outcome in the log has all three
    for e in w.audit():
        if e.outcome in ("auto_execute", "observe"):
            assert e.identity_result.status == "confirmed" and e.rules_applied
