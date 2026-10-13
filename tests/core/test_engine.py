"""Evaluators, calibration, resolution, and the disposition engine (CTL-05, DSP-01..07)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from arg.core.controls.bundle import load_bundle
from arg.core.engine.calibrator import ConfigRiskCalibrator
from arg.core.engine.disposition import DispositionEngine
from arg.core.engine.evaluators import (
    AuthorisationEvaluator,
    EvidenceEvaluator,
    ExposureEvaluator,
    RateEvaluator,
)
from arg.core.engine.keys import counter_key
from arg.core.engine.resolution import PrecedenceResolutionPolicy
from arg.core.models import (
    Action,
    ActionTrace,
    Calibration,
    Context,
    Control,
    ControlsLoadError,
    Effect,
    EvaluationContext,
    Finding,
    IdentityBinding,
    Mandate,
    MandateLimits,
    Outcome,
)
from tests.core.factories import T0, make_envelope, step

ESC = {"queue": "q", "timeout_seconds": 60, "reviewer_role": "r"}
BASE: dict[str, Any] = {
    "version": 1,
    "source": "policy",
    "owner": "risk",
    "review_status": "approved",
    "effect": "deny",
}


def ctl(control_id: str, category: str, logic: dict[str, Any], **kw: Any) -> Control:
    """Build a control."""
    return Control(**{**BASE, "control_id": control_id, "category": category, "logic": logic, **kw})


ID = IdentityBinding(
    agent_id="treasury-agent-1",
    agent_class="treasury",
    principal="alice.example",
    registry_id="default",
    origin="native",
)
MANDATE = Mandate(
    mandate_id="mandate-1",
    principal="alice.example",
    agent_id="treasury-agent-1",
    permitted_actions=["payment.initiate"],
    limits=MandateLimits(per_action=5000),
    not_before=T0 - timedelta(days=1),
    not_after=T0 + timedelta(days=1),
)


def ctx(
    amount: float = 500,
    mandate: Mandate | None = MANDATE,
    state: dict[str, float] | None = None,
    signals: dict[str, Any] | None = None,
    identity: IdentityBinding = ID,
    **env: Any,
) -> EvaluationContext:
    """Evaluation context for a payment of ``amount``."""
    envelope = make_envelope(
        action=Action(type="payment.initiate", scope="s", parameters={"amount": amount}),
        **env,
    )
    return EvaluationContext(
        envelope,
        identity,
        T0,
        mandate,
        state or {},
        signals if signals is not None else {"confidence": 0.95},
    )


def fired(evaluator: Any, control: Control, c: EvaluationContext) -> list[str]:
    """Reason codes of fired findings."""
    return [f.reason_code for f in evaluator.evaluate(control, c) if f.result == "fire"]


# ---- authorisation ---------------------------------------------------------------------
@pytest.mark.req("CTL-05", "DSP-01")
def test_authorisation_conditions() -> None:
    """Action type, mandate presence/scope/window/agent/principal, and depth are enforced."""
    e = AuthorisationEvaluator()
    c = ctl(
        "auth",
        "authorisation",
        {
            "type": "authorisation",
            "permitted_action_types": ["payment.initiate"],
            "max_delegation_depth": 1,
        },
    )
    assert fired(e, c, ctx()) == []
    assert fired(e, c, ctx(mandate=None)) == ["AUTH_MANDATE_MISSING"]
    narrow = ctl(
        "a2", "authorisation", {"type": "authorisation", "permitted_action_types": ["fx.trade"]}
    )
    assert fired(e, narrow, ctx()) == ["AUTH_ACTION_TYPE_NOT_PERMITTED"]
    m = MANDATE.model_copy(update={"permitted_actions": ["fx.trade"]})
    assert fired(e, c, ctx(mandate=m)) == ["AUTH_ACTION_NOT_IN_MANDATE"]
    old = MANDATE.model_copy(update={"not_after": T0 - timedelta(seconds=1)})
    assert fired(e, c, ctx(mandate=old)) == ["AUTH_MANDATE_OUTSIDE_VALIDITY"]
    other = MANDATE.model_copy(update={"agent_id": "someone"})
    assert fired(e, c, ctx(mandate=other)) == ["AUTH_MANDATE_AGENT_MISMATCH"]
    bob = MANDATE.model_copy(update={"principal": "bob.example"})
    assert fired(e, c, ctx(mandate=bob)) == ["AUTH_PRINCIPAL_MISMATCH"]
    deep = MANDATE.model_copy(update={"depth": 2, "delegation_chain": ["x", "y"]})
    assert fired(e, c, ctx(mandate=deep)) == ["AUTH_DELEGATION_DEPTH_EXCEEDED"]
    optional = ctl("a3", "authorisation", {"type": "authorisation", "require_mandate": False})
    assert fired(e, optional, ctx(mandate=None)) == []


# ---- exposure --------------------------------------------------------------------------
@pytest.mark.req("CTL-05")
def test_exposure_per_action_aggregate_and_mandate_limit() -> None:
    """Per-action and aggregate limits; mandate-granted limit narrows the control limit."""
    e = ExposureEvaluator()
    per = ctl(
        "per",
        "exposure",
        {"type": "exposure", "scope": "per_action", "amount_parameter": "amount", "limit": 10000},
    )
    assert fired(e, per, ctx(10000)) == []
    assert fired(e, per, ctx(10000.01)) == ["EXP_PER_ACTION_EXCEEDED"]
    assert fired(e, per, ctx(amount="lots")) == ["EXP_AMOUNT_UNREADABLE"]  # type: ignore[arg-type]
    capped = ctl(
        "cap",
        "exposure",
        {
            "type": "exposure",
            "scope": "per_action",
            "amount_parameter": "amount",
            "limit": 10000,
            "apply_mandate_limit": True,
        },
    )
    assert fired(e, capped, ctx(6000)) == ["EXP_PER_ACTION_EXCEEDED"]  # mandate grants 5000
    agg = ctl(
        "agg",
        "exposure",
        {
            "type": "exposure",
            "scope": "aggregate",
            "amount_parameter": "amount",
            "limit": 3000,
            "window_seconds": 3600,
        },
    )
    key = counter_key(agg, ctx())
    assert fired(e, agg, ctx(1000, state={key: 2000})) == []
    assert fired(e, agg, ctx(1001, state={key: 2000})) == ["EXP_AGGREGATE_EXCEEDED"]


@pytest.mark.req("CTL-05")
def test_counter_key_by_principal_spans_agent_identities() -> None:
    """S18: keyed by principal, two agents of one principal share a counter."""
    agg = ctl(
        "agg",
        "exposure",
        {
            "type": "exposure",
            "scope": "aggregate",
            "amount_parameter": "amount",
            "limit": 100,
            "key_by": "principal",
        },
    )
    a2 = ID.model_copy(update={"agent_id": "treasury-agent-2"})
    assert counter_key(agg, ctx()) == counter_key(agg, ctx(identity=a2))
    by_agent = ctl(
        "agg2",
        "exposure",
        {"type": "exposure", "scope": "aggregate", "amount_parameter": "amount", "limit": 100},
    )
    assert counter_key(by_agent, ctx()) != counter_key(by_agent, ctx(identity=a2))
    bad = ctl("agg3", "exposure", {"type": "exposure", "key_by": "nobody"})
    with pytest.raises(ValueError, match="key_by"):
        counter_key(bad, ctx())


# ---- rate / evidence ---------------------------------------------------------------------
@pytest.mark.req("CTL-05")
def test_rate_limit() -> None:
    """S19: the action that would exceed max_actions in the window fires."""
    e = RateEvaluator()
    c = ctl("rate", "rate", {"type": "rate", "max_actions": 3, "window_seconds": 60})
    key = counter_key(c, ctx())
    assert fired(e, c, ctx(state={key: 2})) == []
    assert fired(e, c, ctx(state={key: 3})) == ["RATE_EXCEEDED"]


@pytest.mark.req("CTL-05", "CTL-02")
def test_evidence_quality_applies_regardless_of_value() -> None:
    """S20: low confidence fires even for a tiny amount; missing signal and evidence fire."""
    e = EvidenceEvaluator()
    c = ctl(
        "evd",
        "evidence",
        {"type": "evidence", "min_confidence": 0.8, "required_evidence": ["lookup_balance"]},
        kind="ai_specific",
    )
    assert fired(e, c, ctx(1.0)) == []
    assert fired(e, c, ctx(1.0, signals={"confidence": 0.5})) == ["EVD_CONFIDENCE_BELOW"]
    assert fired(e, c, ctx(1.0, signals={})) == ["EVD_SIGNAL_MISSING"]
    empty = ctx(1.0, action_trace=ActionTrace(steps=[]))
    assert fired(e, c, empty) == ["EVD_REQUIRED_MISSING"]
    assert fired(e, c, ctx(1.0, action_trace=ActionTrace(steps=[step(1)]))) == []


# ---- resolution ------------------------------------------------------------------------
@pytest.mark.req("DSP-02", "DSP-06")
def test_precedence_deny_over_escalate_over_observe_over_auto() -> None:
    """The most restrictive fired effect (or risk indication) wins."""
    p = PrecedenceResolutionPolicy()

    def f(effect: Effect | None) -> Finding:
        return Finding("c", 1, "fire" if effect else "pass", effect)

    assert p.resolve([], Outcome.AUTO_EXECUTE) is Outcome.AUTO_EXECUTE
    assert p.resolve([f(Effect.OBSERVE)], Outcome.AUTO_EXECUTE) is Outcome.OBSERVE
    assert (
        p.resolve([f(Effect.OBSERVE), f(Effect.ESCALATE)], Outcome.AUTO_EXECUTE) is Outcome.ESCALATE
    )
    assert p.resolve([f(Effect.ESCALATE), f(Effect.DENY)], Outcome.OBSERVE) is Outcome.DENY
    assert p.resolve([f(None)], Outcome.ESCALATE) is Outcome.ESCALATE


# ---- calibration -----------------------------------------------------------------------
CAL = Path("config/bundle/calibration.yaml")


@pytest.mark.req("DSP-03", "DSP-04")
def test_calibration_bands_novelty_and_thresholds() -> None:
    """Materiality band, novelty, and score thresholds drive the indicated outcome."""
    cal = ConfigRiskCalibrator(CAL)
    low = cal.calibrate(ctx(500))
    assert (low.materiality.value, low.score, low.indicated_outcome) == (
        "low",
        2,
        Outcome.AUTO_EXECUTE,
    )
    mid = cal.calibrate(ctx(5000))
    assert (mid.materiality.value, mid.indicated_outcome) == ("medium", Outcome.OBSERVE)
    novel = cal.calibrate(ctx(500, signals={"anomaly_score": 0.9}))
    assert novel.novelty and novel.indicated_outcome is Outcome.OBSERVE  # S21 shape
    high = cal.calibrate(ctx(50000, signals={"anomaly_score": 0.9}))
    assert (high.score, high.indicated_outcome) == (5, Outcome.ESCALATE)
    assert high.escalation is not None
    unreadable = cal.calibrate(ctx(amount="x"))  # type: ignore[arg-type]
    assert "RISK_MATERIALITY_UNREADABLE" in unreadable.reason_codes
    assert unreadable.materiality.value == "high"
    other = make_envelope(action=Action(type="wire.exotic", scope="s"))
    unk = cal.calibrate(EvaluationContext(other, ID, T0))
    assert unk.indicated_outcome is Outcome.DENY and unk.reason_codes == (
        "RISK_UNCALIBRATED_ACTION",
    )


@pytest.mark.req("DSP-04")
def test_production_refuses_unapproved_calibration() -> None:
    """Calibration must be reviewed (approved) before production use."""
    raw = Calibration(**{**yaml.safe_load(CAL.read_text()), "review_status": "draft"})
    with pytest.raises(ControlsLoadError):
        ConfigRiskCalibrator(calibration=raw)
    assert ConfigRiskCalibrator(calibration=raw, production=False)
    with pytest.raises(ValueError, match="path or calibration"):
        ConfigRiskCalibrator()


def test_calibration_file_validation() -> None:
    """Threshold ordering and band shape are validated at load."""
    from arg.core.models import ActionCalibration

    ok: dict[str, Any] = {
        "reversibility": "reversible",
        "customer_impact": "low",
        "regulatory_sensitivity": "low",
        "observe_at": 1,
        "escalate_at": 2,
        "deny_at": 3,
    }
    assert ActionCalibration(**ok)
    with pytest.raises(ValueError, match="observe_at"):
        ActionCalibration(**{**ok, "observe_at": 5})
    with pytest.raises(ValueError, match="go together"):
        ActionCalibration(**{**ok, "materiality_parameter": "amount"})

    def band(u: float | None) -> dict[str, Any]:
        return {"upper": u, "level": "low"}

    with pytest.raises(ValueError, match="unbounded"):
        ActionCalibration(**{**ok, "materiality_parameter": "a", "materiality_bands": [band(1)]})
    with pytest.raises(ValueError, match="ascending"):
        ActionCalibration(
            **{
                **ok,
                "materiality_parameter": "a",
                "materiality_bands": [band(5), band(1), band(None)],
            }
        )


# ---- engine ----------------------------------------------------------------------------
def engine() -> tuple[DispositionEngine, list[Control]]:
    """Engine over the built-in evaluators and the sample bundle plus rate/evidence/observe."""
    ev = {
        "authorisation": AuthorisationEvaluator(),
        "exposure": ExposureEvaluator(),
        "rate": RateEvaluator(),
        "evidence": EvidenceEvaluator(),
    }
    controls = list(load_bundle(Path("config/bundle")).controls) + [
        ctl(
            "evidence-min",
            "evidence",
            {"type": "evidence", "min_confidence": 0.8},
            effect="escalate",
            escalation=ESC,
            kind="ai_specific",
        ),
    ]
    return DispositionEngine(ev, ConfigRiskCalibrator(CAL), PrecedenceResolutionPolicy()), controls


def decide(amount: float = 500, **kw: Any) -> Any:
    """Run the engine for a payment."""
    eng, controls = engine()
    c = ctx(amount, **kw)
    return eng.evaluate(
        c.envelope, c.identity, controls, c.state, c.signals, at=T0, mandate=c.mandate
    )


@pytest.mark.req("DSP-01", "DSP-02")
def test_engine_outcomes_end_to_end() -> None:
    """S01/S02/S21/S04-shape through the engine with the sample bundle."""
    ok = decide(500)
    assert ok.outcome is Outcome.AUTO_EXECUTE and ok.reason_codes == ()
    over = decide(20000, signals={"confidence": 0.95, "anomaly_score": 0.9})
    assert over.outcome is Outcome.ESCALATE and "EXP_PER_ACTION_EXCEEDED" in over.reason_codes
    assert over.escalation is not None and over.escalation.queue == "treasury-review"
    anomalous = decide(500, signals={"confidence": 0.95, "anomaly_score": 0.9})
    assert anomalous.outcome is Outcome.OBSERVE and anomalous.observations
    no_mandate = decide(500, mandate=None)
    assert no_mandate.outcome is Outcome.DENY and "AUTH_MANDATE_MISSING" in no_mandate.reason_codes
    low_conf = decide(10, signals={"confidence": 0.2})
    assert low_conf.outcome is Outcome.ESCALATE and low_conf.reason_codes == (
        "EVD_CONFIDENCE_BELOW",
    )


@pytest.mark.req("DSP-05")
def test_no_authority_carries_forward_between_steps() -> None:
    """S22: step 2 is judged alone: same result whether or not step 1 was auto-executed."""
    step1 = decide(500)
    assert step1.outcome is Outcome.AUTO_EXECUTE
    narrowed = MANDATE.model_copy(update={"permitted_actions": ["fx.trade"]})
    after = decide(
        500,
        mandate=narrowed,
        context=Context(
            agent_id="treasury-agent-1", mandate_ref="mandate-1", workflow_id="wf-1", step_index=2
        ),
    )
    alone = decide(500, mandate=narrowed)
    assert after.outcome is Outcome.DENY
    assert (after.outcome, after.reason_codes) == (alone.outcome, alone.reason_codes)


@pytest.mark.req("DSP-07")
@given(
    amount=st.floats(min_value=0, max_value=1e6, allow_nan=False),
    conf=st.floats(min_value=0, max_value=1),
    anomaly=st.floats(min_value=0, max_value=1),
)
@settings(max_examples=60, deadline=None)
def test_engine_is_deterministic(amount: float, conf: float, anomaly: float) -> None:
    """S26: identical inputs always produce identical outcome and reasons."""
    sig = {"confidence": conf, "anomaly_score": anomaly}
    a, b = decide(amount, signals=sig), decide(amount, signals=sig)
    assert (a.outcome, a.reason_codes, a.findings) == (b.outcome, b.reason_codes, b.findings)


@pytest.mark.req("DSP-03")
@given(
    low=st.floats(min_value=0, max_value=1e5, allow_nan=False),
    delta=st.floats(min_value=0, max_value=1e5, allow_nan=False),
    anomaly=st.floats(min_value=0, max_value=1),
)
@settings(max_examples=80, deadline=None)
def test_raising_materiality_never_relaxes_outcome(
    low: float, delta: float, anomaly: float
) -> None:
    """Property: more financial materiality, all else fixed, is never less restrictive."""
    sig = {"confidence": 0.95, "anomaly_score": anomaly}
    a = decide(low, signals=sig).outcome
    b = decide(low + delta, signals=sig).outcome
    assert b.restrictiveness >= a.restrictiveness
