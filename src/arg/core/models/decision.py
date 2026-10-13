"""Decision response, reservation, and escalation models (SG-04, SG-07, ESC)."""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from arg.core.models.audit import AuditObservation, RuleApplication


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reservation(_Strict):
    """An exposure or rate counter increment held for an action (SG-04)."""

    key: str
    amount: float = Field(ge=0)
    limit: float | None = None  # None: unconditional (reviewer-approved)
    window_seconds: int = Field(gt=0)


class DecisionResponse(_Strict):
    """What the caller gets back (SG-07)."""

    decision_id: str | None
    outcome: Literal["deny", "escalate", "observe", "auto_execute"]
    reason_codes: list[str] = Field(default_factory=list)
    rules_applied: list[RuleApplication] = Field(default_factory=list)
    policy_version: str | None = None
    observations: list[AuditObservation] = Field(default_factory=list)
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    decided_at_stage: str = "engine"
    token: str | None = None
    escalation_id: str | None = None


class EscalationState(StrEnum):
    """Lifecycle of a held action (ESC-01..04)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    MODIFIED = "MODIFIED"
    DECLINED = "DECLINED"
    TIMED_OUT = "TIMED_OUT"


class EscalationRecord(_Strict):
    """An escalated action held for human review."""

    escalation_id: str
    decision_id: str
    envelope_id: str
    agent_stream: str
    queue: str
    reviewer_role: str
    on_timeout: Literal["block", "senior"]
    timeout_seconds: int
    state: EscalationState = EscalationState.PENDING
    opened_at: AwareDatetime
    deadline: AwareDatetime
    escalated_to_senior: bool = False
    amount: float | None = None
    envelope: dict[str, JsonValue]
    identity: dict[str, JsonValue]
    reservations: list[Reservation] = Field(default_factory=list)
    resolved_by: str | None = None
    resolved_at: AwareDatetime | None = None
    note: str = ""
    child_envelope_id: str | None = None


class Reviewer(_Strict):
    """A human reviewer's identity and authority (ESC-04)."""

    reviewer_id: str
    roles: list[str]
    authority_limit: float | None = None  # None: unlimited
    senior: bool = False


class StageRejection(Exception):  # noqa: N818 - domain term
    """A pipeline stage rejects the action; ``stage`` is the audit ``decided_at_stage``."""

    def __init__(self, stage: str, code: str, detail: str = "") -> None:
        """Store stage, reason code and detail."""
        super().__init__(f"{stage}: {code}: {detail}" if detail else f"{stage}: {code}")
        self.stage = stage
        self.code = code
        self.detail = detail


class EscalationError(Exception):
    """A reviewer action was refused; ``code`` is an ``ESC_*`` reason code (ESC-04)."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Store reason code and detail."""
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
