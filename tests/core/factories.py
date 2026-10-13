"""Fictional envelope builders for tests (Example Bank)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from arg.core.models import (
    Action,
    ActionTrace,
    Context,
    Envelope,
    Provenance,
    TraceStep,
)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def step(i: int, offset_s: int = 0) -> TraceStep:
    """A tool-call step starting ``offset_s`` after T0."""
    start = T0 + timedelta(seconds=offset_s)
    return TraceStep(
        step_id=f"s{i}",
        kind="tool_call",
        name="lookup_balance",
        started_at=start,
        ended_at=start + timedelta(seconds=1),
    )


def make_envelope(**overrides: Any) -> Envelope:
    """A valid native payment envelope; keyword overrides replace top-level fields."""
    base: dict[str, Any] = {
        "envelope_id": "env-001",
        "created_at": T0,
        "action": Action(
            type="payment.initiate",
            scope="account:ACME-001",
            parameters={"amount": 1250.5, "currency": "USD", "beneficiary": "vendor-17"},
        ),
        "action_trace": ActionTrace(steps=[step(1), step(2, 5)]),
        "context": Context(
            agent_id="treasury-agent-1", mandate_ref="mandate-1", signals={"confidence": 0.93}
        ),
        "provenance": Provenance(origin="native", adapter_id="adapter-1"),
    }
    base.update(overrides)
    return Envelope(**base)
