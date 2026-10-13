"""Agent identity extension points (IDN, ENV-04)."""

from abc import ABC, abstractmethod

from arg.core.models import AgentRecord, Envelope, IdentityBinding


class AgentRegistry(ABC):
    """Condition: a claimed agent resolves to exactly one registry entry, or to nothing.

    Requirements: IDN-01, IDN-03, IDN-04.
    """

    @abstractmethod
    def resolve(self, agent_id: str, network_context: str | None) -> AgentRecord | None:
        """Return the entry for ``agent_id`` in ``network_context``, or None."""


class EnvelopeAuthenticator(ABC):
    """Condition: the origin of an envelope is established, not taken from the agent's report.

    Requirements: ENV-04.
    """

    @abstractmethod
    def authenticate(self, envelope: Envelope, agent: AgentRecord) -> None:
        """Return if the provenance checks out; raise ``IdentityRejection`` otherwise."""


class IdentityVerifier(ABC):
    """Condition: the action is bound to a registered agent before anything else.

    Otherwise it is rejected with a reason code so the rejection can be audited.
    Requirements: IDN-01, IDN-02, IDN-05.
    """

    @abstractmethod
    def verify(self, envelope: Envelope) -> IdentityBinding:
        """Return a confirmed binding or raise ``IdentityRejection``."""
