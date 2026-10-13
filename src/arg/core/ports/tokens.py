"""Decision token extension point (INT-04)."""

from abc import ABC, abstractmethod
from datetime import datetime

from arg.core.models import IssuedToken, TokenClaims, TokenError
from arg.core.ports.state import StateStore


class TokenService(ABC):
    """Condition: Auto-Execute/Observe yields a short-lived, one-time token bound to the action.

    ``redeem`` is a template method: verification always precedes consumption, so a token
    presented with a wrong action hash is not burned and a replay is always refused.
    Requirements: INT-04.
    """

    @abstractmethod
    def issue(
        self,
        *,
        subject: str,
        decision_id: str,
        outcome: str,
        act_hash: str,
        policy_version: str,
        at: datetime,
    ) -> IssuedToken:
        """Return a signed token for the decision."""

    @abstractmethod
    def verify(self, token: str, *, act_hash: str, agent_id: str, at: datetime) -> TokenClaims:
        """Return the claims, or raise ``TokenError`` (signature, expiry, subject, action)."""

    def redeem(
        self,
        token: str,
        *,
        act_hash: str,
        agent_id: str,
        at: datetime,
        state_store: StateStore,
    ) -> TokenClaims:
        """Verify, then atomically consume; a second redemption raises ``TOK_REPLAYED``."""
        claims = self.verify(token, act_hash=act_hash, agent_id=agent_id, at=at)
        if not state_store.consume_token(claims.jti):
            raise TokenError("TOK_REPLAYED", claims.jti)
        return claims
