"""HTTP egress gateway: governs outbound REST calls by method and path (T-902).

Route configuration maps ``METHOD /path/{var}`` to an action type; parameters are extracted
with the dotted-path subset from ``{path, query, headers, body}``. Unmatched routes are
refused (default deny) unless a route is marked ``passthrough``.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arg.core.registry import register
from arg.gateway.base import (
    GatewayAdapter,
    GatewayRequest,
    Passthrough,
    Rejection,
    Respond,
)
from arg.gateway.core import ActionMapping, GatewayEngine, Observation, Verdict
from arg.gateway.identity import IdentityResolver

_JSON = {"content-type": "application/json"}


class Route(BaseModel):
    """One governed (or explicitly passed-through) route."""

    model_config = ConfigDict(extra="forbid")

    name: str
    method: str
    path: str
    passthrough: bool = False
    action_type: str | None = None
    scope: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    signals: dict[str, float | str | bool] = Field(default_factory=dict)

    def mapping(self) -> ActionMapping:
        """The action mapping for a governed route."""
        if self.action_type is None or self.scope is None:
            raise ValueError(f"route {self.name!r} needs action_type and scope")
        return ActionMapping(
            action_type=self.action_type,
            scope=self.scope,
            parameters=self.parameters,
            signals=self.signals,
        )


def _compile(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", path)
    rx = "".join(f"(?P<{p[1:-1]}>[^/]+)" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(f"^{rx}$")


@register(GatewayAdapter, "http-egress")
class HttpEgressGateway(GatewayAdapter):
    """Matches requests against routes and governs the ones that carry authority."""

    def __init__(
        self, engine: GatewayEngine, identity: IdentityResolver, routes: list[dict[str, Any]]
    ) -> None:
        """Compile route patterns; governed routes are validated up front."""
        super().__init__(engine, identity)
        self.routes = [Route.model_validate(r) for r in routes]
        for r in self.routes:
            if not r.passthrough:
                r.mapping()
        self._compiled = [(r, _compile(r.path)) for r in self.routes]

    def observe(self, request: GatewayRequest) -> Observation | Passthrough | Rejection:
        """Find the route; build the extraction document from the request."""
        for route, rx in self._compiled:
            match = rx.match(request.path)
            if match is None or route.method.upper() != request.method.upper():
                continue
            if route.passthrough:
                return Passthrough()
            body: Any = None
            if request.body:
                try:
                    body = json.loads(request.body)
                except ValueError:
                    return Rejection("invalid_body", "body is not JSON", status=400)
            document = {
                "path": match.groupdict(),
                "query": request.query,
                "headers": request.headers,
                "body": body,
            }
            return Observation(
                label=request.method.upper(),
                target=request.path,
                mapping=route.mapping(),
                document=document,
                request_id=route.name,
            )
        return Observation(
            label=request.method.upper(),
            target=request.path,
            mapping=None,
            document={},
            request_id=None,
        )

    def render_rejection(self, rejection: Rejection, request: GatewayRequest) -> Respond:
        """JSON error body."""
        body = json.dumps({"error": rejection.code, "detail": rejection.detail}).encode()
        return Respond(rejection.status, body, dict(_JSON))

    def render_refusal(
        self, obs: Observation, verdict: Verdict, request: GatewayRequest
    ) -> Respond:
        """403 with structured reasons; never a 2xx, so a client cannot mistake it for success."""
        pending = verdict.outcome == "escalate" and verdict.escalation_id
        payload = {
            "error": "pending_review" if pending else "governance_denied",
            "outcome": verdict.outcome,
            "reason_codes": list(verdict.reason_codes),
            "decision_id": verdict.decision_id,
            "escalation_id": verdict.escalation_id,
        }
        headers = dict(_JSON)
        if verdict.escalation_id:
            headers["x-arg-escalation-id"] = verdict.escalation_id
        return Respond(403, json.dumps(payload).encode(), headers)

    def render_unauthenticated(self, request: GatewayRequest) -> Respond:
        """401 with a bearer challenge."""
        return Respond(
            401, b'{"error":"authentication_required"}', {**_JSON, "www-authenticate": "Bearer"}
        )
