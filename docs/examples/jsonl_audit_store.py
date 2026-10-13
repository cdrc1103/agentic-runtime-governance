"""Worked example 2 (docs/extending.md): a custom ``AuditStore``.

Appends one JSON line per entry to a file. Because ``AuditStore.append`` is a template
method, this class cannot skip the hash chain or the expected-head check: it supplies only
persistence. Not concurrency-safe across processes; a reference, not a recommendation.
"""

from collections.abc import Sequence
from pathlib import Path

from arg.core.models import AuditConflict, AuditEntry
from arg.core.ports import AuditStore
from arg.core.registry import register


@register(AuditStore, "jsonl")
class JsonlAuditStore(AuditStore):
    """One file, one line per entry, all streams interleaved."""

    def __init__(self, path: str | Path) -> None:
        """Use ``path`` (created on first write)."""
        self.path = Path(path)

    def _all(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        return [AuditEntry.model_validate_json(x) for x in self.path.read_text().splitlines() if x]

    def read_stream(self, agent_stream: str) -> Sequence[AuditEntry]:
        """Entries of one stream ordered by sequence."""
        return sorted(
            (e for e in self._all() if e.agent_stream == agent_stream), key=lambda e: e.seq
        )

    def _read_head(self, agent_stream: str) -> AuditEntry | None:
        stream = self.read_stream(agent_stream)
        return stream[-1] if stream else None

    def _persist(self, entry: AuditEntry) -> None:
        head = self._read_head(entry.agent_stream)
        if (head.seq if head else 0) + 1 != entry.seq:
            raise AuditConflict(f"{entry.agent_stream}: seq {entry.seq} is not next")
        with self.path.open("a") as fh:
            fh.write(entry.model_dump_json() + "\n")
