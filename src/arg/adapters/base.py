"""The docking point: what a framework adapter must (and need not) implement.

An adapter turns *a framework's event* into an envelope and turns *a decision* back into
*framework behaviour*. Everything that must not be skippable (signing, asking the core
before acting, failing closed, mapping outcomes) lives in the template methods here, so a
framework adapter implements only two small, framework-specific hooks:

* ``build_envelope(event)``: map the framework's tool-call event to an ``Envelope``.
* ``enforce(result, event)``: how to stop (or park) the action in that framework.

See ``docs/adapters/README.md``. Requirements: INT-01, INT-05, INT-06.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.adapters.client import GovernanceClient
from arg.core.crypto import sign_envelope
from arg.core.models import DecisionResponse, Envelope

T = TypeVar("T")


@dataclass(frozen=True)
class GuardResult:
    """What the adapter learned about one proposed action."""

    verdict: Literal["allow", "block", "pending"]
    outcome: str
    reason_codes: tuple[str, ...] = ()
    decision_id: str | None = None
    token: str | None = None
    escalation_id: str | None = None

    @property
    def allowed(self) -> bool:
        """True only for Auto-Execute and Observe."""
        return self.verdict == "allow"


class ActionBlocked(Exception):  # noqa: N818 - domain term
    """Raised by the default ``enforce`` when governance denies the action."""

    def __init__(self, result: GuardResult) -> None:
        """Keep the structured reason."""
        super().__init__(f"blocked: {', '.join(result.reason_codes) or result.outcome}")
        self.result = result


@dataclass(frozen=True)
class PendingAction:
    """Structured result returned in place of execution when the action is held for review."""

    escalation_id: str | None
    decision_id: str | None
    reason_codes: tuple[str, ...]


class NativeAdapter(ABC):
    """Condition: the agent emits an envelope before each proposed action and obeys the outcome.

    The validator's answer arrives before the agent acts (INT-01). The mapping is fixed:
    Deny -> block with structured reasons; Escalate -> pending with ``escalation_id``;
    Auto-Execute/Observe -> proceed with the decision token attached. Any failure to obtain
    a decision is a block (INT-05).
    """

    def __init__(
        self,
        client: GovernanceClient,
        signer: Ed25519PrivateKey | None = None,
        require_token: bool = False,
    ) -> None:
        """``signer`` is the agent-instance key (SG-02); ``require_token`` for hybrid mode."""
        self.client = client
        self.signer = signer
        self.require_token = require_token

    # ---- hooks a framework adapter implements --------------------------------------
    @abstractmethod
    def build_envelope(self, event: Any) -> Envelope:
        """Map a framework event (tool call, step, ...) to an unsigned ``Envelope``."""

    def enforce(self, result: GuardResult, event: Any) -> Any:  # noqa: ARG002
        """Framework-specific stop. Default: raise ``ActionBlocked`` / return ``PendingAction``."""
        if result.verdict == "pending":
            return PendingAction(result.escalation_id, result.decision_id, result.reason_codes)
        raise ActionBlocked(result)

    # ---- template methods (do not override) ---------------------------------------
    def guard(self, event: Any) -> GuardResult:
        """Ask the core; never raises; anything unexpected is a block."""
        try:
            envelope = self.build_envelope(event)
            if self.signer is not None:
                envelope = sign_envelope(envelope, self.signer)
            response = self.client.decide(envelope.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 - INT-05: no decision means no action
            return GuardResult("block", "deny", ("ADAPTER_NO_DECISION",))
        return self._map(response)

    def run(self, event: Any, execute: Callable[[GuardResult], T]) -> T | Any:
        """Execute only if allowed; otherwise delegate to ``enforce``."""
        result = self.guard(event)
        if result.allowed:
            return execute(result)
        return self.enforce(result, event)

    def _map(self, response: DecisionResponse) -> GuardResult:
        common: dict[str, Any] = {
            "outcome": response.outcome,
            "reason_codes": tuple(response.reason_codes),
            "decision_id": response.decision_id,
            "escalation_id": response.escalation_id,
        }
        if response.outcome in ("auto_execute", "observe"):
            if self.require_token and not response.token:
                return GuardResult(
                    "block", "deny", ("ADAPTER_TOKEN_MISSING",), response.decision_id
                )
            return GuardResult("allow", token=response.token, **common)
        if response.outcome == "escalate" and response.escalation_id:
            return GuardResult("pending", **common)
        return GuardResult("block", **common)
