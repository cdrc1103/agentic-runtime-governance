"""API caller authentication (decision D5, T-606).

Roles: ``submit``, ``consume``, ``review``, ``admin``. mTLS and OIDC are described in
``docs/production-gaps.md`` and not built.
"""

import hmac
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from arg.core.registry import register

ROLES = frozenset({"submit", "consume", "review", "admin"})


class Authenticator(ABC):
    """Condition: an API caller is authenticated into a principal with roles.

    Requirements: D5 (roles: submit, consume, review, admin).
    """

    @abstractmethod
    def authenticate(self, credential: str | None) -> tuple[str, frozenset[str]] | None:
        """Return ``(principal, roles)`` or None if the credential is not valid."""


@register(Authenticator, "bearer")
class BearerTokenAuthenticator(Authenticator):
    """Static role-scoped bearer tokens from config or an environment variable (JSON).

    Format: ``{"<token>": {"principal": "rita.reviewer", "roles": ["review"]}}``. Tokens are
    compared in constant time. The principal of a ``review`` token is the reviewer id.
    """

    def __init__(
        self, tokens: Mapping[str, Mapping[str, Any]] | None = None, tokens_env: str | None = None
    ) -> None:
        """Take tokens directly and/or from environment variable ``tokens_env``."""
        merged: dict[str, Mapping[str, Any]] = dict(tokens or {})
        if tokens_env is not None:
            raw = os.environ.get(tokens_env)
            if not raw:
                raise ValueError(f"environment variable {tokens_env} is not set")
            merged.update(json.loads(raw))
        if not merged:
            raise ValueError("no tokens configured")
        self._tokens: dict[str, tuple[str, frozenset[str]]] = {}
        for token, spec in merged.items():
            roles = frozenset(spec["roles"])
            if not roles <= ROLES:
                raise ValueError(f"unknown roles {sorted(roles - ROLES)}")
            self._tokens[token] = (str(spec["principal"]), roles)

    def authenticate(self, credential: str | None) -> tuple[str, frozenset[str]] | None:
        """Return ``(principal, roles)`` for a known token, else None."""
        if not credential:
            return None
        found: tuple[str, frozenset[str]] | None = None
        for token, identity in self._tokens.items():  # no early exit: constant-time-ish
            if hmac.compare_digest(token.encode(), credential.encode()):
                found = identity
        return found


@register(Authenticator, "unsafe-none")
class UnsafeNoAuthenticator(Authenticator):
    """Grants every role to every caller. Tests only: refuses to start outside test mode."""

    def __init__(self) -> None:
        """Refuse construction unless ``ARG_TEST_MODE=1``."""
        if os.environ.get("ARG_TEST_MODE") != "1":
            raise RuntimeError("UnsafeNoAuthenticator requires ARG_TEST_MODE=1 (tests only)")

    def authenticate(self, credential: str | None) -> tuple[str, frozenset[str]] | None:  # noqa: ARG002
        """Return a fixed principal holding all roles."""
        return ("unsafe-test", ROLES)
