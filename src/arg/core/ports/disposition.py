"""Disposition engine extension points (DSP)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from arg.core.types import JsonObject


class RiskCalibrator(ABC):
    """Condition: action and signals map to a risk profile from design-time parameters.

    Requirements: DSP-03, DSP-04.
    """

    @abstractmethod
    def calibrate(self, action: JsonObject, signals: JsonObject) -> JsonObject:
        """Return the risk profile (reversibility, materiality, impact, sensitivity, novelty)."""


class ResolutionPolicy(ABC):
    """Condition: findings combine into exactly one of Deny, Escalate, Observe, Auto-Execute.

    Requirements: DSP-02, DSP-06.
    """

    @abstractmethod
    def resolve(self, findings: Sequence[JsonObject], risk_profile: JsonObject) -> str:
        """Return the single outcome."""
