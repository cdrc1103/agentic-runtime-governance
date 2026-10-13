"""State-store-backed escalation queue with a file reviewer directory (ESC-01..06, T-603)."""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml

from arg.core.models import (
    Escalation,
    EscalationError,
    EscalationRecord,
    EscalationState,
    Reservation,
    Reviewer,
)
from arg.core.ports import EscalationQueue, StateStore
from arg.core.registry import register
from arg.core.types import JsonObject

_TARGET = {
    "approve": EscalationState.APPROVED,
    "decline": EscalationState.DECLINED,
    "modify": EscalationState.MODIFIED,
}


@register(EscalationQueue, "state")
class StateEscalationQueue(EscalationQueue):
    """Pending reviews live in the state store; reviewers come from ``reviewers.yaml``.

    ``max_open`` caps PENDING items per queue (ESC-06) so reviewers are not flooded (T7).
    """

    def __init__(
        self,
        state_store: StateStore,
        reviewers_path: str | Path | None = None,
        max_open: int | None = 100,
        reviewers: Collection[Reviewer] = (),
    ) -> None:
        """Load reviewers from ``reviewers_path`` (``reviewers:`` list) and/or ``reviewers``."""
        loaded = list(reviewers)
        if reviewers_path is not None:
            data = yaml.safe_load(Path(reviewers_path).read_text()) or {}
            loaded += [Reviewer(**r) for r in data.get("reviewers", [])]
        self.store = state_store
        self.max_open = max_open
        self._reviewers = {r.reviewer_id: r for r in loaded}

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
        """Create a PENDING record with its deadline; None when the queue is full."""
        record = EscalationRecord(
            escalation_id=escalation_id,
            decision_id=decision_id,
            envelope_id=str(envelope.get("envelope_id", "")),
            agent_stream=agent_stream,
            queue=route.queue,
            reviewer_role=route.reviewer_role,
            on_timeout=route.on_timeout,
            timeout_seconds=route.timeout_seconds,
            opened_at=at,
            deadline=at + timedelta(seconds=route.timeout_seconds),
            amount=amount,
            reservations=list(reservations),
            envelope=dict(envelope),  # type: ignore[arg-type]
            identity=dict(identity),  # type: ignore[arg-type]
        )
        return record if self.store.create_escalation(record, self.max_open) else None

    def get(self, escalation_id: str) -> EscalationRecord | None:
        """Return the record."""
        return self.store.get_escalation(escalation_id)

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
        """Check state, deadline, role and authority; then transition atomically."""
        record = self.store.get_escalation(escalation_id)
        if record is None:
            raise EscalationError("ESC_NOT_FOUND", escalation_id)
        if record.state is not EscalationState.PENDING:
            raise EscalationError("ESC_NOT_PENDING", record.state.value)
        if at >= record.deadline:
            raise EscalationError("ESC_EXPIRED", record.deadline.isoformat())
        reviewer = self._reviewers.get(reviewer_id)
        if reviewer is None:
            raise EscalationError("ESC_REVIEWER_UNKNOWN", reviewer_id)
        eligible = (
            reviewer.senior
            if record.escalated_to_senior
            else record.reviewer_role in reviewer.roles
        )
        if not eligible:
            raise EscalationError("ESC_ROLE_MISMATCH", record.reviewer_role)
        values = [v for v in (record.amount, amount) if v is not None]
        if (
            reviewer.authority_limit is not None
            and values
            and max(values) > reviewer.authority_limit
        ):
            raise EscalationError(
                "ESC_AUTHORITY_EXCEEDED", f"{max(values)} > {reviewer.authority_limit}"
            )
        updated = record.model_copy(
            update={
                "state": _TARGET[action],
                "resolved_by": reviewer_id,
                "resolved_at": at,
                "note": note,
                "child_envelope_id": child_envelope_id,
            }
        )
        if not self.store.transition_escalation(escalation_id, EscalationState.PENDING, updated):
            raise EscalationError("ESC_NOT_PENDING", "resolved concurrently")
        return updated

    def sweep(self, at: datetime) -> list[EscalationRecord]:
        """Block overdue items, or hand them once to a senior reviewer (ESC-03)."""
        changed: list[EscalationRecord] = []
        for record in self.store.list_escalations(EscalationState.PENDING):
            if record.deadline > at:
                continue
            if record.on_timeout == "senior" and not record.escalated_to_senior:
                updated = record.model_copy(
                    update={
                        "escalated_to_senior": True,
                        "deadline": at + timedelta(seconds=record.timeout_seconds),
                    }
                )
            else:
                updated = record.model_copy(
                    update={
                        "state": EscalationState.TIMED_OUT,
                        "resolved_at": at,
                        "note": "timeout: blocked",
                    }
                )
            if self.store.transition_escalation(
                record.escalation_id, EscalationState.PENDING, updated
            ):
                changed.append(updated)
        return changed

    def depth(self, queue: str) -> int:
        """PENDING count for ``queue``."""
        return len(self.store.list_escalations(EscalationState.PENDING, queue))
