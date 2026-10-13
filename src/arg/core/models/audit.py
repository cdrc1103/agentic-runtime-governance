"""Audit log models (AUD-01..06, contracts.md)."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

GENESIS_HASH = "0" * 64


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IdentityResult(_Strict):
    """Outcome of the identity stage (IDN-05)."""

    status: Literal["confirmed", "rejected"]
    code: str | None = None
    detail: str | None = None
    agent_id: str | None = None
    agent_class: str | None = None
    principal: str | None = None
    registry_id: str | None = None
    origin: str | None = None
    network_context: str | None = None


class RuleApplication(_Strict):
    """One control evaluation (AUD-03: the specific rules applied)."""

    control_id: str
    version: int
    result: Literal["pass", "fire"]
    effect: str | None = None
    reason_code: str = ""
    inputs: dict[str, JsonValue] = Field(default_factory=dict)


class AuditBasis(_Strict):
    """Why the outcome is what it is (AUD-03). Controlling reasons decided it."""

    controlling: list[str] = Field(default_factory=list)
    contributing: list[str] = Field(default_factory=list)


class AuditObservation(_Strict):
    """Structured observation (SG-05)."""

    code: str
    severity: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AuditContent(_Strict):
    """Everything about a decision; the store adds sequence and chain fields."""

    agent_stream: str = Field(min_length=1)
    recorded_at: AwareDatetime
    # Stage that produced the outcome; identity/mandate/validation rejections are decisions too.
    decided_at_stage: Literal["validation", "identity", "mandate", "engine", "reviewer"]
    # The envelope exactly as submitted (raw JSON, so even malformed input is recorded).
    envelope: dict[str, JsonValue]
    identity_result: IdentityResult
    mandate_snapshot: dict[str, JsonValue] | None = None
    policy_version: str | None = None
    # [DESIGN] counter snapshot the engine saw; lets a reviewer re-run the decision (AUD-04).
    state_snapshot: dict[str, float] = Field(default_factory=dict)
    rules_applied: list[RuleApplication] = Field(default_factory=list)
    outcome: Literal["deny", "escalate", "observe", "auto_execute"]
    basis: AuditBasis = Field(default_factory=AuditBasis)
    observations: list[AuditObservation] = Field(default_factory=list)
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    token_jti: str | None = None
    escalation_id: str | None = None
    reviewer_decision: dict[str, JsonValue] | None = None


class AuditEntry(AuditContent):
    """A persisted entry in an agent's hash chain (AUD-02, AUD-06)."""

    entry_id: str
    seq: int = Field(ge=1)
    prev_hash: str
    entry_hash: str


class Anchor(_Strict):
    """Chain head exported outside the store (AUD-06)."""

    agent_stream: str
    seq: int = Field(ge=1)
    entry_hash: str


class AuditConflict(Exception):  # noqa: N818 - domain term
    """The stream head moved (or the sequence slot is taken); retry with the new head."""


class VerifyResult(_Strict):
    """Chain verification outcome; ``ok`` iff nothing is wrong."""

    ok: bool
    checked: int
    code: str | None = None
    seq: int | None = None
