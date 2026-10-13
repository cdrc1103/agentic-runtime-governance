"""Decision API (FastAPI): thin HTTP layer over ``DecisionService`` (T-604, T-606).

All decision logic lives in the core; this module authenticates callers, maps roles, and
translates results. The internal reviewer re-entry parameter of the service is not reachable
from here.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from arg.core.audit.anchor import verify_with_sink
from arg.core.models import (
    Anchor,
    DecisionResponse,
    EscalationError,
    EscalationRecord,
    VerifyResult,
)
from arg.core.ports import AnchorSink, AuditStore
from arg.runtime import GovernanceRuntime
from arg.service.auth import Authenticator

_HTTP_STATUS = {
    "ESC_NOT_FOUND": 404,
    "ESC_NOT_PENDING": 409,
    "ESC_EXPIRED": 409,
    "ESC_REVIEWER_UNKNOWN": 403,
    "ESC_ROLE_MISMATCH": 403,
    "ESC_AUTHORITY_EXCEEDED": 403,
}


class Principal(BaseModel):
    """Authenticated caller."""

    name: str
    roles: frozenset[str]


class ResolutionRequest(BaseModel):
    """Reviewer decision body (ESC-04)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "decline", "modify"]
    modified_parameters: dict[str, Any] | None = None
    note: str = ""


class EscalationSummary(BaseModel):
    """What a submitter may see about an escalation."""

    escalation_id: str
    state: str
    queue: str
    deadline: str
    decision_id: str


class ResolutionResponse(BaseModel):
    """Result of a reviewer decision; ``child`` is set for modify."""

    escalation: EscalationRecord
    child: DecisionResponse | None = None


def create_app(runtime: GovernanceRuntime, authenticator: Authenticator) -> FastAPI:
    """Build the API for ``runtime``; every route except ``/healthz`` needs a bearer token."""
    service = runtime.decision_service
    if service is None:
        raise ValueError("runtime has no decision service (pipeline or stores missing)")
    audit: AuditStore = runtime.components["audit_store"]
    sink: AnchorSink | None = runtime.components.get("anchor_sink")
    app = FastAPI(title="agentic-runtime-governance", version="0.1.0")

    def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
        scheme, _, token = (authorization or "").partition(" ")
        identity = authenticator.authenticate(token if scheme.lower() == "bearer" else None)
        if identity is None:
            raise HTTPException(401, "invalid or missing bearer token")
        return Principal(name=identity[0], roles=identity[1])

    def require_role(*roles: str) -> Callable[[Principal], Principal]:
        def check(p: Annotated[Principal, Depends(principal)]) -> Principal:
            if not p.roles & set(roles):
                raise HTTPException(403, f"requires one of: {', '.join(roles)}")
            return p

        return check

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/decisions")
    async def decide(
        request: Request, _: Annotated[Principal, Depends(require_role("submit"))]
    ) -> DecisionResponse:
        try:
            body = await request.json()
        except ValueError:
            body = None
        # Anything that is not a JSON object is still decided (and audited) as a rejection.
        return service.decide(body if isinstance(body, dict) else {})

    @app.get("/v1/escalations/{escalation_id}", response_model=None)
    def get_escalation(
        escalation_id: str,
        who: Annotated[Principal, Depends(require_role("submit", "review", "admin"))],
    ) -> EscalationRecord | EscalationSummary:
        record = service.queue.get(escalation_id)
        if record is None:
            raise HTTPException(404, "escalation not found")
        if who.roles & {"review", "admin"}:
            return record
        return EscalationSummary(
            escalation_id=record.escalation_id,
            state=record.state.value,
            queue=record.queue,
            deadline=record.deadline.isoformat(),
            decision_id=record.decision_id,
        )

    @app.post("/v1/escalations/{escalation_id}/resolution")
    def resolve(
        escalation_id: str,
        body: ResolutionRequest,
        who: Annotated[Principal, Depends(require_role("review"))],
    ) -> ResolutionResponse:
        try:
            result = service.resolve_escalation(
                escalation_id,
                who.name,
                body.action,
                modified_parameters=body.modified_parameters,
                note=body.note,
            )
        except EscalationError as exc:
            raise HTTPException(
                _HTTP_STATUS.get(exc.code, 400), {"code": exc.code, "detail": exc.detail}
            ) from exc
        return ResolutionResponse(escalation=result.escalation, child=result.child)

    @app.post("/v1/escalations/sweep")
    def sweep(_: Annotated[Principal, Depends(require_role("admin"))]) -> list[dict[str, str]]:
        return [{"escalation_id": r.escalation_id, "state": r.state.value} for r in service.sweep()]

    @app.get("/v1/audit/{agent_id}/verify")
    def verify(
        agent_id: str, _: Annotated[Principal, Depends(require_role("admin"))]
    ) -> VerifyResult:
        if sink is not None:
            return verify_with_sink(audit, sink, agent_id)
        return audit.verify(agent_id)

    @app.post("/v1/audit/{agent_id}/anchor")
    def anchor(agent_id: str, _: Annotated[Principal, Depends(require_role("admin"))]) -> Anchor:
        if sink is None:
            raise HTTPException(404, "no anchor sink configured")
        head = audit.head(agent_id)
        if head is None:
            raise HTTPException(404, "empty stream")
        a = Anchor(agent_stream=agent_id, seq=head.seq, entry_hash=head.entry_hash)
        sink.publish(a)
        return a

    return app
