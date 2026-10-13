"""Human escalation: timeouts, authority, cap, approve/decline/modify (S06, S07, S15, S24)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from arg.core.models import EscalationError, EscalationState
from tests.core.factories import T0
from tests.service.world import World, build_world

AGG_KEY = "exposure-payment-aggregate:principal:alice.example"


@pytest.fixture
def w(tmp_path: Path) -> World:
    """In-memory world."""
    return build_world(tmp_path)


def escalate(w: World, amount: float = 20000) -> str:
    """Submit an escalating payment; return the escalation id."""
    r = w.decide(amount)
    assert r.outcome == "escalate" and r.escalation_id
    return r.escalation_id


def refused(w: World, *args: Any, **kw: Any) -> str:
    """Return the code of the EscalationError a resolution raises."""
    with pytest.raises(EscalationError) as ei:
        w.svc.resolve_escalation(*args, **kw)
    return ei.value.code


@pytest.mark.req("ESC-03")
def test_s06_timeout_blocks_and_is_logged(w: World) -> None:
    """S06: no decision before the deadline: TIMED_OUT (blocked), audited; late reviews refused."""
    esc_id = escalate(w)
    assert w.svc.sweep() == []  # not overdue yet
    w.clock.advance(seconds=901)
    [done] = w.svc.sweep()
    assert done.state is EscalationState.TIMED_OUT
    last = w.audit()[-1]
    assert (last.decided_at_stage, last.outcome, last.basis.controlling) == (
        "reviewer",
        "deny",
        ["ESC_TIMEOUT_BLOCKED"],
    )
    assert refused(w, esc_id, "rita.reviewer", "approve") == "ESC_NOT_PENDING"


@pytest.mark.req("ESC-03")
def test_timeout_default_senior_reassigns_once_then_blocks(tmp_path: Path) -> None:
    """on_timeout=senior hands the item to a senior reviewer, then blocks if still unreviewed."""
    import shutil

    import yaml

    bundle = tmp_path / "bundle"
    shutil.copytree("config/bundle", bundle)
    f = bundle / "controls" / "exposure-payment-per-action.yaml"
    d = yaml.safe_load(f.read_text())
    d["escalation"]["on_timeout"] = "senior"
    f.write_text(yaml.safe_dump(d))
    w = build_world(tmp_path, controls_path=bundle)
    esc_id = escalate(w)
    w.clock.advance(seconds=901)
    [moved] = w.svc.sweep()
    assert moved.state is EscalationState.PENDING and moved.escalated_to_senior
    assert w.audit()[-1].basis.controlling == ["ESC_TIMEOUT_REASSIGNED_SENIOR"]
    assert refused(w, esc_id, "rita.reviewer", "approve") == "ESC_ROLE_MISMATCH"
    w.clock.advance(seconds=901)
    [blocked] = w.svc.sweep()
    assert blocked.state is EscalationState.TIMED_OUT


@pytest.mark.req("ESC-04")
def test_s07_reviewer_without_authority_refused_and_logged(w: World) -> None:
    """S07: unknown reviewer, wrong role, and over-limit reviewers cannot resolve; all logged."""
    esc_id = escalate(w, 20000)
    before = len(w.audit())
    assert refused(w, esc_id, "nobody", "approve") == "ESC_REVIEWER_UNKNOWN"
    assert refused(w, esc_id, "ivan.intern", "approve") == "ESC_AUTHORITY_EXCEEDED"
    assert w.svc.queue.get(esc_id).state is EscalationState.PENDING  # type: ignore[union-attr]
    refusals = w.audit()[before:]
    assert [e.basis.controlling for e in refusals] == [
        ["ESC_REVIEWER_UNKNOWN"],
        ["ESC_AUTHORITY_EXCEEDED"],
    ]
    assert refusals[1].reviewer_decision == {
        "action": "approve",
        "reviewer_id": "ivan.intern",
        "status": "refused",
    }
    assert refused(w, "esc-missing", "rita.reviewer", "approve") == "ESC_NOT_FOUND"


@pytest.mark.req("ESC-04")
def test_authorised_reviewer_approval_carries_weight(w: World) -> None:
    """Approval resolves the item, applies the held reservations, and is audited."""
    w.decide(100)  # counters exist
    esc_id = escalate(w, 20000)
    store = w.rt.components["state_store"]
    assert store.usage(AGG_KEY, 3600, T0) == 100
    res = w.svc.resolve_escalation(esc_id, "rita.reviewer", "approve", note="verified by phone")
    assert res.escalation.state is EscalationState.APPROVED and res.child is None
    assert store.usage(AGG_KEY, 3600, T0) == 20100  # forced past the limit: reviewer authority
    last = w.audit()[-1]
    assert (last.outcome, last.decided_at_stage, last.escalation_id) == (
        "auto_execute",
        "reviewer",
        esc_id,
    )
    assert last.reviewer_decision == {
        "action": "approve",
        "reviewer_id": "rita.reviewer",
        "note": "verified by phone",
    }
    assert refused(w, esc_id, "rita.reviewer", "decline") == "ESC_NOT_PENDING"


def test_decline_and_expired_review(w: World) -> None:
    """Decline blocks; a review after the deadline (before the sweeper ran) is refused."""
    a = escalate(w)
    res = w.svc.resolve_escalation(a, "rita.reviewer", "decline")
    assert res.escalation.state is EscalationState.DECLINED
    assert w.audit()[-1].outcome == "deny"
    b = escalate(w)
    w.clock.advance(seconds=1000)
    assert refused(w, b, "rita.reviewer", "approve") == "ESC_EXPIRED"


@pytest.mark.req("ESC-02", "ESC-06")
def test_s15_open_escalation_cap_blocks_new_ones(tmp_path: Path) -> None:
    """S15: beyond the cap new escalations are denied and logged; depth is observable."""
    w = build_world(tmp_path, max_open=2)
    assert w.decide(20000).outcome == "escalate"
    assert w.decide(20000).outcome == "escalate"
    third = w.decide(20000)
    assert (third.outcome, third.reason_codes[0]) == ("deny", "ESC_QUEUE_FULL")
    assert third.escalation_id is None
    assert w.svc.queue.depth("treasury-review") == 2
    assert w.audit()[-1].basis.controlling == ["ESC_QUEUE_FULL"]


@pytest.mark.req("ESC-05")
def test_s24_modify_reenters_pipeline_with_parent_link(w: World) -> None:
    """S24: 'modify' ends the original and evaluates a new envelope that links to it."""
    esc_id = escalate(w, 20000)
    res = w.svc.resolve_escalation(
        esc_id, "rita.reviewer", "modify", modified_parameters={"amount": 400}, note="reduced"
    )
    assert res.escalation.state is EscalationState.MODIFIED
    assert res.child is not None and res.child.outcome == "auto_execute"
    child_entry = w.audit()[-1]
    assert child_entry.envelope["action"]["parent_envelope_id"] == "env-0001"
    assert child_entry.envelope["envelope_id"] == "env-0001-m1"
    assert child_entry.envelope["action"]["parameters"]["amount"] == 400
    assert child_entry.identity_result.origin == "reviewer"
    reviewer_entry = w.audit()[-2]
    assert reviewer_entry.decided_at_stage == "reviewer" and reviewer_entry.outcome == "deny"
    assert reviewer_entry.reviewer_decision["child_envelope_id"] == "env-0001-m1"
    # the child is subject to the same controls: a still-too-large modification escalates again
    big = escalate(w, 20000)
    again = w.svc.resolve_escalation(
        big, "rita.reviewer", "modify", modified_parameters={"amount": 15000}
    )
    assert again.child is not None and again.child.outcome == "escalate"


@pytest.mark.req("ESC-05", "ESC-04")
def test_modify_beyond_reviewer_authority_refused(w: World) -> None:
    """A reviewer cannot modify an action to an amount above their authority."""
    esc_id = escalate(w, 20000)
    code = refused(w, esc_id, "rita.reviewer", "modify", modified_parameters={"amount": 90000})
    assert code == "ESC_AUTHORITY_EXCEEDED"


def test_audit_chain_stays_valid_across_reviewer_activity(w: World) -> None:
    """Reviewer entries are ordinary chained entries in the agent's stream."""
    esc_id = escalate(w)
    w.svc.resolve_escalation(esc_id, "rita.reviewer", "approve")
    w.clock.advance(seconds=5)
    assert w.rt.components["audit_store"].verify("treasury-agent-1").ok
    assert timedelta(0) < w.clock.now - T0
