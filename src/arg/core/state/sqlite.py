"""SQLite state store (local persistence)."""

import sqlite3
import threading

from arg.core.models import EscalationRecord, EscalationState
from arg.core.ports import StateStore
from arg.core.registry import register

_SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
    key TEXT NOT NULL, window_s INTEGER NOT NULL, window INTEGER NOT NULL,
    total REAL NOT NULL, PRIMARY KEY (key, window_s, window));
CREATE TABLE IF NOT EXISTS tokens (jti TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS decisions (envelope_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS escalations (
    escalation_id TEXT PRIMARY KEY, queue TEXT NOT NULL, state TEXT NOT NULL,
    deadline TEXT NOT NULL, body TEXT NOT NULL);
"""


@register(StateStore, "sqlite")
class SqliteStateStore(StateStore):
    """Each operation runs in one transaction under a process-wide lock."""

    def __init__(self, path: str = ":memory:") -> None:
        """Open (and create if needed) the database at ``path``."""
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def _add(self, key: str, window: int, window_s: int, delta: float, limit: float | None) -> bool:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT total FROM counters WHERE key=? AND window_s=? AND window=?",
                (key, window_s, window),
            ).fetchone()
            new = (row[0] if row else 0.0) + delta
            if limit is not None and delta > 0 and new > limit:
                return False
            self._db.execute(
                "INSERT INTO counters (key, window_s, window, total) VALUES (?,?,?,?) "
                "ON CONFLICT(key, window_s, window) DO UPDATE SET total=excluded.total",
                (key, window_s, window, max(new, 0.0)),
            )
            return True

    def _usage(self, key: str, window: int, window_s: int) -> float:
        with self._lock:
            row = self._db.execute(
                "SELECT total FROM counters WHERE key=? AND window_s=? AND window=?",
                (key, window_s, window),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def consume_token(self, jti: str) -> bool:
        """Insert-or-fail on the primary key."""
        try:
            with self._lock, self._db:
                self._db.execute("INSERT INTO tokens (jti) VALUES (?)", (jti,))
        except sqlite3.IntegrityError:
            return False
        return True

    def put_decision(self, envelope_id: str, payload: str) -> str:
        """First writer wins."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO decisions (envelope_id, payload) VALUES (?,?)",
                (envelope_id, payload),
            )
            return str(
                self._db.execute(
                    "SELECT payload FROM decisions WHERE envelope_id=?", (envelope_id,)
                ).fetchone()[0]
            )

    def get_decision(self, envelope_id: str) -> str | None:
        """Return stored payload."""
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM decisions WHERE envelope_id=?", (envelope_id,)
            ).fetchone()
        return str(row[0]) if row else None

    def create_escalation(self, record: EscalationRecord, cap: int | None) -> bool:
        """Insert unless the queue is at capacity or the id exists."""
        with self._lock, self._db:
            if cap is not None:
                pending = self._db.execute(
                    "SELECT COUNT(*) FROM escalations WHERE queue=? AND state=?",
                    (record.queue, EscalationState.PENDING.value),
                ).fetchone()[0]
                if pending >= cap:
                    return False
            cur = self._db.execute(
                "INSERT OR IGNORE INTO escalations VALUES (?,?,?,?,?)",
                (
                    record.escalation_id,
                    record.queue,
                    record.state.value,
                    record.deadline.isoformat(),
                    record.model_dump_json(),
                ),
            )
            return cur.rowcount == 1

    def get_escalation(self, escalation_id: str) -> EscalationRecord | None:
        """Return the record."""
        with self._lock:
            row = self._db.execute(
                "SELECT body FROM escalations WHERE escalation_id=?", (escalation_id,)
            ).fetchone()
        return EscalationRecord.model_validate_json(row[0]) if row else None

    def transition_escalation(
        self, escalation_id: str, expected: EscalationState, record: EscalationRecord
    ) -> bool:
        """Compare-and-set on state via a conditional UPDATE."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE escalations SET state=?, deadline=?, body=? "
                "WHERE escalation_id=? AND state=?",
                (
                    record.state.value,
                    record.deadline.isoformat(),
                    record.model_dump_json(),
                    escalation_id,
                    expected.value,
                ),
            )
            return cur.rowcount == 1

    def list_escalations(
        self, state: EscalationState, queue: str | None = None
    ) -> list[EscalationRecord]:
        """Records in ``state``, ordered by deadline then id (ISO strings sort correctly)."""
        sql = "SELECT body FROM escalations WHERE state=?"
        args: list[str] = [state.value]
        if queue is not None:
            sql += " AND queue=?"
            args.append(queue)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        rs = [EscalationRecord.model_validate_json(r[0]) for r in rows]
        return sorted(rs, key=lambda r: (r.deadline, r.escalation_id))
