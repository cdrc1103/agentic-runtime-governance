"""Agent identity extension points (IDN, ENV-04)."""

from abc import ABC, abstractmethod

from arg.core.types import JsonObject


class AgentRegistry(ABC):
    """Condition: a claimed agent resolves to exactly one registry entry, or to nothing.

    Requirements: IDN-01, IDN-03, IDN-04.
    """

    @abstractmethod
    def resolve(self, agent_id: str, network_context: str | None) -> JsonObject | None:
        """Return the registry entry for ``agent_id`` in ``network_context``, or None."""


class IdentityVerifier(ABC):
    """Condition: the action is bound to a registered agent before anything else.

    Otherwise it is rejected and the rejection is reported for audit.
    Requirements: IDN-01, IDN-02, IDN-05.
    """

    @abstractmethod
    def verify(self, envelope: JsonObject) -> JsonObject:
        """Return a confirmed identity binding, or raise a reason-coded rejection."""


class EnvelopeAuthenticator(ABC):
    """Condition: the origin of an envelope is established, not taken from the agent's report.

    Requirements: ENV-04.
    """

    @abstractmethod
    def authenticate(self, envelope: JsonObject) -> bool:
        """Return True only if the envelope's provenance checks out."""
