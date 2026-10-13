"""Config-driven risk calibration (DSP-03, DSP-04, T-402).

Risk score = reversibility rank + materiality rank + customer impact rank + regulatory
sensitivity rank (each 0..2) + 1 if the action is novel. The calibration file sets, per
action type, the scores at which Observe, Escalate, and Deny are indicated. Raising any
factor never lowers the score, so the indicated outcome is monotone in risk.
"""

from pathlib import Path

import yaml

from arg.core.models import (
    ActionCalibration,
    Calibration,
    ControlsLoadError,
    EvaluationContext,
    Level,
    Outcome,
    ReviewStatus,
    RiskProfile,
)
from arg.core.ports import RiskCalibrator
from arg.core.registry import register


@register(RiskCalibrator, "config")
class ConfigRiskCalibrator(RiskCalibrator):
    """Maps action and signals to a risk profile using the reviewed calibration file."""

    def __init__(
        self,
        path: str | Path | None = None,
        production: bool = True,
        calibration: Calibration | None = None,
    ) -> None:
        """Load ``path`` (or take ``calibration``); production refuses unapproved files."""
        if calibration is None:
            if path is None:
                raise ValueError("give path or calibration")
            calibration = Calibration(**yaml.safe_load(Path(path).read_text()))
        if production and calibration.review_status is not ReviewStatus.APPROVED:
            raise ControlsLoadError("production mode refuses an unapproved calibration file")
        self.calibration = calibration

    def calibrate(self, context: EvaluationContext) -> RiskProfile:
        """Return the risk profile; an uncalibrated action type is indicated Deny."""
        action = context.envelope.action
        cal = self.calibration.action_types.get(action.type)
        if cal is None:
            return RiskProfile(
                None,
                Level.HIGH,
                None,
                None,
                False,
                0,
                Outcome.DENY,
                reason_codes=("RISK_UNCALIBRATED_ACTION",),
            )
        codes: list[str] = []
        materiality = Level.LOW
        if cal.materiality_parameter is not None:
            materiality = self._materiality(cal, context, codes)
        novel = False
        if cal.novelty is not None:
            value = context.signals.get(cal.novelty.signal)
            novel = (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and value >= cal.novelty.threshold
            )
        score = (
            cal.reversibility.rank
            + materiality.rank
            + cal.customer_impact.rank
            + cal.regulatory_sensitivity.rank
            + int(novel)
        )
        if score >= cal.deny_at:
            indicated, codes = Outcome.DENY, [*codes, "RISK_DENY_THRESHOLD"]
        elif score >= cal.escalate_at:
            indicated, codes = Outcome.ESCALATE, [*codes, "RISK_ESCALATE_THRESHOLD"]
        elif score >= cal.observe_at:
            indicated, codes = Outcome.OBSERVE, [*codes, "RISK_OBSERVE_THRESHOLD"]
        else:
            indicated = Outcome.AUTO_EXECUTE
        return RiskProfile(
            cal.reversibility,
            materiality,
            cal.customer_impact,
            cal.regulatory_sensitivity,
            novel,
            score,
            indicated,
            self.calibration.escalation,
            tuple(codes),
            self._amount(cal, context),
        )

    @staticmethod
    def _amount(cal: ActionCalibration, context: EvaluationContext) -> float | None:
        value = context.envelope.action.parameters.get(cal.materiality_parameter or "")
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    @staticmethod
    def _materiality(cal: ActionCalibration, context: EvaluationContext, codes: list[str]) -> Level:
        value = context.envelope.action.parameters.get(cal.materiality_parameter or "")
        if isinstance(value, bool) or not isinstance(value, int | float):
            codes.append("RISK_MATERIALITY_UNREADABLE")
            return Level.HIGH  # fail closed: unreadable amount is treated as most material
        for band in cal.materiality_bands:
            if band.upper is None or value <= band.upper:
                return band.level
        return Level.HIGH  # pragma: no cover - last band is unbounded by validation
