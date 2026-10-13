"""Dispatch controls to evaluators by ``logic.type`` (T-305, DSP-01, INT-05)."""

from collections.abc import Mapping, Sequence

from arg.core.models import Control, Effect, EvaluationContext, Finding
from arg.core.ports import ControlEvaluator


def evaluate_controls(
    controls: Sequence[Control],
    evaluators: Mapping[str, ControlEvaluator],
    context: EvaluationContext,
) -> list[Finding]:
    """Evaluate every control; a control that cannot be evaluated fires a Deny (fail closed)."""
    findings: list[Finding] = []
    for control in controls:
        evaluator = evaluators.get(str(control.logic["type"]))
        if evaluator is None:
            findings.append(_deny(control, "CTL_NO_EVALUATOR"))
            continue
        try:
            findings.extend(evaluator.evaluate(control, context))
        except Exception:  # noqa: BLE001 - any evaluator failure must fail closed
            findings.append(_deny(control, "CTL_EVALUATOR_ERROR"))
    return findings


def _deny(control: Control, code: str) -> Finding:
    return Finding(control.control_id, control.version, "fire", Effect.DENY, code)
