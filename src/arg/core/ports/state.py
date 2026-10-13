"""State store extension point (SG-04, INT-04, ESC, ENV-06)."""

import math
from abc import ABC, abstractmethod
from datetime import datetime

from arg.core.models import EscalationRecord, EscalationState


class StateStore(ABC):
    """Condition: exposure/rate reservations, token consumption, decisions and escalations
    change atomically.

    ``reserve``/``release`` are template methods: input validation and fixed-window
    arithmetic cannot be skipped; implementations supply ``_add`` and ``_usage``.
    Requirements: SG-04, INT-04, ENV-06, ESC-01..06.
    """

    # ---- counters (fixed windows) ----
    def reserve(
        self, key: str, amount: float, limit: float | None, window_s: int, at: datetime
    ) -> bool:
        """Atomically add ``amount`` to the window counter if the total stays <= ``limit``.

        ``limit=None`` adds unconditionally (reviewer-approved actions). Returns success.
        """
        self._check(key, amount, window_s)
        return self._add(key, self._window(at, window_s), window_s, amount, limit)

    def release(self, key: str, amount: float, window_s: int, at: datetime) -> None:
        """Undo a reservation made in the window containing ``at`` (never below zero)."""
        self._check(key, amount, window_s)
        self._add(key, self._window(at, window_s), window_s, -amount, None)

    def usage(self, key: str, window_s: int, at: datetime) -> float:
        """Current total in the window containing ``at``."""
        self._check(key, 0, window_s)
        return self._usage(key, self._window(at, window_s), window_s)

    @staticmethod
    def _check(key: str, amount: float, window_s: int) -> None:
        if not key:
            raise ValueError("empty counter key")
        if not math.isfinite(amount) or amount < 0:
            raise ValueError(f"amount must be a finite non-negative number, got {amount}")
        if window_s <= 0:
            raise ValueError("window must be positive")

    @staticmethod
    def _window(at: datetime, window_s: int) -> int:
        return int(at.timestamp()) // window_s

    @abstractmethod
    def _add(self, key: str, window: int, window_s: int, delta: float, limit: float | None) -> bool:
        """Atomically apply ``delta``; refuse (False) if it would exceed ``limit``."""

    @abstractmethod
    def _usage(self, key: str, window: int, window_s: int) -> float:
        """Total for the window (0 if none)."""

    # ---- one-time tokens ----
    @abstractmethod
    def consume_token(self, jti: str) -> bool:
        """Atomically mark ``jti`` consumed; return False if it already was."""

    # ---- idempotency (ENV-06) ----
    @abstractmethod
    def put_decision(self, envelope_id: str, payload: str) -> str:
        """Store ``payload`` unless one exists; return the stored payload (first writer wins)."""

    @abstractmethod
    def get_decision(self, envelope_id: str) -> str | None:
        """Return the stored decision payload, if any."""

    # ---- escalations (ESC-01..06) ----
    @abstractmethod
    def create_escalation(self, record: EscalationRecord, cap: int | None) -> bool:
        """Insert unless the queue already holds ``cap`` PENDING records (ESC-06)."""

    @abstractmethod
    def get_escalation(self, escalation_id: str) -> EscalationRecord | None:
        """Return the record, if any."""

    @abstractmethod
    def transition_escalation(
        self, escalation_id: str, expected: EscalationState, record: EscalationRecord
    ) -> bool:
        """Replace the record only if it is still in ``expected`` state (compare-and-set)."""

    @abstractmethod
    def list_escalations(
        self, state: EscalationState, queue: str | None = None
    ) -> list[EscalationRecord]:
        """Records in ``state`` (optionally one queue), ordered by deadline then id."""
