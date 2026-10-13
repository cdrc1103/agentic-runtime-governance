"""State store extension point (SG-04, INT-04, ESC)."""

from abc import ABC, abstractmethod


class StateStore(ABC):
    """Condition: exposure/rate reservations, token consumption, and escalation state are atomic.

    Requirements: SG-04, INT-04, ESC-01..06.
    ``reserve`` becomes a template method (input validation not skippable) in Phase 6.
    """

    @abstractmethod
    def reserve(self, key: str, amount: float, limit: float, window_s: int) -> bool:
        """Atomically add ``amount`` to the window counter if it stays within ``limit``."""

    @abstractmethod
    def release(self, key: str, amount: float, window_s: int) -> None:
        """Undo a reservation (failed execution or failed audit append)."""

    @abstractmethod
    def consume_token(self, jti: str) -> bool:
        """Atomically mark ``jti`` consumed; return False if it already was."""
