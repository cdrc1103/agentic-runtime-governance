"""Ed25519 decision token service (INT-04, T-701)."""

import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import ValidationError

from arg.core import crypto
from arg.core.canonical import canonical_hash
from arg.core.models import Action, IssuedToken, TokenClaims, TokenError
from arg.core.ports import TokenService
from arg.core.registry import register
from arg.core.tokens import jws


def action_hash(action: Action) -> str:
    """Hash binding a token to the action: ``SHA-256(JCS({type, scope, parameters}))``.

    ``parent_envelope_id`` is excluded: a gateway cannot know it, and it does not change
    what executes.
    """
    return canonical_hash(
        {"type": action.type, "scope": action.scope, "parameters": action.parameters}
    )


@register(TokenService, "ed25519")
class Ed25519TokenService(TokenService):
    """Signs with a private key; a service holding only a public key can verify, not issue."""

    def __init__(
        self,
        private_key_path: str | Path | None = None,
        private_key_env: str | None = None,
        public_key_path: str | Path | None = None,
        public_key_env: str | None = None,
        issuer: str = "arg",
        ttl_seconds: int = 300,
        kid: str | None = None,
        private_key: Ed25519PrivateKey | None = None,
        public_key: Ed25519PublicKey | None = None,
    ) -> None:
        """Provide a private key (issue+verify) or a public key (verify only)."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if private_key is None and (private_key_path or private_key_env):
            private_key = crypto.load_private_key(
                path=Path(private_key_path) if private_key_path else None, env=private_key_env
            )
        if public_key is None and private_key is not None:
            public_key = private_key.public_key()
        if public_key is None and (public_key_path or public_key_env):
            public_key = crypto.load_public_key(
                path=Path(public_key_path) if public_key_path else None, env=public_key_env
            )
        if public_key is None:
            raise ValueError("a private or public key is required")
        self._private = private_key
        self._public = public_key
        self.issuer = issuer
        self.ttl_seconds = ttl_seconds
        self.kid = kid

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
        """Sign a one-time token valid for ``ttl_seconds`` from ``at``."""
        if self._private is None:
            raise TokenError("TOK_NO_SIGNING_KEY", "verify-only token service")
        iat = int(at.timestamp())
        try:
            claims = TokenClaims(
                iss=self.issuer,
                sub=subject,
                jti=uuid.uuid4().hex,
                decision_id=decision_id,
                outcome=outcome,  # type: ignore[arg-type]
                act_hash=act_hash,
                policy_version=policy_version,
                iat=iat,
                exp=iat + self.ttl_seconds,
            )
        except ValidationError as exc:
            raise TokenError("TOK_CLAIMS_INVALID", str(exc.error_count())) from exc
        token = jws.sign_compact(claims.model_dump(), self._private, self.kid)
        return IssuedToken(token, claims)

    def verify(self, token: str, *, act_hash: str, agent_id: str, at: datetime) -> TokenClaims:
        """Check signature, claims, issuer, validity window, subject and action hash."""
        payload = jws.verify_compact(token, self._public)
        try:
            claims = TokenClaims(**payload)
        except (ValidationError, TypeError) as exc:
            raise TokenError("TOK_CLAIMS_INVALID", "claims do not match the schema") from exc
        if claims.iss != self.issuer:
            raise TokenError("TOK_ISSUER_MISMATCH", claims.iss)
        now = int(at.timestamp())
        if now < claims.iat:
            raise TokenError("TOK_NOT_YET_VALID")
        if now >= claims.exp:
            raise TokenError("TOK_EXPIRED")
        if claims.sub != agent_id:
            raise TokenError("TOK_SUBJECT_MISMATCH", agent_id)
        if claims.act_hash != act_hash:
            raise TokenError("TOK_ACTION_MISMATCH")
        return claims
