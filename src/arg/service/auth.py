"""API caller authentication extension point (decision D5)."""

from abc import ABC, abstractmethod


class Authenticator(ABC):
    """Condition: an API caller is authenticated into a principal with roles.

    Requirements: D5 (roles: submit, consume, review, admin).
    """

    @abstractmethod
    def authenticate(self, credential: str | None) -> tuple[str, frozenset[str]] | None:
        """Return ``(principal, roles)`` or None if the credential is not valid."""
