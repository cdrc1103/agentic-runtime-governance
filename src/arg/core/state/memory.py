"""In-memory state store (tests, demo)."""

import threading

from arg.core.models import EscalationRecord, EscalationState
from arg.core.ports import StateStore
from arg.core.registry import register


@register(StateStore, "memory")
class InMemoryStateStore(StateStore):
    """Dicts guarded by one lock; every operation is atomic."""

    def __init__(self) -> None:
        """Create an empty store."""
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, int, int], float] = {}
        self._tokens: set[str] = set()
        self._decisions: dict[str, str] = {}
        self._escalations: dict[str, EscalationRecord] = {}

    def _add(self, key: str, window: int, window_s: int, delta: float, limit: float | None) -> bool:
        with self._lock:
            k = (key, window_s, window)
            new = self._counters.get(k, 0.0) + delta
            if limit is not None and delta > 0 and new > limit:
                return False
            self._counters[k] = max(new, 0.0)
            return True

    def _usage(self, key: str, window: int, window_s: int) -> float:
        with self._lock:
            return self._counters.get((key, window_s, window), 0.0)

    def consume_token(self, jti: str) -> bool:
        """Atomic test-and-set."""
        with self._lock:
            if jti in self._tokens:
                return False
            self._tokens.add(jti)
            return True

    def put_decision(self, envelope_id: str, payload: str) -> str:
        """First writer wins."""
        with self._lock:
            return self._decisions.setdefault(envelope_id, payload)

    def get_decision(self, envelope_id: str) -> str | None:
        """Return stored payload."""
        with self._lock:
            return self._decisions.get(envelope_id)

    def create_escalation(self, record: EscalationRecord, cap: int | None) -> bool:
        """Insert unless the queue is at capacity."""
        with self._lock:
            if record.escalation_id in self._escalations:
                return False
            pending = sum(
                1
                for r in self._escalations.values()
                if r.queue == record.queue and r.state is EscalationState.PENDING
            )
            if cap is not None and pending >= cap:
                return False
            self._escalations[record.escalation_id] = record
            return True

    def get_escalation(self, escalation_id: str) -> EscalationRecord | None:
        """Return the record."""
        with self._lock:
            return self._escalations.get(escalation_id)

    def transition_escalation(
        self, escalation_id: str, expected: EscalationState, record: EscalationRecord
    ) -> bool:
        """Compare-and-set on state."""
        with self._lock:
            cur = self._escalations.get(escalation_id)
            if cur is None or cur.state is not expected:
                return False
            self._escalations[escalation_id] = record
            return True

    def list_escalations(
        self, state: EscalationState, queue: str | None = None
    ) -> list[EscalationRecord]:
        """Records in ``state``, ordered by deadline then id."""
        with self._lock:
            rs = [
                r
                for r in self._escalations.values()
                if r.state is state and (queue is None or r.queue == queue)
            ]
        return sorted(rs, key=lambda r: (r.deadline, r.escalation_id))
