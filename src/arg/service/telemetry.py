"""OpenTelemetry implementation of the decision observer (T-604).

Spans: ``arg.decide`` with child ``arg.stage.<name>`` per pipeline stage. Metrics:
``arg.decisions`` (counter by outcome/stage), ``arg.stage.duration`` (histogram, ms),
``arg.escalation.queue_depth`` (gauge), ``arg.escalation.blocked`` (counter, ESC-06).
Mapping the action trace to the OTel GenAI conventions is done in Phase 8.
"""

import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from opentelemetry import metrics, trace
from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import TracerProvider

from arg.core.models import DecisionResponse


class OtelObserver:
    """Emits spans and metrics for decisions, stages, and escalation queues."""

    def __init__(
        self,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
    ) -> None:
        """Use the given providers, or the process-global ones."""
        self._tracer = (tracer_provider or trace.get_tracer_provider()).get_tracer("arg")
        meter = (meter_provider or metrics.get_meter_provider()).get_meter("arg")
        self._decisions = meter.create_counter("arg.decisions")
        self._stage_ms = meter.create_histogram("arg.stage.duration", unit="ms")
        self._depth = meter.create_gauge("arg.escalation.queue_depth")
        self._blocked = meter.create_counter("arg.escalation.blocked")

    def decision(self) -> AbstractContextManager[None]:
        """Parent span for one decision."""
        return self._span("arg.decide")

    def stage(self, name: str) -> AbstractContextManager[None]:
        """Child span and duration histogram for one stage."""
        return self._timed(name)

    @contextmanager
    def _span(self, name: str) -> Iterator[None]:
        with self._tracer.start_as_current_span(name):
            yield

    @contextmanager
    def _timed(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            with self._tracer.start_as_current_span(f"arg.stage.{name}"):
                yield
        finally:
            self._stage_ms.record((time.perf_counter() - start) * 1000, {"stage": name})

    def decided(self, response: DecisionResponse) -> None:
        """Count the decision by outcome and deciding stage."""
        self._decisions.add(
            1, {"outcome": response.outcome, "decided_at_stage": response.decided_at_stage}
        )

    def queue_depth(self, queue: str, depth: int) -> None:
        """Record the queue's pending count."""
        self._depth.set(depth, {"queue": queue})

    def escalation_blocked(self, queue: str) -> None:
        """Count a refused escalation."""
        self._blocked.add(1, {"queue": queue})
