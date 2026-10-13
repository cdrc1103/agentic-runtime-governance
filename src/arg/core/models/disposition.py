"""Disposition models: outcomes, risk profile, calibration, result (DSP-02..04)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from arg.core.models.controls import Escalation, ReviewStatus
from arg.core.models.evaluation import Finding


class Outcome(StrEnum):
    """The four dispositions (DSP-02)."""

    DENY = "deny"
    ESCALATE = "escalate"
    OBSERVE = "observe"
    AUTO_EXECUTE = "auto_execute"

    @property
    def restrictiveness(self) -> int:
        """Precedence rank for DSP-06: Deny > Escalate > Observe > Auto-Execute."""
        return {"deny": 3, "escalate": 2, "observe": 1, "auto_execute": 0}[self.value]


class Level(StrEnum):
    """Ordinal level used for materiality, impact, and sensitivity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        """0, 1, 2."""
        return ("low", "medium", "high").index(self.value)


class Reversibility(StrEnum):
    """How easily the action can be undone."""

    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"

    @property
    def rank(self) -> int:
        """0, 1, 2."""
        return ("reversible", "partially_reversible", "irreversible").index(self.value)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MaterialityBand(_Strict):
    """Band ``level`` applies up to and including ``upper`` (None = unbounded)."""

    upper: float | None
    level: Level


class NoveltyRule(_Strict):
    """Anomaly relative to mandate patterns: ``signals[signal] >= threshold``."""

    signal: str
    threshold: float


class ActionCalibration(_Strict):
    """Design-time governance parameters for one action type (DSP-03, DSP-04)."""

    reversibility: Reversibility
    customer_impact: Level
    regulatory_sensitivity: Level
    materiality_parameter: str | None = None
    materiality_bands: list[MaterialityBand] = Field(default_factory=list)
    novelty: NoveltyRule | None = None
    # Risk score (sum of ordinal ranks, +1 for novelty) at which each outcome is indicated.
    observe_at: int = Field(ge=0)
    escalate_at: int = Field(ge=0)
    deny_at: int = Field(ge=0)

    @model_validator(mode="after")
    def _checks(self) -> "ActionCalibration":
        if not self.observe_at <= self.escalate_at <= self.deny_at:
            raise ValueError("require observe_at <= escalate_at <= deny_at")
        if (self.materiality_parameter is None) != (not self.materiality_bands):
            raise ValueError("materiality_parameter and materiality_bands go together")
        uppers = [b.upper for b in self.materiality_bands]
        if self.materiality_bands and uppers[-1] is not None:
            raise ValueError("last materiality band must be unbounded (upper: null)")
        finite = [u for u in uppers[:-1] if u is not None]
        if len(finite) != len(uppers[:-1]) or finite != sorted(finite):
            raise ValueError("materiality bands must be ascending with only the last unbounded")
        return self


class Calibration(_Strict):
    """The calibration file (reviewed before deployment, DSP-04)."""

    review_status: ReviewStatus
    escalation: Escalation
    action_types: dict[str, ActionCalibration]


@dataclass(frozen=True)
class RiskProfile:
    """Risk factors of one action and the outcome they indicate on their own."""

    reversibility: Reversibility | None
    materiality: Level
    customer_impact: Level | None
    regulatory_sensitivity: Level | None
    novelty: bool
    score: int
    indicated_outcome: Outcome
    escalation: Escalation | None = None
    reason_codes: tuple[str, ...] = ()
    materiality_value: float | None = None


@dataclass(frozen=True)
class Observation:
    """Structured observation logged for later review (SG-05)."""

    code: str
    severity: str
    details: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Disposition:
    """Result of evaluating one action (DSP-02); exactly one outcome."""

    outcome: Outcome
    reason_codes: tuple[str, ...]
    findings: tuple[Finding, ...]
    risk_profile: RiskProfile
    observations: tuple[Observation, ...] = ()
    escalation: Escalation | None = None
    # ``reason_codes`` = controlling + contributing. Controlling reasons are those that
    # produced the final outcome; contributing ones fired but a stricter rule decided.
    controlling_codes: tuple[str, ...] = ()
    contributing_codes: tuple[str, ...] = ()

    def rules_applied(self) -> Sequence[Finding]:
        """Findings in evaluation order (audit ``rules_applied``)."""
        return self.findings
