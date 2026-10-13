"""Gateway adapter extension point."""

from abc import ABC, abstractmethod

from arg.core.types import JsonObject


class GatewayAdapter(ABC):
    """Condition: an outbound call is intercepted, wrapped in an envelope from the observed call.

    Requirements: INT-02, INT-04.
    """

    @abstractmethod
    def build_envelope(self, observed_call: JsonObject) -> JsonObject:
        """Build an envelope from the observed call (authentic by construction)."""

    @abstractmethod
    def enforce(self, decision: JsonObject, observed_call: JsonObject) -> JsonObject:
        """Forward the call if allowed (and token valid in hybrid mode), else a structured error."""
