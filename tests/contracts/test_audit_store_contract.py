"""Contract: every AuditStore is an append-only, chained, verifiable log (AUD-01..06)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from arg.core.audit.memory import InMemoryAuditStore
from arg.core.audit.sqlite import SqliteAuditStore
from arg.core.models import GENESIS_HASH, AuditConflict
from arg.core.ports import AuditStore
from tests.core.audit_factories import content

BASE = AuditStore

BUILDERS: dict[type, Callable[[Path], AuditStore]] = {
    InMemoryAuditStore: lambda tmp: InMemoryAuditStore(),
    SqliteAuditStore: lambda tmp: SqliteAuditStore(str(tmp / "audit.db")),
}


@pytest.fixture
def store(component_cls: Any, tmp_path: Path) -> AuditStore:
    """A fresh store of the implementation under test."""
    assert component_cls in BUILDERS, "add a builder for the new implementation"
    return BUILDERS[component_cls](tmp_path)


@pytest.mark.req("AUD-02", "AUD-06")
def test_entries_chain_from_genesis_and_verify(store: AuditStore) -> None:
    """Each entry links to its predecessor; the stream verifies."""
    e1 = store.append(content("a-1", "auto_execute"), None)
    e2 = store.append(content("a-1", "deny"), e1.entry_hash)
    assert (e1.seq, e1.prev_hash) == (1, GENESIS_HASH)
    assert (e2.seq, e2.prev_hash) == (2, e1.entry_hash)
    assert store.head("a-1") == e2
    assert [e.seq for e in store.read_stream("a-1")] == [1, 2]
    assert store.verify("a-1").ok


@pytest.mark.req("AUD-02")
def test_stale_expected_head_is_refused(store: AuditStore) -> None:
    """Appending against a stale head raises; nothing is written."""
    e1 = store.append(content("a-1", "auto_execute"), None)
    with pytest.raises(AuditConflict):
        store.append(content("a-1", "deny"), None)
    with pytest.raises(AuditConflict):
        store.append(content("a-1", "deny"), "f" * 64)
    assert store.head("a-1") == e1


def test_streams_are_independent_and_empty_stream_verifies(store: AuditStore) -> None:
    """Per-agent chains do not interact."""
    store.append(content("a-1", "deny"), None)
    other = store.append(content("a-2", "observe"), None)
    assert other.seq == 1 and other.prev_hash == GENESIS_HASH
    assert store.head("nobody") is None
    assert store.verify("nobody").ok and store.verify("nobody").checked == 0
