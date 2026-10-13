"""Audit tamper detection, anchors, export, and reconstruction (AUD-01..06)."""

import json
import sqlite3
import subprocess
import sys
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from arg.core.audit.anchor import (
    FileAnchorSink,
    anchor_head,
    export_jsonl,
    load_jsonl,
    verify_with_sink,
)
from arg.core.audit.builder import content_from_disposition, content_from_rejection
from arg.core.audit.chain import verify_entries
from arg.core.audit.memory import InMemoryAuditStore
from arg.core.audit.sqlite import SqliteAuditStore
from arg.core.models import (
    Anchor,
    AuditConflict,
    AuditEntry,
    Envelope,
    IdentityBinding,
    Mandate,
    Outcome,
)
from arg.core.ports import AuditStore
from tests.core.audit_factories import REC, content
from tests.core.factories import make_envelope
from tests.core.test_engine import ID, MANDATE, ctx, decide, engine


def fill(store: AuditStore, n: int = 4, agent: str = "a-1") -> list[AuditEntry]:
    """Append ``n`` entries."""
    out: list[AuditEntry] = []
    head = None
    for i in range(n):
        e = store.append(content(agent, "auto_execute" if i % 2 else "deny"), head)
        head = e.entry_hash
        out.append(e)
    return out


# ---- tamper: SQLite (row-level, bypassing the append-only triggers like a DB owner) ------
def raw_db(path: Path) -> sqlite3.Connection:
    """Open the file directly and drop the guard triggers (simulates a privileged attacker)."""
    db = sqlite3.connect(path)
    db.executescript("DROP TRIGGER audit_no_update; DROP TRIGGER audit_no_delete;")
    return db


@pytest.fixture
def sq(tmp_path: Path) -> tuple[SqliteAuditStore, Path]:
    """A filled SQLite store and its path."""
    p = tmp_path / "a.db"
    s = SqliteAuditStore(str(p))
    fill(s)
    assert s.verify("a-1").ok
    return s, p


@pytest.mark.req("AUD-02")
def test_triggers_block_update_and_delete(sq: tuple[SqliteAuditStore, Path]) -> None:
    """Ordinary mutation through the store's connection fails."""
    s, _ = sq
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        s._db.execute("UPDATE audit SET body='{}' WHERE seq=1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        s._db.execute("DELETE FROM audit WHERE seq=1")


@pytest.mark.req("AUD-02", "AUD-06")
def test_sqlite_modified_row_detected(sq: tuple[SqliteAuditStore, Path]) -> None:
    """S13: editing a stored entry's content breaks its hash."""
    s, p = sq
    db = raw_db(p)
    body = json.loads(db.execute("SELECT body FROM audit WHERE seq=2").fetchone()[0])
    body["outcome"] = "deny" if body["outcome"] != "deny" else "observe"
    db.execute("UPDATE audit SET body=? WHERE seq=2", (json.dumps(body),))
    db.commit()
    r = s.verify("a-1")
    assert (r.ok, r.code, r.seq) == (False, "AUD_ENTRY_MODIFIED", 2)


@pytest.mark.req("AUD-02", "AUD-06")
def test_sqlite_deleted_row_detected(sq: tuple[SqliteAuditStore, Path]) -> None:
    """S13: removing a middle entry leaves a sequence gap."""
    s, p = sq
    db = raw_db(p)
    db.execute("DELETE FROM audit WHERE seq=2")
    db.commit()
    r = s.verify("a-1")
    assert (r.ok, r.code) == (False, "AUD_SEQ_GAP")


@pytest.mark.req("AUD-02", "AUD-06")
def test_sqlite_reordered_rows_detected(sq: tuple[SqliteAuditStore, Path]) -> None:
    """S13: swapping the seq of two rows breaks hashes and links."""
    s, p = sq
    db = raw_db(p)
    db.execute("UPDATE audit SET seq=99 WHERE seq=2")
    db.execute("UPDATE audit SET seq=2 WHERE seq=3")
    db.execute("UPDATE audit SET seq=3 WHERE seq=99")
    db.commit()
    assert not s.verify("a-1").ok


@pytest.mark.req("AUD-06")
def test_truncated_tail_needs_anchor(sq: tuple[SqliteAuditStore, Path], tmp_path: Path) -> None:
    """Truncation is invisible to the chain alone; the external anchor reveals it."""
    s, p = sq
    sink = FileAnchorSink(tmp_path / "anchors.jsonl")
    anchored = anchor_head(s, sink, "a-1")
    assert anchored is not None and anchored.seq == 4
    db = raw_db(p)
    db.execute("DELETE FROM audit WHERE seq>=3")
    db.commit()
    assert s.verify("a-1").ok  # chain alone cannot see it
    r = verify_with_sink(s, sink, "a-1")
    assert (r.ok, r.code) == (False, "AUD_ANCHOR_MISMATCH")


def test_anchor_detects_rewritten_history(tmp_path: Path) -> None:
    """A fully re-chained stream with different content no longer matches the anchor."""
    honest, forged = InMemoryAuditStore(), InMemoryAuditStore()
    fill(honest)
    sink = FileAnchorSink(tmp_path / "anchors.jsonl")
    anchor_head(honest, sink, "a-1")
    head = None
    for _ in range(4):
        head = forged.append(content("a-1", "auto_execute"), head).entry_hash
    assert forged.verify("a-1").ok
    assert verify_with_sink(forged, sink, "a-1").code == "AUD_ANCHOR_MISMATCH"
    assert verify_with_sink(honest, sink, "a-1").ok


def test_anchor_sink_basics(tmp_path: Path) -> None:
    """Latest anchor wins; unknown streams and missing files yield None; empty stream no-op."""
    sink = FileAnchorSink(tmp_path / "sub" / "anchors.jsonl")
    assert sink.latest("a-1") is None
    store = InMemoryAuditStore()
    assert anchor_head(store, sink, "a-1") is None
    fill(store, 2)
    anchor_head(store, sink, "a-1")
    fill_more = store.append(content("a-1"), store.head("a-1").entry_hash)  # type: ignore[union-attr]
    anchor_head(store, sink, "a-1")
    latest = sink.latest("a-1")
    assert latest is not None and latest.seq == fill_more.seq
    assert sink.latest("other") is None


# ---- tamper: in-memory --------------------------------------------------------------------
@pytest.mark.req("AUD-02")
def test_memory_tampering_detected() -> None:
    """Modified, deleted, and reordered entries in the in-memory store fail verification."""
    for op in ("modify", "delete", "reorder"):
        s = InMemoryAuditStore()
        es = fill(s)
        lst = s._streams["a-1"]
        if op == "modify":
            lst[1] = es[1].model_copy(update={"outcome": "observe"})
        elif op == "delete":
            del lst[1]
        else:
            lst[1], lst[2] = lst[2], lst[1]
        assert not s.verify("a-1").ok, op


def test_verify_stream_mismatch_and_conflict_on_slot() -> None:
    """Foreign-stream entries are flagged; a taken slot raises on direct persist."""
    s = InMemoryAuditStore()
    es = fill(s, 1)
    assert verify_entries(es, "other").code == "AUD_STREAM_MISMATCH"
    with pytest.raises(AuditConflict):
        s._persist(es[0])
    sq = SqliteAuditStore()
    sq_es = fill(sq, 1)
    with pytest.raises(AuditConflict):
        sq._persist(sq_es[0])


# ---- builder, content, reconstruction --------------------------------------------------------
@pytest.mark.req("AUD-01", "AUD-03")
def test_every_outcome_and_rejection_is_recorded_with_required_fields() -> None:
    """Engine decisions and pre-engine rejections both produce complete entries."""
    store = InMemoryAuditStore()
    env = make_envelope()
    timings = {"identity": 0.3, "engine": 2.0}
    # engine decision
    eng, controls = engine()
    c = ctx(20000)
    d = eng.evaluate(c.envelope, c.identity, controls, {}, c.signals, at=c.at, mandate=c.mandate)
    entry = store.append(
        content_from_disposition(
            c.envelope,
            ID,
            d,
            recorded_at=REC,
            policy_version="v1",
            mandate=MANDATE,
            stage_timings_ms=timings,
            escalation_id="esc-1",
        ),
        None,
    )
    assert entry.outcome == "escalate" and entry.decided_at_stage == "engine"
    assert entry.envelope["envelope_id"] == "env-001"
    assert (
        entry.mandate_snapshot is not None and entry.mandate_snapshot["mandate_id"] == "mandate-1"
    )
    assert entry.stage_timings_ms == timings and entry.escalation_id == "esc-1"
    assert {r.control_id for r in entry.rules_applied} >= {"exposure-payment-per-action"}
    assert "EXP_PER_ACTION_EXCEEDED" in entry.basis.controlling
    assert entry.identity_result.status == "confirmed"

    # rejections: identity (unattributed envelope allowed), mandate
    ghost = {"envelope_id": "e-x", "context": {"agent_id": "ghost"}}
    idr = store.append(
        content_from_rejection(ghost, "identity", "IDN_AGENT_UNKNOWN", "ghost", recorded_at=REC),
        None,
    )
    assert (idr.outcome, idr.decided_at_stage, idr.agent_stream) == ("deny", "identity", "ghost")
    assert (
        idr.identity_result.status == "rejected" and idr.identity_result.code == "IDN_AGENT_UNKNOWN"
    )
    garbage = store.append(
        content_from_rejection({"nonsense": True}, "validation", "ENV_SCHEMA", recorded_at=REC),
        None,
    )
    assert garbage.agent_stream == "_unattributed" and garbage.envelope == {"nonsense": True}
    mnd = content_from_rejection(env, "mandate", "MND_EXPIRED", recorded_at=REC, identity=ID)
    assert mnd.identity_result.status == "confirmed" and mnd.basis.controlling == ["MND_EXPIRED"]


@pytest.mark.req("AUD-04", "DSP-07")
def test_decision_reconstructs_from_the_entry_alone() -> None:
    """A reviewer can re-run the decision from the stored entry without the agent's account."""
    eng, controls = engine()
    c = ctx(5000, state={}, signals={"confidence": 0.95, "anomaly_score": 0.9})
    d = eng.evaluate(
        c.envelope, c.identity, controls, c.state, c.signals, at=REC, mandate=c.mandate
    )
    entry = InMemoryAuditStore().append(
        content_from_disposition(
            c.envelope,
            ID,
            d,
            recorded_at=REC,
            policy_version="v1",
            mandate=MANDATE,
            state_snapshot=c.state,
        ),
        None,
    )
    replay = eng.evaluate(
        Envelope.model_validate(entry.envelope),
        IdentityBinding(
            **{
                k: v
                for k, v in entry.identity_result.model_dump().items()
                if k not in {"status", "code", "detail"}
            }
        ),
        controls,
        entry.state_snapshot,
        Envelope.model_validate(entry.envelope).context.signals,
        at=entry.recorded_at,
        mandate=Mandate.model_validate(entry.mandate_snapshot) if entry.mandate_snapshot else None,
    )
    assert replay.outcome.value == entry.outcome
    assert list(replay.controlling_codes) == entry.basis.controlling
    assert Outcome(entry.outcome) is d.outcome


def test_controlling_vs_contributing_reasons() -> None:
    """Risk-profile codes are contributing when a control already forces a stricter outcome."""
    d = decide(20000, signals={"confidence": 0.95, "anomaly_score": 0.9})
    assert d.outcome is Outcome.ESCALATE
    assert "EXP_PER_ACTION_EXCEEDED" in d.controlling_codes
    assert set(d.reason_codes) == set(d.controlling_codes) | set(d.contributing_codes)
    observe_only = decide(5000)
    assert observe_only.controlling_codes == ("RISK_OBSERVE_THRESHOLD",)
    assert observe_only.contributing_codes == ()
    assert decide(500).controlling_codes == ()


# ---- export and offline verify ---------------------------------------------------------------
@pytest.mark.req("AUD-05", "AUD-06")
def test_jsonl_export_roundtrip_and_offline_verify(tmp_path: Path) -> None:
    """Export is one JSON object per line; the verify script accepts it and flags edits."""
    s = InMemoryAuditStore()
    fill(s, 3)
    out = tmp_path / "entries.jsonl"
    assert export_jsonl(s.read_stream("a-1"), out) == 3
    lines = out.read_text().splitlines()
    first = json.loads(lines[0])
    assert {
        "entry_id",
        "seq",
        "prev_hash",
        "entry_hash",
        "outcome",
        "envelope",
        "basis",
        "rules_applied",
        "stage_timings_ms",
        "identity_result",
    } <= first.keys()
    assert load_jsonl(out) == list(s.read_stream("a-1"))

    def run(*args: str) -> int:
        return subprocess.run(
            [sys.executable, "scripts/verify_audit.py", *args], capture_output=True, text=True
        ).returncode

    assert run(str(out)) == 0
    assert run() == 2
    tampered = json.loads(lines[1])
    tampered["outcome"] = "auto_execute" if tampered["outcome"] != "auto_execute" else "deny"
    out.write_text("\n".join([lines[0], json.dumps(tampered), lines[2]]) + "\n")
    assert run(str(out)) == 1
    sink = FileAnchorSink(tmp_path / "anchors.jsonl")
    sink.publish(Anchor(agent_stream="a-1", seq=3, entry_hash="0" * 64))
    out.write_text("\n".join(lines) + "\n")
    assert run(str(out), str(tmp_path / "anchors.jsonl")) == 1


def test_recorded_at_roundtrip_is_stable_through_sqlite(tmp_path: Path) -> None:
    """Timestamps and floats survive storage so recomputed hashes match."""
    s = SqliteAuditStore(str(tmp_path / "t.db"))
    c = content(
        "a-1",
        recorded_at=REC.astimezone(timezone(timedelta(hours=2))),
        stage_timings_ms={"engine": 0.1 + 0.2},
    )
    s.append(c, None)
    assert s.verify("a-1").ok
    assert s.read_stream("a-1")[0].stage_timings_ms["engine"] == 0.1 + 0.2


def test_sample_runtime_config_builds_audit_components(tmp_path: Path) -> None:
    """The composition root can build both stores and the anchor sink by name."""
    from arg.runtime import build_runtime

    for kind, extra in (("memory", {}), ("sqlite", {"path": str(tmp_path / "x.db")})):
        rt = build_runtime(
            {
                "components": {
                    "audit_store": {"type": kind, **extra},
                    "anchor_sink": {"type": "file", "path": str(tmp_path / "an.jsonl")},
                }
            }
        )
        e: Any = rt.components["audit_store"].append(content("a-9"), None)
        assert e.seq == 1
