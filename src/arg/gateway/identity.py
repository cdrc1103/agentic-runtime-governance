"""Gateway-side agent identity from presented credentials (T-901, T-902).

The gateway, not the agent's own envelope, says who is calling. mTLS and JWT claim mapping
are deliberately not built (``docs/production-gaps.md``); implement ``IdentityResolver`` to
add them.
"""

import hmac
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from arg.core.registry import register


@dataclass(frozen=True)
class GatewayIdentity:
    """Who the gateway believes is calling."""

    agent_id: str
    mandate_ref: str | None = None
    network_context: str | None = None


class AgentCredential(BaseModel):
    """Configuration for one agent credential."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    mandate_ref: str | None = None
    network_context: str | None = None


class IdentityResolver(ABC):
    """Condition: the calling agent is established from credentials the gateway verified.

    Requirements: INT-02, ENV-04.
    """

    @abstractmethod
    def resolve(self, headers: Mapping[str, str]) -> GatewayIdentity | None:
        """Return the identity, or None if the request is not authenticated."""


@register(IdentityResolver, "static-bearer")
class StaticBearerIdentityResolver(IdentityResolver):
    """Maps ``Authorization: Bearer <token>`` to an agent via configuration."""

    def __init__(self, credentials: Mapping[str, Mapping[str, str | None]]) -> None:
        """``credentials``: token -> {agent_id, mandate_ref?, network_context?}."""
        self._creds = {t: AgentCredential.model_validate(dict(c)) for t, c in credentials.items()}
        if not self._creds:
            raise ValueError("no credentials configured")

    def resolve(self, headers: Mapping[str, str]) -> GatewayIdentity | None:
        """Constant-time lookup of the bearer token."""
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        found: AgentCredential | None = None
        for known, cred in self._creds.items():
            if hmac.compare_digest(known.encode(), token.encode()):
                found = cred
        if found is None:
            return None
        return GatewayIdentity(found.agent_id, found.mandate_ref, found.network_context)
