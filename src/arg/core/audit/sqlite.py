"""SQLite audit store (local persistence).

Triggers reject UPDATE and DELETE so accidental mutation fails loudly. They are not a
security boundary (whoever owns the file can drop them); the hash chain and external anchor
are what make tampering evident (AUD-02).
"""

import sqlite3
import threading
from collections.abc import Sequence

from arg.core.models import AuditConflict, AuditEntry
from arg.core.ports import AuditStore
from arg.core.registry import register

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    agent_stream TEXT NOT NULL,
    seq INTEGER NOT NULL,
    entry_hash TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (agent_stream, seq)
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


@register(AuditStore, "sqlite")
class SqliteAuditStore(AuditStore):
    """One row per entry, keyed by (stream, seq); the primary key resolves append races."""

    def __init__(self, path: str = ":memory:") -> None:
        """Open (and create if needed) the database at ``path``."""
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def _read_head(self, agent_stream: str) -> AuditEntry | None:
        with self._lock:
            row = self._db.execute(
                "SELECT body FROM audit WHERE agent_stream=? ORDER BY seq DESC LIMIT 1",
                (agent_stream,),
            ).fetchone()
        return AuditEntry.model_validate_json(row[0]) if row else None

    def _persist(self, entry: AuditEntry) -> None:
        try:
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO audit (agent_stream, seq, entry_hash, body) VALUES (?,?,?,?)",
                    (entry.agent_stream, entry.seq, entry.entry_hash, entry.model_dump_json()),
                )
        except sqlite3.IntegrityError as exc:
            raise AuditConflict(f"{entry.agent_stream}: seq {entry.seq} taken") from exc

    def read_stream(self, agent_stream: str) -> Sequence[AuditEntry]:
        """Return the stream's entries ordered by ``seq``."""
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM audit WHERE agent_stream=? ORDER BY seq", (agent_stream,)
            ).fetchall()
        return [AuditEntry.model_validate_json(r[0]) for r in rows]
