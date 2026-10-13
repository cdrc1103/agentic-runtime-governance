"""Human escalation extension point (ESC)."""

from abc import ABC, abstractmethod

from arg.core.types import JsonObject


class EscalationQueue(ABC):
    """Condition: escalated actions are held for reviewers with authority, with a timeout default.

    Requirements: ESC-01..06.
    """

    @abstractmethod
    def open(self, decision_id: str, queue: str) -> str:
        """Hold an escalated action; return the ``escalation_id`` (refused beyond the cap)."""

    @abstractmethod
    def reviewer_authority(self, reviewer_id: str) -> JsonObject | None:
        """Return the reviewer's role and authority limit, or None if unknown."""
