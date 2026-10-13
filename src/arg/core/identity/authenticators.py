"""Envelope origin authentication (ENV-04, SG-02).

Native envelopes are signed by the agent-instance key held in the registry. Gateway envelopes
are authentic by construction: the action is the observed call, so the check is that a
trusted gateway produced it and that it carries the observed call.
"""

from collections.abc import Collection

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from arg.core.crypto import verify_envelope_signature
from arg.core.models import AgentRecord, Envelope, IdentityRejection
from arg.core.ports import EnvelopeAuthenticator
from arg.core.registry import register


@register(EnvelopeAuthenticator, "adapter-signature")
class AdapterSignatureAuthenticator(EnvelopeAuthenticator):
    """Native origin: signature must verify against a registered key of the agent."""

    def authenticate(self, envelope: Envelope, agent: AgentRecord) -> None:
        """Raise ``IdentityRejection`` unless a registered key verifies the signature."""
        if envelope.provenance.origin != "native":
            raise IdentityRejection("IDN_ORIGIN_UNSUPPORTED", envelope.provenance.origin)
        if envelope.provenance.signature is None:
            raise IdentityRejection("IDN_SIGNATURE_MISSING", agent.agent_id)
        for pem in agent.public_keys:
            key = load_pem_public_key(pem.encode())
            if isinstance(key, Ed25519PublicKey) and verify_envelope_signature(envelope, key):
                return
        raise IdentityRejection("IDN_SIGNATURE_INVALID", agent.agent_id)


@register(EnvelopeAuthenticator, "gateway-observed")
class GatewayObservedAuthenticator(EnvelopeAuthenticator):
    """Gateway origin: built by a trusted gateway from the observed call."""

    def __init__(self, trusted_gateways: Collection[str] = ()) -> None:
        """``trusted_gateways``: adapter ids allowed to submit gateway envelopes."""
        self.trusted_gateways = frozenset(trusted_gateways)

    def authenticate(self, envelope: Envelope, agent: AgentRecord) -> None:  # noqa: ARG002
        """Raise ``IdentityRejection`` unless a trusted gateway attests the observed call."""
        prov = envelope.provenance
        if prov.origin != "gateway":
            raise IdentityRejection("IDN_ORIGIN_UNSUPPORTED", prov.origin)
        if prov.adapter_id not in self.trusted_gateways:
            raise IdentityRejection("IDN_GATEWAY_UNTRUSTED", prov.adapter_id)
        if prov.observed_call is None:
            raise IdentityRejection("IDN_GATEWAY_ATTESTATION_MISSING", prov.adapter_id)


@register(EnvelopeAuthenticator, "by-origin")
class OriginDispatchAuthenticator(EnvelopeAuthenticator):
    """Dispatch on ``provenance.origin`` to the native or gateway strategy."""

    def __init__(self, trusted_gateways: Collection[str] = ()) -> None:
        """Build both strategies; ``trusted_gateways`` feeds the gateway one."""
        self._by_origin: dict[str, EnvelopeAuthenticator] = {
            "native": AdapterSignatureAuthenticator(),
            "gateway": GatewayObservedAuthenticator(trusted_gateways),
        }

    def authenticate(self, envelope: Envelope, agent: AgentRecord) -> None:
        """Delegate to the strategy for the envelope's origin."""
        self._by_origin[envelope.provenance.origin].authenticate(envelope, agent)
