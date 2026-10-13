"""Audit log extension points (AUD)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from arg.core.types import JsonObject


class AuditStore(ABC):
    """Condition: append-only, tamper-evident persistence of every governance decision.

    Requirements: AUD-01..06. ``append`` becomes a concrete template method in Phase 5
    (hash chain, expected-head check) calling abstract ``_persist``/``_read_head``.
    """

    @abstractmethod
    def read_stream(self, agent_stream: str) -> Sequence[JsonObject]:
        """Return the entries of one agent stream in sequence order."""


class AnchorSink(ABC):
    """Condition: the chain head is exported outside the store that holds the chain.

    Requirements: AUD-06.
    """

    @abstractmethod
    def publish(self, agent_stream: str, seq: int, entry_hash: str) -> None:
        """Write the head anchor to the external sink."""
