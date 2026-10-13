"""Default identity verification (IDN-01, IDN-02, IDN-05, T-203)."""

from arg.core.models import Envelope, IdentityBinding, IdentityRejection
from arg.core.models.identity import AgentStatus
from arg.core.ports import AgentRegistry, EnvelopeAuthenticator, IdentityVerifier
from arg.core.registry import register


@register(IdentityVerifier, "default")
class DefaultIdentityVerifier(IdentityVerifier):
    """Resolve, check status and network context, then authenticate the envelope origin."""

    def __init__(
        self, agent_registry: AgentRegistry, envelope_authenticator: EnvelopeAuthenticator
    ) -> None:
        """Inject the registry and origin authenticator (wired by role name)."""
        self.registry = agent_registry
        self.authenticator = envelope_authenticator

    def verify(self, envelope: Envelope) -> IdentityBinding:
        """Return the identity binding or raise ``IdentityRejection`` (fail closed)."""
        ctx = envelope.context
        agent = self.registry.resolve(ctx.agent_id, ctx.network_context)
        if agent is None:
            raise IdentityRejection("IDN_AGENT_UNKNOWN", ctx.agent_id)
        if agent.status is not AgentStatus.ACTIVE:
            raise IdentityRejection(f"IDN_AGENT_{agent.status.name}", agent.agent_id)
        if (
            agent.allowed_network_contexts
            and ctx.network_context not in agent.allowed_network_contexts
        ):
            raise IdentityRejection("IDN_CONTEXT_NOT_ALLOWED", str(ctx.network_context))
        self.authenticator.authenticate(envelope, agent)
        return IdentityBinding(
            agent_id=agent.agent_id,
            agent_class=agent.agent_class,
            principal=agent.principal,
            registry_id=agent.registry_id,
            origin=envelope.provenance.origin,
            network_context=ctx.network_context,
        )
