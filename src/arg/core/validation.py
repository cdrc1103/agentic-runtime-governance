"""Envelope completeness and coherence validation (ENV-03, SG-08, T-105).

Pure function: returns reason-coded issues, never raises for invalid envelopes.
Completeness: required fields per action type. Coherence: version, identity claim, trace,
timestamps, mandate reference, gateway observed-call hash.
"""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from arg.core.canonical import canonical_hash
from arg.core.models import Envelope


@dataclass(frozen=True)
class ActionRequirements:
    """Completeness rules for one action type (configuration, not code)."""

    required_parameters: tuple[str, ...] = ()
    trace_required: bool = False
    mandate_required: bool = True


@dataclass(frozen=True)
class ValidationIssue:
    """One reason-coded problem."""

    code: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validation; ``ok`` iff there are no issues."""

    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True when the envelope is complete and coherent."""
        return not self.issues

    @property
    def codes(self) -> list[str]:
        """Reason codes, in check order."""
        return [i.code for i in self.issues]


def validate_envelope(
    envelope: Envelope,
    *,
    supported_versions: Collection[str],
    requirements: Mapping[str, ActionRequirements],
    identity_claim: str,
    mandate_exists: Callable[[str], bool],
) -> ValidationResult:
    """Check completeness and coherence of ``envelope`` (SG-08)."""
    issues: list[ValidationIssue] = []

    def bad(code: str, detail: str) -> None:
        issues.append(ValidationIssue(code, detail))

    if envelope.schema_version not in supported_versions:
        bad("ENV_VERSION_UNSUPPORTED", envelope.schema_version)

    req = requirements.get(envelope.action.type)
    if req is None:
        bad("ENV_ACTION_TYPE_UNKNOWN", envelope.action.type)
        req = ActionRequirements(mandate_required=False)
    for name in req.required_parameters:
        if name not in envelope.action.parameters:
            bad("ENV_PARAMETER_MISSING", name)
    if req.mandate_required and envelope.context.mandate_ref is None:
        bad("ENV_MANDATE_MISSING", "context.mandate_ref")

    if envelope.context.agent_id != identity_claim:
        bad("ENV_IDENTITY_MISMATCH", envelope.context.agent_id)
    steps = envelope.action_trace.steps
    if req.trace_required and not steps:
        bad("ENV_TRACE_EMPTY", envelope.action.type)
    for prev, cur in zip(steps, steps[1:], strict=False):
        if cur.started_at < prev.started_at:
            bad("ENV_TRACE_NOT_MONOTONIC", cur.step_id)
    for step in steps:
        if step.ended_at < step.started_at:
            bad("ENV_TRACE_STEP_INVERTED", step.step_id)
    ref = envelope.context.mandate_ref
    if ref is not None and not mandate_exists(ref):
        bad("ENV_MANDATE_UNRESOLVED", ref)

    prov = envelope.provenance
    if prov.origin == "gateway":
        if prov.observed_call is None:
            bad("ENV_OBSERVED_CALL_MISSING", "provenance.observed_call")
        elif prov.observed_call.params_hash != canonical_hash(envelope.action.parameters):
            bad("ENV_OBSERVED_CALL_MISMATCH", prov.observed_call.target)
    return ValidationResult(tuple(issues))
