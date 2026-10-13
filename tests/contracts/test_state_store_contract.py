"""Contract: every StateStore is atomic for counters, tokens, decisions, escalations."""

import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from arg.core.models import EscalationRecord, EscalationState
from arg.core.ports import StateStore
from arg.core.state.memory import InMemoryStateStore
from arg.core.state.sqlite import SqliteStateStore
from tests.core.factories import T0

BASE = StateStore

BUILDERS: dict[type, Callable[[Path], StateStore]] = {
    InMemoryStateStore: lambda tmp: InMemoryStateStore(),
    SqliteStateStore: lambda tmp: SqliteStateStore(str(tmp / "state.db")),
}


@pytest.fixture
def store(component_cls: Any, tmp_path: Path) -> StateStore:
    """A fresh store of the implementation under test."""
    assert component_cls in BUILDERS, "add a builder for the new implementation"
    return BUILDERS[component_cls](tmp_path)


def esc(i: int, queue: str = "q", deadline_s: int = 60, **kw: Any) -> EscalationRecord:
    """An escalation record."""
    base: dict[str, Any] = {
        "escalation_id": f"esc-{i}",
        "decision_id": f"d-{i}",
        "envelope_id": f"env-{i}",
        "agent_stream": "a-1",
        "queue": queue,
        "reviewer_role": "r",
        "on_timeout": "block",
        "timeout_seconds": 60,
        "opened_at": T0,
        "deadline": T0 + timedelta(seconds=deadline_s),
        "envelope": {},
        "identity": {},
    }
    base.update(kw)
    return EscalationRecord(**base)


@pytest.mark.req("CTL-05")
def test_reserve_respects_limit_and_window(store: StateStore) -> None:
    """Counters accumulate to the limit, refuse beyond it, and reset in the next window."""
    assert store.reserve("k", 600, 1000, 3600, T0)
    assert store.reserve("k", 400, 1000, 3600, T0)
    assert not store.reserve("k", 0.01, 1000, 3600, T0)
    assert store.usage("k", 3600, T0) == 1000
    assert store.reserve("k", 1000, 1000, 3600, T0 + timedelta(hours=1))  # next fixed window
    assert store.usage("other", 3600, T0) == 0


def test_release_and_unconditional_reserve(store: StateStore) -> None:
    """Release returns capacity (never below zero); limit=None adds past the limit."""
    store.reserve("k", 800, 1000, 60, T0)
    store.release("k", 500, 60, T0)
    assert store.usage("k", 60, T0) == 300
    store.release("k", 9999, 60, T0)
    assert store.usage("k", 60, T0) == 0
    assert store.reserve("k", 5000, None, 60, T0)
    assert store.usage("k", 60, T0) == 5000


def test_reserve_validates_input(store: StateStore) -> None:
    """Template method: bad inputs are refused before reaching the implementation."""
    for bad in [("", 1, 10, 60), ("k", -1, 10, 60), ("k", float("nan"), 10, 60), ("k", 1, 10, 0)]:
        with pytest.raises(ValueError):
            store.reserve(bad[0], bad[1], bad[2], bad[3], T0)


def test_reserve_is_atomic_under_concurrency(store: StateStore) -> None:
    """50 concurrent reservations of 1 against limit 20: exactly 20 succeed."""
    results: list[bool] = []

    def worker() -> None:
        results.append(store.reserve("k", 1, 20, 3600, T0))

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 20
    assert store.usage("k", 3600, T0) == 20


@pytest.mark.req("INT-04")
def test_token_consumed_once(store: StateStore) -> None:
    """Second consumption of a jti fails."""
    assert store.consume_token("jti-1")
    assert not store.consume_token("jti-1")
    assert store.consume_token("jti-2")


@pytest.mark.req("ENV-06")
def test_first_decision_wins(store: StateStore) -> None:
    """put_decision is idempotent: later payloads do not replace the first."""
    assert store.get_decision("e-1") is None
    assert store.put_decision("e-1", "first") == "first"
    assert store.put_decision("e-1", "second") == "first"
    assert store.get_decision("e-1") == "first"


@pytest.mark.req("ESC-06")
def test_escalation_cap_per_queue(store: StateStore) -> None:
    """The cap counts PENDING records of one queue only; duplicates are refused."""
    assert store.create_escalation(esc(1), cap=2)
    assert store.create_escalation(esc(2), cap=2)
    assert not store.create_escalation(esc(3), cap=2)
    assert store.create_escalation(esc(4, queue="other"), cap=2)
    assert not store.create_escalation(esc(1, queue="other"), cap=None)  # duplicate id
    done = esc(1).model_copy(update={"state": EscalationState.DECLINED})
    assert store.transition_escalation("esc-1", EscalationState.PENDING, done)
    assert store.create_escalation(esc(5), cap=2)  # capacity freed


def test_transition_is_compare_and_set_and_listing_ordered(store: StateStore) -> None:
    """A stale expected state is refused; listing orders by deadline."""
    store.create_escalation(esc(1, deadline_s=300), None)
    store.create_escalation(esc(2, deadline_s=30), None)
    assert [r.escalation_id for r in store.list_escalations(EscalationState.PENDING)] == [
        "esc-2",
        "esc-1",
    ]
    approved = esc(1, deadline_s=300).model_copy(update={"state": EscalationState.APPROVED})
    assert store.transition_escalation("esc-1", EscalationState.PENDING, approved)
    assert not store.transition_escalation("esc-1", EscalationState.PENDING, approved)
    assert not store.transition_escalation("missing", EscalationState.PENDING, approved)
    got = store.get_escalation("esc-1")
    assert got is not None and got.state is EscalationState.APPROVED
    assert store.get_escalation("nope") is None
    assert store.list_escalations(EscalationState.PENDING, queue="nope") == []
    assert [r.escalation_id for r in store.list_escalations(EscalationState.APPROVED)] == ["esc-1"]
