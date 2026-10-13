"""Decision token extension point (INT-04)."""

from abc import ABC, abstractmethod

from arg.core.types import JsonObject


class TokenService(ABC):
    """Condition: Auto-Execute/Observe yields a short-lived, one-time token bound to the action.

    Requirements: INT-04.
    """

    @abstractmethod
    def issue(self, claims: JsonObject) -> str:
        """Return a signed token for ``claims``."""

    @abstractmethod
    def verify(self, token: str, act_hash: str, agent_id: str) -> JsonObject:
        """Return the claims or raise if signature, expiry, subject, or action hash fail."""
