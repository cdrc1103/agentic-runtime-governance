"""Framework-neutral action-trace capture (T-850).

Adapters call ``record`` as the agent works (tool calls, retrievals, checks, model calls);
``drain`` hands the steps to the next envelope. Inputs and outputs are stored only as hashes.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from arg.core.canonical import sha256_hex
from arg.core.models import TraceStep


def hash_value(value: Any) -> str:
    """SHA-256 of a JSON rendering of ``value`` (non-JSON objects via ``str``)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_hex(text.encode())


class TraceRecorder:
    """Collects ``TraceStep``s between envelopes."""

    def __init__(self) -> None:
        """Start empty."""
        self._steps: list[TraceStep] = []

    def record(
        self,
        kind: Literal["tool_call", "retrieval", "check", "model_call"],
        name: str,
        *,
        input: Any = None,  # noqa: A002 - mirrors the envelope field name
        output: Any = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        otel_span_id: str | None = None,
    ) -> TraceStep:
        """Append and return a step; missing times default to now."""
        now = datetime.now(UTC)
        step = TraceStep(
            step_id=f"s{len(self._steps) + 1}",
            kind=kind,
            name=name,
            input_hash=None if input is None else hash_value(input),
            output_hash=None if output is None else hash_value(output),
            started_at=started_at or now,
            ended_at=ended_at or started_at or now,
            otel_span_id=otel_span_id,
        )
        self._steps.append(step)
        return step

    def extend(self, steps: list[TraceStep]) -> None:
        """Add pre-built steps (e.g. from ``otel_genai``), renumbering ids."""
        for s in steps:
            self._steps.append(s.model_copy(update={"step_id": f"s{len(self._steps) + 1}"}))

    def drain(self) -> list[TraceStep]:
        """Return the recorded steps and clear the recorder."""
        steps, self._steps = self._steps, []
        return steps
