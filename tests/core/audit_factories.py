"""Audit content builders for tests."""

from datetime import UTC, datetime

from arg.core.models import AuditBasis, AuditContent, IdentityResult
from tests.core.factories import make_envelope

REC = datetime(2026, 1, 5, 9, 0, 1, tzinfo=UTC)


def content(agent: str, outcome: str = "auto_execute", **kw: object) -> AuditContent:
    """Minimal valid audit content for ``agent``."""
    env = make_envelope().model_dump(mode="json")
    base: dict[str, object] = {
        "agent_stream": agent,
        "recorded_at": REC,
        "decided_at_stage": "engine",
        "envelope": env,
        "identity_result": IdentityResult(status="confirmed", agent_id=agent),
        "policy_version": "p" * 64,
        "outcome": outcome,
        "basis": AuditBasis(controlling=["X"]),
        "stage_timings_ms": {"identity": 0.4, "engine": 1.25},
    }
    base.update(kw)
    return AuditContent(**base)  # type: ignore[arg-type]
