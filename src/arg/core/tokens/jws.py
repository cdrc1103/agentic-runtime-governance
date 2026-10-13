"""Minimal compact JWS for Ed25519 (RFC 7515 section 7.1, RFC 8037, alg ``EdDSA``).

Deliberately small and strict: one algorithm, no ``none``, no ``crit``, strict base64url,
and header/payload serialised with RFC 8785 so output is deterministic. Only what decision
tokens need is implemented (compact serialisation, no JWE, no JWK).
"""

import base64
import binascii
import json
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from arg.core.models import TokenError

ALG = "EdDSA"
TYP = "arg-decision+jwt"
_ALLOWED_HEADER = {"alg", "typ", "kid"}


def b64url_encode(data: bytes) -> str:
    """Base64url without padding (RFC 7515 section 2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Strict base64url decode: no padding, no stray characters, canonical encoding only."""
    if not text or any(c not in _B64_ALPHABET for c in text):
        raise TokenError("TOK_MALFORMED", "bad base64url")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise TokenError("TOK_MALFORMED", "bad base64url") from exc
    if b64url_encode(raw) != text:  # rejects non-zero trailing bits (malleability)
        raise TokenError("TOK_MALFORMED", "non-canonical base64url")
    return raw


_B64_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def sign_compact(payload: dict[str, Any], key: Ed25519PrivateKey, kid: str | None = None) -> str:
    """Return ``BASE64URL(header).BASE64URL(payload).BASE64URL(signature)``."""
    header: dict[str, Any] = {"alg": ALG, "typ": TYP}
    if kid is not None:
        header["kid"] = kid
    signing_input = (
        b64url_encode(rfc8785.dumps(header)) + "." + b64url_encode(rfc8785.dumps(payload))
    )
    signature = key.sign(signing_input.encode("ascii"))
    return signing_input + "." + b64url_encode(signature)


def verify_compact(token: str, key: Ed25519PublicKey) -> dict[str, Any]:
    """Verify structure, header, and signature; return the payload object."""
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("TOK_MALFORMED", "expected three segments")
    header_b64, payload_b64, sig_b64 = parts
    header = _json_object(b64url_decode(header_b64), "header")
    if header.get("alg") != ALG:  # also refuses "none" and every MAC/RSA algorithm
        raise TokenError("TOK_ALG_UNSUPPORTED", str(header.get("alg")))
    if header.get("typ") != TYP:
        raise TokenError("TOK_MALFORMED", "unexpected typ")
    if not set(header) <= _ALLOWED_HEADER:
        raise TokenError("TOK_MALFORMED", "unexpected header parameters")
    signature = b64url_decode(sig_b64)
    if len(signature) != 64:
        raise TokenError("TOK_MALFORMED", "signature length")
    try:
        key.verify(signature, f"{header_b64}.{payload_b64}".encode("ascii"))
    except InvalidSignature as exc:
        raise TokenError("TOK_SIGNATURE_INVALID") from exc
    return _json_object(b64url_decode(payload_b64), "payload")


def _json_object(raw: bytes, what: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TokenError("TOK_MALFORMED", f"{what} is not JSON") from exc
    if not isinstance(value, dict):
        raise TokenError("TOK_MALFORMED", f"{what} is not an object")
    return value
