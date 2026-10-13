"""Built-in deterministic control evaluators (CTL-02, CTL-05, DSP-01, T-401).

Each evaluator is a pure function of ``(control, context)``. A fired finding carries the
control's ``effect``. Unparseable ``logic`` raises, and dispatch turns that into a Deny.
Control validity periods are applied at retrieval; the mandate window is re-checked here.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arg.core.engine.keys import counter_key
from arg.core.models import Control, EvaluationContext, Finding
from arg.core.ports import ControlEvaluator
from arg.core.registry import register


class _Logic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


def _fire(control: Control, code: str, **inputs: float | str | int) -> Finding:
    return Finding(control.control_id, control.version, "fire", control.effect, code, inputs)


def _pass(control: Control, **inputs: float | str | int) -> Finding:
    return Finding(control.control_id, control.version, "pass", None, "", inputs)


class _AuthorisationLogic(_Logic):
    permitted_action_types: list[str] = Field(default_factory=list)
    require_mandate: bool = True
    require_principal_match: bool = True
    max_delegation_depth: int | None = None


@register(ControlEvaluator, "authorisation")
class AuthorisationEvaluator(ControlEvaluator):
    """Who may act for whom, to what depth, for which action types (CTL-05, CTL-03)."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Fire on the first violated authorisation condition."""
        logic = _AuthorisationLogic(**control.logic)  # type: ignore[arg-type]
        action_type = context.envelope.action.type
        if logic.permitted_action_types and action_type not in logic.permitted_action_types:
            return [_fire(control, "AUTH_ACTION_TYPE_NOT_PERMITTED", action_type=action_type)]
        m = context.mandate
        if m is None:
            if logic.require_mandate:
                return [_fire(control, "AUTH_MANDATE_MISSING")]
            return [_pass(control, action_type=action_type)]
        if action_type not in m.permitted_actions:
            return [_fire(control, "AUTH_ACTION_NOT_IN_MANDATE", action_type=action_type)]
        if not m.not_before <= context.at <= m.not_after:
            return [_fire(control, "AUTH_MANDATE_OUTSIDE_VALIDITY", mandate_id=m.mandate_id)]
        if m.agent_id != context.identity.agent_id:
            return [_fire(control, "AUTH_MANDATE_AGENT_MISMATCH", mandate_id=m.mandate_id)]
        if logic.require_principal_match and m.principal != context.identity.principal:
            return [_fire(control, "AUTH_PRINCIPAL_MISMATCH", principal=m.principal)]
        if logic.max_delegation_depth is not None and m.depth > logic.max_delegation_depth:
            return [_fire(control, "AUTH_DELEGATION_DEPTH_EXCEEDED", depth=m.depth)]
        return [_pass(control, action_type=action_type)]


class _ExposureLogic(_Logic):
    scope: str = Field(pattern="^(per_action|aggregate)$")
    amount_parameter: str
    limit: float
    key_by: str = "agent"
    window_seconds: int | None = None
    apply_mandate_limit: bool = False

    @model_validator(mode="after")
    def _aggregate_needs_window(self) -> "_ExposureLogic":
        if self.scope == "aggregate" and not self.window_seconds:
            raise ValueError("aggregate exposure needs window_seconds")
        return self


def amount_of(context: EvaluationContext, parameter: str) -> float | None:
    """Return the numeric action parameter, or None if absent or not a number."""
    value = context.envelope.action.parameters.get(parameter)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def effective_limit(logic: _ExposureLogic, context: EvaluationContext) -> float:
    """Control limit, narrowed by the mandate's grant when ``apply_mandate_limit`` is set."""
    limit = logic.limit
    mandate = context.mandate
    if logic.apply_mandate_limit and mandate is not None:
        granted = (
            mandate.limits.per_action if logic.scope == "per_action" else mandate.limits.aggregate
        )
        if granted is not None:
            limit = min(limit, granted)
    return limit


@register(ControlEvaluator, "exposure")
class ExposureEvaluator(ControlEvaluator):
    """Per-action and aggregate exposure limits (CTL-05, SG-04)."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Fire when the amount (or snapshot total plus amount) exceeds the limit."""
        logic = _ExposureLogic(**control.logic)  # type: ignore[arg-type]
        amount = amount_of(context, logic.amount_parameter)
        if amount is None:
            return [_fire(control, "EXP_AMOUNT_UNREADABLE", parameter=logic.amount_parameter)]
        limit = effective_limit(logic, context)
        if logic.scope == "per_action":
            if amount > limit:
                return [_fire(control, "EXP_PER_ACTION_EXCEEDED", amount=amount, limit=limit)]
            return [_pass(control, amount=amount, limit=limit)]
        used = context.state.get(counter_key(control, context), 0.0)
        if used + amount > limit:
            return [_fire(control, "EXP_AGGREGATE_EXCEEDED", used=used, amount=amount, limit=limit)]
        return [_pass(control, used=used, amount=amount, limit=limit)]


class _RateLogic(_Logic):
    max_actions: int = Field(ge=0)
    window_seconds: int = Field(gt=0)
    key_by: str = "agent"


@register(ControlEvaluator, "rate")
class RateEvaluator(ControlEvaluator):
    """Maximum action count per time window (CTL-05)."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Fire when this action would exceed ``max_actions`` in the window."""
        logic = _RateLogic(**control.logic)  # type: ignore[arg-type]
        count = context.state.get(counter_key(control, context), 0.0)
        if count + 1 > logic.max_actions:
            return [_fire(control, "RATE_EXCEEDED", count=count, max_actions=logic.max_actions)]
        return [_pass(control, count=count, max_actions=logic.max_actions)]


class _EvidenceLogic(_Logic):
    min_confidence: float = Field(ge=0, le=1)
    signal: str = "confidence"
    required_evidence: list[str] = Field(default_factory=list)


@register(ControlEvaluator, "evidence")
class EvidenceEvaluator(ControlEvaluator):
    """Minimum confidence and required evidence, regardless of value (CTL-05, CTL-02)."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Fire on missing/low confidence signal or missing required trace steps."""
        logic = _EvidenceLogic(**control.logic)  # type: ignore[arg-type]
        value = context.signals.get(logic.signal)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return [_fire(control, "EVD_SIGNAL_MISSING", signal=logic.signal)]
        if value < logic.min_confidence:
            return [
                _fire(control, "EVD_CONFIDENCE_BELOW", value=value, minimum=logic.min_confidence)
            ]
        names = {s.name for s in context.envelope.action_trace.steps}
        missing = [r for r in logic.required_evidence if r not in names]
        if missing:
            return [_fire(control, "EVD_REQUIRED_MISSING", missing=",".join(missing))]
        return [_pass(control, value=value)]
