"""Map OpenTelemetry GenAI spans to action-trace steps (INT-06, T-850).

Conventions checked 2026-10-14 against the ``open-telemetry/semantic-conventions-genai``
repository (the GenAI conventions moved there from the main semconv site). Status of every
attribute used below: **Development**, so names may change; pin and re-verify before relying
on them. See ``docs/adapters/otel-genai.md``.

Verified names: ``gen_ai.operation.name`` with well-known values ``execute_tool``,
``invoke_agent``, ``create_agent``, ``chat``, ``generate_content``, ``text_completion``,
``embeddings``, ``retrieval``; tool spans carry ``gen_ai.tool.name`` and
``gen_ai.tool.call.id``; agent spans ``gen_ai.agent.name`` / ``gen_ai.agent.id``.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from arg.core.models import TraceStep

OPERATION = "gen_ai.operation.name"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
AGENT_NAME = "gen_ai.agent.name"
REQUEST_MODEL = "gen_ai.request.model"

_KIND: dict[str, Literal["tool_call", "retrieval", "model_call"]] = {
    "execute_tool": "tool_call",
    "retrieval": "retrieval",
    "embeddings": "retrieval",
    "chat": "model_call",
    "generate_content": "model_call",
    "text_completion": "model_call",
}


def step_from_span(
    attributes: Mapping[str, Any],
    *,
    step_id: str,
    started_at: datetime,
    ended_at: datetime,
    span_id: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
) -> TraceStep | None:
    """Return the trace step for a GenAI span, or None for operations that are not steps.

    ``invoke_agent`` and ``create_agent`` describe the agent itself (envelope context), not
    something the agent did, so they map to None.
    """
    operation = attributes.get(OPERATION)
    kind = _KIND.get(str(operation))
    if kind is None:
        return None
    if kind == "tool_call":
        name = str(attributes.get(TOOL_NAME, "unknown_tool"))
    else:
        name = str(attributes.get(REQUEST_MODEL) or operation)
    return TraceStep(
        step_id=step_id,
        kind=kind,
        name=name,
        input_hash=input_hash,
        output_hash=output_hash,
        started_at=started_at,
        ended_at=ended_at,
        otel_span_id=span_id,
    )
