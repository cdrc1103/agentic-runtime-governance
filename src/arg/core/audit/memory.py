"""In-memory audit store (tests, demo)."""

import threading
from collections import defaultdict
from collections.abc import Sequence

from arg.core.models import AuditConflict, AuditContent, AuditEntry
from arg.core.ports import AuditStore
from arg.core.registry import register


@register(AuditStore, "memory")
class InMemoryAuditStore(AuditStore):
    """Entries kept per stream in lists; a lock makes append atomic."""

    def __init__(self) -> None:
        """Create an empty store."""
        self._streams: dict[str, list[AuditEntry]] = defaultdict(list)
        self._lock = threading.Lock()

    def append(self, content: AuditContent, expected_head: str | None) -> AuditEntry:
        """Serialise head-check and persist (template method inherited)."""
        with self._lock:
            return super().append(content, expected_head)

    def _read_head(self, agent_stream: str) -> AuditEntry | None:
        entries = self._streams.get(agent_stream)
        return entries[-1] if entries else None

    def _persist(self, entry: AuditEntry) -> None:
        entries = self._streams[entry.agent_stream]
        if len(entries) + 1 != entry.seq:
            raise AuditConflict(f"{entry.agent_stream}: seq {entry.seq} not next")
        entries.append(entry)

    def read_stream(self, agent_stream: str) -> Sequence[AuditEntry]:
        """Return a copy of the stream."""
        return list(self._streams.get(agent_stream, []))
