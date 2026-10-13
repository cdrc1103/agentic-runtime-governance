"""Native adapter extension point."""

from abc import ABC, abstractmethod

from arg.core.types import JsonObject


class NativeAdapter(ABC):
    """Condition: the agent emits an envelope before each action and obeys the outcome.

    Requirements: INT-01, INT-06.
    """

    @abstractmethod
    def build_envelope(self, framework_event: JsonObject) -> JsonObject:
        """Build a signed envelope from a framework event."""

    @abstractmethod
    def enforce(self, decision: JsonObject) -> JsonObject:
        """Map a decision to framework behaviour (block, pending result, or proceed)."""
