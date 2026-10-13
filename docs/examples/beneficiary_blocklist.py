"""Worked example 1 (docs/extending.md): a custom ``ControlEvaluator``.

A sanctions-style rule: fire when the payment's beneficiary is on a blocklist carried in the
control's own ``logic``. It is deterministic and pure, which is all the engine asks of an
evaluator (DSP-01, DSP-07). Registering it under a name makes ``logic: {type: blocklist}``
work in any controls bundle once this module is imported.
"""

from collections.abc import Sequence

from arg.core.models import Control, EvaluationContext, Finding
from arg.core.ports import ControlEvaluator
from arg.core.registry import register


@register(ControlEvaluator, "blocklist")
class BeneficiaryBlocklistEvaluator(ControlEvaluator):
    """Fire the control's effect when ``parameters.beneficiary`` is in ``logic.blocked``."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Return one finding; unreadable beneficiary fires too (fail closed)."""
        blocked = control.logic.get("blocked", [])
        beneficiary = context.envelope.action.parameters.get("beneficiary")
        if not isinstance(blocked, list) or not isinstance(beneficiary, str):
            return [
                Finding(
                    control.control_id,
                    control.version,
                    "fire",
                    control.effect,
                    "BLK_BENEFICIARY_UNREADABLE",
                )
            ]
        if beneficiary in blocked:
            return [
                Finding(
                    control.control_id,
                    control.version,
                    "fire",
                    control.effect,
                    "BLK_BENEFICIARY_BLOCKED",
                    {"beneficiary": beneficiary},
                )
            ]
        return [Finding(control.control_id, control.version, "pass")]
