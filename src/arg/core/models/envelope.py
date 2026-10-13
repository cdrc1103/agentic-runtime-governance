"""Governance Envelope models (ENV-01, ENV-02, ENV-05; SG-01).

Three classes of information (ENV-02): action, action trace, context metadata. ``provenance``
carries what is needed to authenticate the origin (ENV-04).
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    """Base: unknown fields are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Action(_Strict):
    """The proposed action: type, scope, parameters."""

    type: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    parent_envelope_id: str | None = None


class TraceStep(_Strict):
    """One executed step: tool call, retrieval, check, or model call."""

    step_id: str = Field(min_length=1)
    kind: Literal["tool_call", "retrieval", "check", "model_call"]
    name: str
    input_hash: str | None = None
    output_hash: str | None = None
    started_at: AwareDatetime
    ended_at: AwareDatetime
    otel_span_id: str | None = None


class ActionTrace(_Strict):
    """Steps executed, tool calls, data retrieved, checks performed."""

    steps: list[TraceStep] = Field(default_factory=list)


class Context(_Strict):
    """Context metadata: identity, mandate, system state, constraints, signals."""

    agent_id: str = Field(min_length=1)
    network_context: str | None = None
    mandate_ref: str | None = None
    system_state: dict[str, JsonValue] = Field(default_factory=dict)
    policy_constraints: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    step_index: int = Field(default=0, ge=0)
    # Probabilistic assessments computed outside the core (constitution rule 8).
    signals: dict[str, float | str | bool] = Field(default_factory=dict)


class ObservedCall(_Strict):
    """The call a gateway actually observed (gateway origin)."""

    method: str
    target: str
    params_hash: str


class Provenance(_Strict):
    """Where the envelope came from and how it can be authenticated (ENV-04)."""

    origin: Literal["native", "gateway"]
    adapter_id: str = Field(min_length=1)
    signature: str | None = None
    observed_call: ObservedCall | None = None


class Envelope(_Strict):
    """A proposed agent action packaged for governance before execution (ENV-01)."""

    schema_version: str = SCHEMA_VERSION
    envelope_id: str = Field(min_length=1)
    created_at: AwareDatetime
    action: Action
    action_trace: ActionTrace = Field(default_factory=ActionTrace)
    context: Context
    provenance: Provenance
