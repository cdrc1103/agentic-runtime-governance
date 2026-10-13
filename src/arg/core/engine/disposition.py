"""The disposition engine: a deterministic function from inputs to one outcome (DSP-01, DSP-07).

Probabilistic assessments arrive only as ``signals`` (constitution 8). Each call evaluates
one action independently; nothing from an earlier action is consulted (DSP-05).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from arg.core.controls.dispatch import evaluate_controls
from arg.core.models import (
    Control,
    Disposition,
    Effect,
    Envelope,
    EvaluationContext,
    IdentityBinding,
    Mandate,
    Observation,
    Outcome,
)
from arg.core.ports import ControlEvaluator, ResolutionPolicy, RiskCalibrator

_SEVERITY = {Effect.DENY: "high", Effect.ESCALATE: "medium", Effect.OBSERVE: "low"}


class DispositionEngine:
    """Wires evaluators, calibrator, and resolution policy; holds no mutable state."""

    def __init__(
        self,
        evaluators: Mapping[str, ControlEvaluator],
        calibrator: RiskCalibrator,
        policy: ResolutionPolicy,
    ) -> None:
        """Inject components (built by the composition root)."""
        self.evaluators = evaluators
        self.calibrator = calibrator
        self.policy = policy

    def evaluate(
        self,
        envelope: Envelope,
        identity: IdentityBinding,
        controls: Sequence[Control],
        state_snapshot: Mapping[str, float],
        signals: Mapping[str, float | str | bool],
        *,
        at: datetime,
        mandate: Mandate | None = None,
    ) -> Disposition:
        """Return the disposition of ``envelope``; identical inputs give identical results."""
        ctx = EvaluationContext(envelope, identity, at, mandate, state_snapshot, signals)
        findings = evaluate_controls(controls, self.evaluators, ctx)
        profile = self.calibrator.calibrate(ctx)
        outcome = self.policy.resolve(findings, profile.indicated_outcome)

        by_id = {c.control_id: c for c in controls}
        fired = [f for f in findings if f.result == "fire"]
        outcome_of = {
            Effect.DENY: Outcome.DENY,
            Effect.ESCALATE: Outcome.ESCALATE,
            Effect.OBSERVE: Outcome.OBSERVE,
        }
        controlling = [f.reason_code for f in fired if f.effect and outcome_of[f.effect] is outcome]
        contributing = [
            f.reason_code for f in fired if f.effect and outcome_of[f.effect] is not outcome
        ]
        if profile.indicated_outcome is outcome and outcome is not Outcome.AUTO_EXECUTE:
            controlling += list(profile.reason_codes)
        else:
            contributing += list(profile.reason_codes)
        reasons = controlling + contributing
        escalation = None
        if outcome is Outcome.ESCALATE:
            routed = next(
                (
                    by_id[f.control_id].escalation
                    for f in fired
                    if f.effect is Effect.ESCALATE and f.control_id in by_id
                ),
                None,
            )
            escalation = routed or profile.escalation
        observations = tuple(
            Observation(f.reason_code, _SEVERITY[f.effect], {"control_id": f.control_id})
            for f in fired
            if f.effect is Effect.OBSERVE
        )
        if outcome is Outcome.OBSERVE and not observations:
            observations = (Observation("RISK_OBSERVE", "low", {"score": profile.score}),)
        return Disposition(
            outcome,
            tuple(dict.fromkeys(reasons)),
            tuple(findings),
            profile,
            observations,
            escalation,
            tuple(dict.fromkeys(controlling)),
            tuple(c for c in dict.fromkeys(contributing) if c not in controlling),
        )
