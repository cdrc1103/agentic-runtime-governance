"""Gateway decision logic shared by every protocol (INT-02, INT-04; T-903).

Standalone mode: the gateway builds an envelope from the *observed* call and asks the core.
Hybrid mode: the gateway requires a decision token whose action hash matches the observed
call and consumes it. Either way the observed call, not anything the agent claims, governs.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from arg.adapters.client import GovernanceClient
from arg.core.canonical import canonical_hash
from arg.core.models import (
    Action,
    ActionTrace,
    Context,
    Envelope,
    ObservedCall,
    Provenance,
    TokenError,
    TraceStep,
)
from arg.core.tokens.service import action_hash
from arg.gateway.backend import TokenRedeemer
from arg.gateway.extract import get_path, render
from arg.gateway.identity import GatewayIdentity


class ActionMapping(BaseModel):
    """How an observed call becomes an action (configuration, owned by the institution)."""

    model_config = ConfigDict(extra="forbid")

    action_type: str
    scope: str
    parameters: dict[str, str] = Field(default_factory=dict)
    # Operator-asserted static signals; never agent-reported (see docs/adapters/gateways.md).
    signals: dict[str, float | str | bool] = Field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    """A call the gateway saw, ready to govern."""

    label: str  # observed_call.method, e.g. "tools/call" or "POST"
    target: str  # tool name or request path
    mapping: ActionMapping | None  # None: the call is not mapped, so it is refused
    document: Mapping[str, Any]  # what paths in the mapping are evaluated against
    request_id: Any = None


@dataclass(frozen=True)
class Verdict:
    """The gateway's decision for one observed call."""

    allowed: bool
    outcome: str
    reason_codes: tuple[str, ...] = ()
    decision_id: str | None = None
    escalation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _deny(*codes: str) -> Verdict:
    return Verdict(False, "deny", tuple(codes))


class GatewayEngine:
    """Maps observations to verdicts; holds no per-request state (stateless gateway)."""

    def __init__(
        self,
        gateway_id: str,
        mode: Literal["standalone", "hybrid"],
        client: GovernanceClient | None = None,
        redeemer: TokenRedeemer | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Standalone needs a ``client``; hybrid needs a ``redeemer``."""
        if mode == "standalone" and client is None:
            raise ValueError("standalone mode needs a governance client")
        if mode == "hybrid" and redeemer is None:
            raise ValueError("hybrid mode needs a token redeemer")
        self.gateway_id = gateway_id
        self.mode = mode
        self.client = client
        self.redeemer = redeemer
        self.clock = clock

    def govern(
        self, identity: GatewayIdentity, obs: Observation, presented_token: str | None
    ) -> Verdict:
        """Return the verdict; never raises for governance refusals."""
        if obs.mapping is None:
            return _deny("GW_UNMAPPED")
        try:
            parameters = {k: get_path(obs.document, p) for k, p in obs.mapping.parameters.items()}
            scope = render(obs.mapping.scope, obs.document)
            action = Action(type=obs.mapping.action_type, scope=scope, parameters=parameters)
        except (KeyError, ValueError):
            return _deny("GW_PARAMETER_UNREADABLE")
        if self.mode == "hybrid":
            return self._hybrid(identity, action, presented_token)
        return self._standalone(identity, obs, action, obs.mapping.signals)

    def _hybrid(self, identity: GatewayIdentity, action: Action, token: str | None) -> Verdict:
        assert self.redeemer is not None
        if not token:
            return _deny("GW_TOKEN_MISSING")
        try:
            self.redeemer.redeem(token, action_hash(action), identity.agent_id)
        except TokenError as exc:
            return _deny(exc.code)
        return Verdict(True, "auto_execute")

    def _standalone(
        self,
        identity: GatewayIdentity,
        obs: Observation,
        action: Action,
        signals: dict[str, float | str | bool],
    ) -> Verdict:
        assert self.client is not None
        now = self.clock()
        params_hash = canonical_hash(action.parameters)
        envelope = Envelope(
            envelope_id=f"gw-{uuid.uuid4().hex}",
            created_at=now,
            action=action,
            action_trace=ActionTrace(
                steps=[
                    TraceStep(
                        step_id="s1",
                        kind="tool_call",
                        name=obs.target,
                        input_hash=params_hash,
                        started_at=now,
                        ended_at=now,
                    )
                ]
            ),
            context=Context(
                agent_id=identity.agent_id,
                mandate_ref=identity.mandate_ref,
                network_context=identity.network_context,
                signals=signals,
            ),
            provenance=Provenance(
                origin="gateway",
                adapter_id=self.gateway_id,
                observed_call=ObservedCall(
                    method=obs.label, target=obs.target, params_hash=params_hash
                ),
            ),
        )
        try:
            response = self.client.decide(envelope.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 - INT-05
            return _deny("GW_NO_DECISION")
        allowed = response.outcome in ("auto_execute", "observe")
        return Verdict(
            allowed,
            response.outcome,
            tuple(response.reason_codes),
            response.decision_id,
            response.escalation_id,
        )
