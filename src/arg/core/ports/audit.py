"""Audit log extension points (AUD)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from arg.core.audit.chain import GENESIS_HASH, compute_entry_hash, verify_entries
from arg.core.models import Anchor, AuditConflict, AuditContent, AuditEntry, VerifyResult


class AuditStore(ABC):
    """Condition: append-only, tamper-evident persistence of every governance decision.

    ``append`` is a template method: the hash chain and the expected-head check cannot be
    bypassed by an implementation, which supplies only ``_read_head``, ``_persist`` and
    ``read_stream``. Requirements: AUD-01..06.
    """

    def append(self, content: AuditContent, expected_head: str | None) -> AuditEntry:
        """Chain ``content`` after the stream head; ``expected_head`` is the head hash seen."""
        stream = content.agent_stream
        head = self._read_head(stream)
        actual = head.entry_hash if head else None
        if actual != expected_head:
            raise AuditConflict(f"{stream}: head is {actual}, caller expected {expected_head}")
        seq = 1 if head is None else head.seq + 1
        draft = AuditEntry(
            **content.model_dump(),
            entry_id=f"{stream}#{seq}",
            seq=seq,
            prev_hash=head.entry_hash if head else GENESIS_HASH,
            entry_hash="",
        )
        entry = draft.model_copy(update={"entry_hash": compute_entry_hash(draft)})
        self._persist(entry)
        return entry

    def head(self, agent_stream: str) -> AuditEntry | None:
        """Latest entry of the stream, or None if empty."""
        return self._read_head(agent_stream)

    def verify(self, agent_stream: str, anchor: Anchor | None = None) -> VerifyResult:
        """Verify the stream's chain (and, if given, the external anchor)."""
        return verify_entries(self.read_stream(agent_stream), agent_stream, anchor)

    @abstractmethod
    def _read_head(self, agent_stream: str) -> AuditEntry | None:
        """Return the entry with the highest ``seq`` for the stream."""

    @abstractmethod
    def _persist(self, entry: AuditEntry) -> None:
        """Atomically store ``entry``; raise ``AuditConflict`` if (stream, seq) exists."""

    @abstractmethod
    def read_stream(self, agent_stream: str) -> Sequence[AuditEntry]:
        """Return the stream's entries ordered by ``seq``."""


class AnchorSink(ABC):
    """Condition: the chain head is exported outside the store that holds the chain.

    Requirements: AUD-06.
    """

    @abstractmethod
    def publish(self, anchor: Anchor) -> None:
        """Write the head anchor to the external sink."""

    @abstractmethod
    def latest(self, agent_stream: str) -> Anchor | None:
        """Return the most recent anchor for the stream, or None."""
