"""Build audit content from decision parts (AUD-01, AUD-03, AUD-04).

Every outcome yields content, including rejections before the engine runs.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from arg.core.models import (
    AuditBasis,
    AuditContent,
    AuditObservation,
    Disposition,
    Envelope,
    EscalationRecord,
    IdentityBinding,
    IdentityResult,
    Mandate,
    RuleApplication,
)

Stage = str  # "validation" | "identity" | "mandate" | "engine" | "reviewer"


def _raw(envelope: Envelope | Mapping[str, Any]) -> dict[str, Any]:
    return envelope.model_dump(mode="json") if isinstance(envelope, Envelope) else dict(envelope)


def _stream(raw: Mapping[str, Any]) -> str:
    agent = (
        (raw.get("context") or {}).get("agent_id") if isinstance(raw.get("context"), dict) else None
    )
    return agent if isinstance(agent, str) and agent else "_unattributed"


def confirmed(binding: IdentityBinding) -> IdentityResult:
    """Identity result for a confirmed binding."""
    return IdentityResult(status="confirmed", **binding.model_dump())


def content_from_disposition(
    envelope: Envelope,
    identity: IdentityBinding,
    disposition: Disposition,
    *,
    recorded_at: datetime,
    policy_version: str,
    mandate: Mandate | None = None,
    state_snapshot: Mapping[str, float] | None = None,
    stage_timings_ms: Mapping[str, float] | None = None,
    token_jti: str | None = None,
    escalation_id: str | None = None,
) -> AuditContent:
    """Audit content for a decision made by the disposition engine."""
    raw = _raw(envelope)
    return AuditContent(
        agent_stream=_stream(raw),
        recorded_at=recorded_at,
        decided_at_stage="engine",
        envelope=raw,
        identity_result=confirmed(identity),
        mandate_snapshot=mandate.model_dump(mode="json") if mandate else None,
        policy_version=policy_version,
        state_snapshot=dict(state_snapshot or {}),
        rules_applied=[
            RuleApplication(
                control_id=f.control_id,
                version=f.version,
                result=f.result,
                effect=f.effect.value if f.effect else None,
                reason_code=f.reason_code,
                inputs=dict(f.inputs),
            )
            for f in disposition.findings
        ],
        outcome=disposition.outcome.value,
        basis=AuditBasis(
            controlling=list(disposition.controlling_codes),
            contributing=list(disposition.contributing_codes),
        ),
        observations=[
            AuditObservation(code=o.code, severity=o.severity, details=dict(o.details))
            for o in disposition.observations
        ],
        stage_timings_ms=dict(stage_timings_ms or {}),
        token_jti=token_jti,
        escalation_id=escalation_id,
    )


def content_from_rejection(
    envelope: Envelope | Mapping[str, Any],
    stage: Stage,
    code: str,
    detail: str = "",
    *,
    recorded_at: datetime,
    policy_version: str | None = None,
    identity: IdentityBinding | None = None,
    stage_timings_ms: Mapping[str, float] | None = None,
) -> AuditContent:
    """Audit content for a rejection before the engine (validation, identity, mandate)."""
    raw = _raw(envelope)
    identity_result = (
        confirmed(identity)
        if identity is not None
        else IdentityResult(
            status="rejected",
            code=code if stage == "identity" else None,
            detail=detail if stage == "identity" else None,
        )
    )
    return AuditContent(
        agent_stream=_stream(raw),
        recorded_at=recorded_at,
        decided_at_stage=stage,  # type: ignore[arg-type]
        envelope=raw,
        identity_result=identity_result,
        policy_version=policy_version,
        outcome="deny",
        basis=AuditBasis(controlling=[code]),
        stage_timings_ms=dict(stage_timings_ms or {}),
    )


def content_for_reviewer(
    record: EscalationRecord,
    outcome: str,
    code: str,
    decision: Mapping[str, Any],
    *,
    recorded_at: datetime,
    policy_version: str | None = None,
) -> AuditContent:
    """Audit content for a reviewer action, refusal, or timeout (ESC-04, ESC-05)."""
    ident = {k: v for k, v in record.identity.items() if k not in {"status", "code", "detail"}}
    return AuditContent(
        agent_stream=record.agent_stream,
        recorded_at=recorded_at,
        decided_at_stage="reviewer",
        envelope=record.envelope,
        identity_result=IdentityResult.model_validate({"status": "confirmed", **ident}),
        policy_version=policy_version,
        outcome=outcome,  # type: ignore[arg-type]
        basis=AuditBasis(controlling=[code]),
        escalation_id=record.escalation_id,
        reviewer_decision=dict(decision),
    )
