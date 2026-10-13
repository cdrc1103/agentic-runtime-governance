"""Gateway adapter template: observe, authenticate, govern, then forward or refuse.

Protocol adapters implement ``observe`` and the three renderers; everything that must not be
skippable is in ``handle``. Any exception is a refusal (INT-05). The request body that was
governed is the body that is forwarded, byte for byte (no TOCTOU between check and use).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from arg.gateway.core import GatewayEngine, Observation, Verdict
from arg.gateway.identity import IdentityResolver


@dataclass(frozen=True)
class GatewayRequest:
    """A normalised inbound request (header names lower-cased)."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""
    query: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Forward:
    """Send the original request upstream unchanged."""


@dataclass(frozen=True)
class Respond:
    """Answer locally; the request is not forwarded."""

    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Passthrough:
    """Not a governed call (e.g. ``tools/list``); forward untouched."""


@dataclass(frozen=True)
class Rejection:
    """Malformed or ungovernable request; refuse with a protocol-appropriate error."""

    code: str
    detail: str = ""
    status: int = 400


class GatewayAdapter(ABC):
    """Condition: an outbound call is intercepted at the infrastructure layer, wrapped in an
    envelope built from what was *observed*, evaluated, and only then forwarded.

    No agent code changes. Requirements: INT-02, INT-04, INT-05.
    """

    def __init__(self, engine: GatewayEngine, identity: IdentityResolver) -> None:
        """Inject the decision logic and the credential resolver."""
        self.engine = engine
        self.identity = identity

    @abstractmethod
    def observe(self, request: GatewayRequest) -> Observation | Passthrough | Rejection:
        """Classify the request and extract the observed call."""

    @abstractmethod
    def render_rejection(self, rejection: Rejection, request: GatewayRequest) -> Respond:
        """Protocol-shaped error for a malformed request."""

    @abstractmethod
    def render_refusal(
        self, obs: Observation, verdict: Verdict, request: GatewayRequest
    ) -> Respond:
        """Protocol-shaped structured refusal carrying ``reason_codes`` / ``escalation_id``."""

    @abstractmethod
    def render_unauthenticated(self, request: GatewayRequest) -> Respond:
        """401 in the protocol's idiom."""

    def handle(self, request: GatewayRequest) -> Forward | Respond:
        """Decide what to do with ``request``; never raises."""
        try:
            seen = self.observe(request)
            if isinstance(seen, Passthrough):
                return Forward()
            if isinstance(seen, Rejection):
                return self.render_rejection(seen, request)
            who = self.identity.resolve(request.headers)
            if who is None:
                return self.render_unauthenticated(request)
            verdict = self.engine.govern(who, seen, request.headers.get("x-arg-decision-token"))
            if verdict.allowed:
                return Forward()
            return self.render_refusal(seen, verdict, request)
        except Exception:  # noqa: BLE001 - fail closed (INT-05)
            return Respond(502, b'{"error":"gateway_error"}', {"content-type": "application/json"})
