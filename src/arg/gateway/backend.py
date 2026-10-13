"""How a gateway redeems decision tokens in hybrid mode (INT-04)."""

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime

from arg.adapters.client import Transport
from arg.core.models import TokenError
from arg.core.ports import StateStore, TokenService
from arg.core.registry import register


class TokenRedeemer(ABC):
    """Condition: a token is verified against the observed action and consumed exactly once.

    Requirements: INT-04.
    """

    @abstractmethod
    def redeem(self, token: str, act_hash: str, agent_id: str) -> None:
        """Return on success; raise ``TokenError`` for any refusal."""


@register(TokenRedeemer, "embedded")
class EmbeddedRedeemer(TokenRedeemer):
    """Redeems in-process through the token service and state store."""

    def __init__(
        self, token_service: TokenService, state_store: StateStore, clock: Callable[[], datetime]
    ) -> None:
        """Bind the collaborators."""
        self.tokens = token_service
        self.state = state_store
        self.clock = clock

    def redeem(self, token: str, act_hash: str, agent_id: str) -> None:
        """Verify then consume."""
        self.tokens.redeem(
            token, act_hash=act_hash, agent_id=agent_id, at=self.clock(), state_store=self.state
        )


def _urllib(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@register(TokenRedeemer, "http")
class HttpRedeemer(TokenRedeemer):
    """Redeems through ``POST /v1/tokens/consume`` with a ``consume``-role bearer token."""

    def __init__(
        self,
        base_url: str,
        consume_token: str,
        timeout_s: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        """``transport`` replaces ``urllib`` (tests, custom TLS)."""
        self.url = base_url.rstrip("/") + "/v1/tokens/consume"
        self.headers = {
            "Authorization": f"Bearer {consume_token}",
            "Content-Type": "application/json",
        }
        self.timeout_s = timeout_s
        self.transport = transport or _urllib

    def redeem(self, token: str, act_hash: str, agent_id: str) -> None:
        """Map HTTP refusals back to ``TokenError``; any failure refuses (fail closed)."""
        body = json.dumps({"token": token, "act_hash": act_hash, "agent_id": agent_id}).encode()
        try:
            status, payload = self.transport(self.url, self.headers, body, self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise TokenError("TOK_BACKEND_UNAVAILABLE", str(exc)) from exc
        if status == 200:
            return
        try:
            code = json.loads(payload)["detail"]["code"]
        except Exception:  # noqa: BLE001
            code = "TOK_BACKEND_UNAVAILABLE"
        raise TokenError(str(code))
