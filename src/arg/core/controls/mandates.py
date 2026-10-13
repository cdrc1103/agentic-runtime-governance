"""File-backed mandate resolution and validation (CTL-03, CTL-04, SG-10, T-304)."""

from collections.abc import Collection, Mapping
from datetime import datetime
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from arg.core.crypto import verify_mandate_signature
from arg.core.models import Mandate, MandateRejection
from arg.core.ports import MandateResolver
from arg.core.registry import register


@register(MandateResolver, "file")
class FileMandateResolver(MandateResolver):
    """Mandates, principal keys, and revocations from one YAML file (or direct arguments).

    File keys: ``mandates`` (list), ``principals`` ({name: PEM public key}), ``revoked``
    (list of revocation refs). The agent has no write path to any of these (T9).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        max_depth: int = 1,
        mandates: Collection[Mandate] = (),
        principals: Mapping[str, str] | None = None,
        revoked: Collection[str] = (),
    ) -> None:
        """Load from ``path`` and/or take values directly; ``max_depth`` bounds delegation."""
        data = yaml.safe_load(Path(path).read_text()) if path is not None else {}
        data = data or {}
        loaded = [*mandates, *(Mandate(**m) for m in data.get("mandates", []))]
        self._mandates = {m.mandate_id: m for m in loaded}
        if len(self._mandates) != len(loaded):
            raise ValueError("duplicate mandate_id")
        self._principals = {**data.get("principals", {}), **(principals or {})}
        self._revoked = {*data.get("revoked", []), *revoked}
        self.max_depth = max_depth

    def resolve(self, mandate_ref: str, agent_id: str, at: datetime) -> Mandate:
        """Return the mandate if valid for ``agent_id`` at ``at``; else raise ``MandateRejection``."""
        m = self._mandates.get(mandate_ref)
        if m is None:
            raise MandateRejection("MND_NOT_FOUND", mandate_ref)
        if m.agent_id != agent_id:
            raise MandateRejection("MND_AGENT_MISMATCH", agent_id)
        if m.not_after < m.not_before:
            raise MandateRejection("MND_VALIDITY_INVERTED", mandate_ref)
        if at < m.not_before:
            raise MandateRejection("MND_NOT_YET_VALID", mandate_ref)
        if at > m.not_after:
            raise MandateRejection("MND_EXPIRED", mandate_ref)
        if m.revocation_ref is not None and m.revocation_ref in self._revoked:
            raise MandateRejection("MND_REVOKED", m.revocation_ref)
        if m.depth != len(m.delegation_chain):
            raise MandateRejection(
                "MND_DEPTH_INCOHERENT", f"{m.depth} != {len(m.delegation_chain)}"
            )
        if m.depth > self.max_depth:
            raise MandateRejection("MND_DEPTH_EXCEEDED", f"{m.depth} > {self.max_depth}")
        pem = self._principals.get(m.principal)
        if pem is None:
            raise MandateRejection("MND_PRINCIPAL_UNKNOWN", m.principal)
        try:
            key = load_pem_public_key(pem.encode())
        except ValueError:
            key = None
        if not isinstance(key, Ed25519PublicKey):
            raise MandateRejection("MND_PRINCIPAL_KEY_INVALID", m.principal)
        if m.signature is None or not verify_mandate_signature(m, key):
            raise MandateRejection("MND_SIGNATURE_INVALID", mandate_ref)
        return m
