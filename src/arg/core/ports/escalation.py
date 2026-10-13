"""Human escalation extension point (ESC)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from arg.core.models import Escalation, EscalationRecord, Reservation
from arg.core.types import JsonObject


class EscalationQueue(ABC):
    """Condition: escalated actions are held for reviewers with authority, with a timeout default.

    Resolution is refused unless the reviewer is known, holds the required role, and has
    sufficient authority (ESC-04). Requirements: ESC-01..06.
    """

    @abstractmethod
    def open(
        self,
        *,
        escalation_id: str,
        decision_id: str,
        envelope: JsonObject,
        identity: JsonObject,
        agent_stream: str,
        route: Escalation,
        amount: float | None,
        at: datetime,
        reservations: Sequence[Reservation] = (),
    ) -> EscalationRecord | None:
        """Hold the action; None if the queue is at its cap (ESC-06)."""

    @abstractmethod
    def get(self, escalation_id: str) -> EscalationRecord | None:
        """Return the record."""

    @abstractmethod
    def resolve(
        self,
        escalation_id: str,
        reviewer_id: str,
        action: Literal["approve", "decline", "modify"],
        at: datetime,
        *,
        amount: float | None = None,
        note: str = "",
        child_envelope_id: str | None = None,
    ) -> EscalationRecord:
        """Apply a reviewer decision or raise ``EscalationError``."""

    @abstractmethod
    def sweep(self, at: datetime) -> list[EscalationRecord]:
        """Apply timeout defaults to overdue pending items (ESC-03)."""

    @abstractmethod
    def depth(self, queue: str) -> int:
        """Number of PENDING items in ``queue`` (metric)."""
