"""Disposition engine extension points (DSP)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from arg.core.models import EvaluationContext, Finding, Outcome, RiskProfile


class RiskCalibrator(ABC):
    """Condition: action and signals map to a risk profile from design-time parameters.

    Requirements: DSP-03, DSP-04.
    """

    @abstractmethod
    def calibrate(self, context: EvaluationContext) -> RiskProfile:
        """Return the risk profile, including the outcome it indicates on its own."""


class ResolutionPolicy(ABC):
    """Condition: findings combine into exactly one of Deny, Escalate, Observe, Auto-Execute.

    Requirements: DSP-02, DSP-06.
    """

    @abstractmethod
    def resolve(self, findings: Sequence[Finding], indicated: Outcome) -> Outcome:
        """Return the single outcome."""
