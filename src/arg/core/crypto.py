"""Ed25519 signing helpers and envelope signing (ENV-04, T-104).

Keys are loaded from PEM files or environment variables; tests generate keys at run time.
Key management and rotation are out of scope (``docs/production-gaps.md``).
"""

import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from arg.core.canonical import canonical_bytes
from arg.core.models import Envelope, Mandate


def generate_private_key() -> Ed25519PrivateKey:
    """Return a fresh Ed25519 private key (tests, demo)."""
    return Ed25519PrivateKey.generate()


def private_key_pem(key: Ed25519PrivateKey) -> bytes:
    """Serialise a private key as unencrypted PKCS8 PEM."""
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_key_pem(key: Ed25519PublicKey) -> bytes:
    """Serialise a public key as SubjectPublicKeyInfo PEM."""
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def load_private_key(*, path: Path | None = None, env: str | None = None) -> Ed25519PrivateKey:
    """Load a PEM private key from ``path`` or from environment variable ``env``."""
    pem = _read_pem(path, env)
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key


def load_public_key(*, path: Path | None = None, env: str | None = None) -> Ed25519PublicKey:
    """Load a PEM public key from ``path`` or from environment variable ``env``."""
    key = serialization.load_pem_public_key(_read_pem(path, env))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return key


def _read_pem(path: Path | None, env: str | None) -> bytes:
    if (path is None) == (env is None):
        raise ValueError("give exactly one of path or env")
    if path is not None:
        return path.read_bytes()
    value = os.environ.get(env or "")
    if not value:
        raise ValueError(f"environment variable {env} is not set")
    return value.encode()


def sign(key: Ed25519PrivateKey, payload: bytes) -> str:
    """Return the base64url (unpadded) Ed25519 signature of ``payload``."""
    return base64.urlsafe_b64encode(key.sign(payload)).rstrip(b"=").decode()


def verify(key: Ed25519PublicKey, payload: bytes, signature: str) -> bool:
    """Return True iff ``signature`` is valid for ``payload``; never raises on bad input."""
    try:
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        key.verify(raw, payload)
    except (InvalidSignature, ValueError):
        return False
    return True


def signing_payload(envelope: Envelope) -> bytes:
    """Canonical bytes of the envelope with ``provenance.signature`` cleared.

    The signature cannot cover itself, so it is nulled before canonicalisation.
    """
    unsigned = envelope.model_copy(
        update={"provenance": envelope.provenance.model_copy(update={"signature": None})}
    )
    return canonical_bytes(unsigned)


def sign_envelope(envelope: Envelope, key: Ed25519PrivateKey) -> Envelope:
    """Return a copy of ``envelope`` carrying the adapter's signature (native origin)."""
    sig = sign(key, signing_payload(envelope))
    return envelope.model_copy(
        update={"provenance": envelope.provenance.model_copy(update={"signature": sig})}
    )


def verify_envelope_signature(envelope: Envelope, key: Ed25519PublicKey) -> bool:
    """Return True iff the envelope carries a valid signature from ``key`` (ENV-04)."""
    sig = envelope.provenance.signature
    return sig is not None and verify(key, signing_payload(envelope), sig)


def mandate_signing_payload(mandate: Mandate) -> bytes:
    """Canonical bytes of the mandate with ``signature`` cleared (principal signs this)."""
    return canonical_bytes(mandate.model_copy(update={"signature": None}))


def sign_mandate(mandate: Mandate, key: Ed25519PrivateKey) -> Mandate:
    """Return a copy of ``mandate`` signed with the principal's key."""
    return mandate.model_copy(update={"signature": sign(key, mandate_signing_payload(mandate))})


def verify_mandate_signature(mandate: Mandate, key: Ed25519PublicKey) -> bool:
    """Return True iff the mandate carries a valid signature from ``key``."""
    return mandate.signature is not None and verify(
        key, mandate_signing_payload(mandate), mandate.signature
    )
