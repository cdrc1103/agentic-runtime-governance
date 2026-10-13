"""Decision pipeline extension point (Action Lifecycle, DSP-05)."""

from abc import ABC, abstractmethod
from typing import Any


class PipelineStage(ABC):
    """Condition: one step of the action lifecycle (validate, identity, retrieve, ...).

    Each action is evaluated independently; no stage carries authority between actions.
    Requirements: DSP-05, INT-05 (a failing stage fails closed).
    """

    @abstractmethod
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return the updated pipeline state; raise to fail closed."""
