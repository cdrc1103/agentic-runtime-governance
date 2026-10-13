"""Control and mandate models (CTL-01..05, SG-10)."""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator


class _Strict(BaseModel):
    """Base: unknown fields are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ControlSource(StrEnum):
    """Where a control's authority comes from (CTL-01)."""

    REGULATORY = "regulatory"
    POLICY = "policy"
    PRODUCT = "product"
    MANDATE = "mandate"


class ControlCategory(StrEnum):
    """Independently configurable categories (CTL-05)."""

    AUTHORISATION = "authorisation"
    EXPOSURE = "exposure"
    RATE = "rate"
    EVIDENCE = "evidence"
    CUSTOM = "custom"


class ControlKind(StrEnum):
    """Generic (any actor) or AI-specific (CTL-02)."""

    GENERIC = "generic"
    AI_SPECIFIC = "ai_specific"


class Effect(StrEnum):
    """What a fired control asks for; resolution precedence is DSP-06."""

    DENY = "deny"
    ESCALATE = "escalate"
    OBSERVE = "observe"


class ReviewStatus(StrEnum):
    """Review state; production loads only ``approved`` (CTL-07)."""

    DRAFT = "draft"
    APPROVED = "approved"


class AppliesTo(_Strict):
    """Selection scope; an empty list means "any"."""

    action_types: list[str] = Field(default_factory=list)
    agent_classes: list[str] = Field(default_factory=list)


class Escalation(_Strict):
    """Escalation routing and timeout default (CTL-04, ESC-03)."""

    queue: str
    timeout_seconds: int = Field(gt=0)
    reviewer_role: str
    on_timeout: Literal["block", "senior"] = "block"


class Validity(_Strict):
    """Validity period (CTL-04); bounds are inclusive, open when omitted."""

    not_before: AwareDatetime | None = None
    not_after: AwareDatetime | None = None


class Control(_Strict):
    """One rule of the institution's rulebook (CTL-04)."""

    control_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    source: ControlSource
    category: ControlCategory
    kind: ControlKind = ControlKind.GENERIC
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    # Type-specific; ``logic["type"]`` selects the evaluator (e.g. exposure, rego).
    logic: dict[str, JsonValue]
    effect: Effect
    escalation: Escalation | None = None
    validity: Validity = Field(default_factory=Validity)
    owner: str = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.DRAFT

    @model_validator(mode="after")
    def _checks(self) -> "Control":
        if "type" not in self.logic:
            raise ValueError("logic.type is required")
        if self.effect is Effect.ESCALATE and self.escalation is None:
            raise ValueError("effect 'escalate' requires an escalation block")
        return self


class MandateLimits(_Strict):
    """Limits delegated by the principal; omitted means "none granted"."""

    per_action: float | None = None
    aggregate: float | None = None
    rate: int | None = None


class Mandate(_Strict):
    """Machine-readable delegation of authority from a principal to an agent (CTL-03)."""

    mandate_id: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    permitted_actions: list[str]
    limits: MandateLimits = Field(default_factory=MandateLimits)
    conditions: dict[str, JsonValue] = Field(default_factory=dict)
    not_before: AwareDatetime
    not_after: AwareDatetime
    delegation_chain: list[str] = Field(default_factory=list)
    depth: int = Field(default=0, ge=0)
    revocation_ref: str | None = None
    signature: str | None = None


class MandateRejection(Exception):  # noqa: N818 - domain term
    """Mandate failed validation; ``code`` is an ``MND_*`` reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Store the reason ``code`` and ``detail``."""
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class ControlsLoadError(Exception):
    """A controls bundle could not be loaded (invalid or unapproved content)."""
