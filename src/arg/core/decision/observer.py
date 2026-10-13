"""Observability hook for the decision service, free of any telemetry dependency.

``arg.service.telemetry`` provides the OpenTelemetry implementation.
"""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from arg.core.models import DecisionResponse


class DecisionObserver(Protocol):
    """Receives spans and metric events from ``DecisionService``."""

    def decision(self) -> AbstractContextManager[None]:
        """Context wrapping one ``decide`` call."""
        ...

    def stage(self, name: str) -> AbstractContextManager[None]:
        """Context wrapping one pipeline stage."""
        ...

    def decided(self, response: DecisionResponse) -> None:
        """A decision was produced."""
        ...

    def queue_depth(self, queue: str, depth: int) -> None:
        """Current PENDING count of an escalation queue."""
        ...

    def escalation_blocked(self, queue: str) -> None:
        """A new escalation was refused because the queue is at its cap (ESC-06)."""
        ...


class NullObserver:
    """Does nothing."""

    def decision(self) -> AbstractContextManager[None]:
        """No-op context."""
        return nullcontext()

    def stage(self, name: str) -> AbstractContextManager[None]:  # noqa: ARG002
        """No-op context."""
        return nullcontext()

    def decided(self, response: DecisionResponse) -> None:
        """Ignore."""

    def queue_depth(self, queue: str, depth: int) -> None:
        """Ignore."""

    def escalation_blocked(self, queue: str) -> None:
        """Ignore."""
