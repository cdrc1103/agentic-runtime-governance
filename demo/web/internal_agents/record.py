"""Record the internal-agents scenarios on the real engine and build the page.

Each scenario runs on a fresh in-process runtime (SQLite in a temp dir) over the bank's
fictional agents. The page replays these recordings and decides nothing itself.

Run: ``uv run python -m scripts.gen_demos``. Not regulatory guidance; demo only.
"""

import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from arg.core.models import AgentStatus
from arg.runtime import ROLES
from demo.web.internal_agents import detail as dt
from demo.web.internal_agents import followups as fu
from demo.web.internal_agents.story import SCENARIOS, TOOLS
from demo.web.internal_agents.trace import Decision, Session, component
from demo.web.internal_agents.view import Film, row
from demo.web.internal_agents.world import TOKENS, World, build_world

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
PAGE = ROOT / "docs" / "demo" / "internal-agents" / "index.html"
MARK = re.compile(r"(/\*DATA_START\*/).*?(/\*DATA_END\*/)", re.S)

THREE_WAY = [("retrieval", "read_invoice"), ("check", "po_match"), ("check", "goods_receipt_match")]
Scenario = tuple[list[dict[str, Any]], list[Decision]]


def fresh(sid: str) -> tuple[World, Session, Film]:
    """A new world, a recording session over it and an empty film for ``sid``."""
    world = build_world(Path(tempfile.mkdtemp(prefix="arg-internal-")))
    return world, Session(world), Film(world, sid)


def run_token(w: World, f: Film, d: Decision, text: str = "Accepted") -> None:
    """The bank system redeems the decision token for the exact action."""
    tok = fu.token_beat(w, d)
    ex = fu.execute_beat(w, fu.redeem(w, d, d.body["token"]), d, title="", plain="")
    f.accept([tok, ex], "Bank system accepts", "One-time token, exact action only.", text=text)


def s_invoice() -> Scenario:
    """P2P: matched invoice, Allow automatically, then an altered amount is refused."""
    w, s, f = fresh("p2p-invoice")
    d = s.propose(
        "p2p-invoice-agent-1",
        "invoice.approve",
        {"amount": 8400, "currency": "USD", "invoice_id": "INV-20417", "supplier_id": "SUP-0042"},
        envelope_id="inv-1",
        scope="ap:invoice:INV-20417",
        trace=THREE_WAY,
        confidence=0.93,
    )
    f.flow(d, rego=True)
    tampered = fu.redeem(w, d, d.body["token"], amount=84000)
    ex = fu.execute_beat(w, tampered, d, title="", plain="")
    f.refuse(
        [fu.token_beat(w, d), ex],
        "Amount changed to 84,000: refused",
        "The token only fits 8,400.",
        ptext="Approve invoice \u00b7 84,000",
    )
    run_token(w, f, d)
    return f.beats, [d]


def s_payment() -> Scenario:
    """P2P: payment over the mandate limit is held, then a reviewer with authority approves."""
    w, s, f = fresh("p2p-payment")
    d = s.propose(
        "p2p-payment-agent-1",
        "supplier_payment.release",
        {"amount": 32000, "currency": "USD", "invoice_id": "INV-20398", "supplier_id": "SUP-0042"},
        envelope_id="pay-1",
        scope="ap:supplier:SUP-0042",
        trace=THREE_WAY,
    )
    f.flow(d, rego=True)
    f.hold(
        [fu.escalation_beat(w, d)], "Held for a person", "Nothing runs until a reviewer decides."
    )
    b, resp = fu.review_beat(
        w, d, "ap-1", {"action": "approve", "note": "supplier call-back done"}, title="", plain=""
    )
    f.reviewed(
        True,
        [b],
        "Reviewer approves",
        "Right role, enough authority. Note recorded.",
        "Reviewer, limit 100,000",
    )
    ex = fu.execute_beat(w, fu.redeem(w, d, resp["token"]), d, title="", plain="")
    f.accept([ex], "Bank system accepts", "Token fits exactly this payment.")
    return f.beats, [d]


def s_bank_change() -> Scenario:
    """P2P: supplier master-data change is not a permitted action for payment agents."""
    w, s, f = fresh("p2p-bank-change")
    d = s.propose(
        "p2p-payment-agent-1",
        "supplier.bank_details.change",
        {"supplier_id": "SUP-0042", "new_account_ref": "acct-ref-9931"},
        envelope_id="bank-1",
        scope="ap:supplier:SUP-0042",
        trace=[("retrieval", "read_inbound_email"), ("tool_call", "draft_supplier_update")],
    )
    f.flow(d)
    f.blocked([fu.blocked_beat(w, d)], "Nothing reaches the bank system", "No token, no action.")
    return f.beats, [d]


def s_billing() -> Scenario:
    """O2C: routine fee invoice, Allow automatically."""
    w, s, f = fresh("o2c-billing")
    d = s.propose(
        "o2c-billing-agent-1",
        "fee_invoice.issue",
        {"amount": 1250, "currency": "USD", "customer_ref": "CUST-5510", "fee": "account"},
        envelope_id="fee-1",
        scope="ar:customer:CUST-5510",
        trace=[("retrieval", "read_fee_schedule"), ("check", "fee_schedule_match")],
    )
    f.flow(d)
    run_token(w, f, d)
    return f.beats, [d]


def s_writeoff() -> Scenario:
    """O2C: three write-offs; the daily running total decides the third."""
    w, s, f = fresh("o2c-writeoff")
    decisions: list[Decision] = []
    for i, amount in enumerate((1800, 2000, 1500)):
        d = s.propose(
            "o2c-collections-agent-1",
            "receivable.write_off",
            {"amount": amount, "currency": "USD", "receivable_ref": f"RCV-{3300 + i}"},
            envelope_id=f"wo-{i}",
            scope=f"ar:receivable:RCV-{3300 + i}",
            trace=[("retrieval", "read_receivable"), ("check", "dormancy_check")],
        )
        decisions.append(d)
        f.flow(
            d, act=f"Write-off {i + 1} of 3", lead=f"Write-off {i + 1} of 3 today.", compact=i > 0
        )
        if d.entry.outcome == "escalate":
            f.hold(
                [fu.escalation_beat(w, d, f.act)],
                "Held for a person",
                "The daily cap would be passed.",
            )
        else:
            run_token(w, f, d, "Accepted, watched")
    return f.beats, decisions


def s_journal() -> Scenario:
    """R2R: routine journal, Allow with monitoring."""
    w, s, f = fresh("r2r-journal")
    d = s.propose(
        "r2r-recon-agent-1",
        "journal.post",
        {"amount": 48000, "currency": "USD", "ledger": "GL-1200", "period": "2026-02"},
        envelope_id="jrn-1",
        scope="gl:GL-1200",
        trace=[("retrieval", "read_bank_statement"), ("check", "reconciliation_match")],
    )
    f.flow(d)
    run_token(w, f, d, "Accepted, watched")
    return f.beats, [d]


def s_closed_period() -> Scenario:
    """R2R: posting to a closed period is not a permitted action."""
    w, s, f = fresh("r2r-closed-period")
    d = s.propose(
        "r2r-recon-agent-1",
        "journal.post_closed_period",
        {"amount": 12000, "currency": "USD", "ledger": "GL-1200", "period": "2025-12"},
        envelope_id="jrn-2",
        scope="gl:GL-1200",
        trace=[("retrieval", "read_bank_statement"), ("check", "reconciliation_match")],
    )
    f.flow(d)
    f.blocked([fu.blocked_beat(w, d)], "Nothing reaches the ledger", "No token, no posting.")
    return f.beats, [d]


def s_adjustment() -> Scenario:
    """R2R: low-confidence manual adjustment is held; the controller declines."""
    w, s, f = fresh("r2r-adjustment")
    d = s.propose(
        "r2r-recon-agent-1",
        "journal.adjust",
        {"amount": 12000, "currency": "USD", "ledger": "GL-1200", "period": "2026-02"},
        envelope_id="adj-1",
        scope="gl:GL-1200",
        trace=[("retrieval", "read_gl_balance"), ("check", "variance_analysis")],
        confidence=0.55,
    )
    f.flow(d)
    f.hold(
        [fu.escalation_beat(w, d)], "Held for the controller", "The agent's doubt needs a person."
    )
    b, _ = fu.review_beat(
        w,
        d,
        "controller",
        {"action": "decline", "note": "no supporting document"},
        title="",
        plain="",
    )
    f.reviewed(False, [b], "Controller declines", "No token, nothing runs.", "Controller")
    return f.beats, [d]


def s_kill_switch() -> Scenario:
    """All: suspend an agent, then lose a dependency; both end in Deny."""
    w, s, f = fresh("kill-switch")
    agent = "o2c-billing-agent-1"
    params = {"amount": 1250, "currency": "USD", "customer_ref": "CUST-5510", "fee": "account"}
    kw: dict[str, Any] = {
        "scope": "ar:customer:CUST-5510",
        "trace": [("retrieval", "read_fee_schedule"), ("check", "fee_schedule_match")],
    }
    d1 = s.propose(agent, "fee_invoice.issue", params, envelope_id="ks-1", **kw)
    f.flow(d1, act="A normal day", lead="A routine fee invoice.", compact=True)
    run_token(w, f, d1)
    registry = w.runtime.components["agent_registry"]
    registry._by_id[agent] = registry._by_id[agent].model_copy(
        update={"status": AgentStatus.SUSPENDED}
    )
    data = yaml.safe_load(w.registry_file.read_text())
    for rec in data["agents"]:
        if rec["agent_id"] == agent:
            rec["status"] = "suspended"
    w.registry_file.write_text(yaml.safe_dump(data, sort_keys=False))
    f.act = "Kill switch"
    rows = [
        row("Agent is registered", "ok"),
        row("Agent is active", "fail", "suspended in the register"),
    ]
    detail = dt.beat(
        "identity",
        w,
        title="Agent register",
        plain="",
        tech="Registry status is read on every decision. Here the file register is edited; a "
        "production register would be a live identity service.",
        artifacts=[dt.art("Register entry (YAML)", "yaml", dt._registry_record(w, agent))],
    )
    f.custom(
        "kill", "The bank suspends the agent", "One change in the register. Effective at once.",
        box="1", rows=rows, state="stop", tool=TOOLS["identity"], ref=[detail],
    )  # fmt: skip
    d2 = s.propose(agent, "fee_invoice.issue", params, envelope_id="ks-2", **kw)
    f.flow(d2, act="Kill switch", lead="The same request, after the suspension.", compact=True)
    f.blocked(
        [fu.blocked_beat(w, d2, "Kill switch")],
        "Nothing reaches the bank system",
        "No token, no action.",
    )
    store = w.runtime.components["state_store"]
    original = store.usage

    def unreachable(*_a: Any, **_k: Any) -> float:
        raise ConnectionError("state store unreachable")

    store.usage = unreachable
    d3 = s.propose(
        "o2c-collections-agent-1",
        "receivable.write_off",
        {"amount": 900, "currency": "USD", "receivable_ref": "RCV-3390"},
        envelope_id="ks-3",
        scope="ar:receivable:RCV-3390",
        trace=[("retrieval", "read_receivable"), ("check", "dormancy_check")],
    )
    store.usage = original
    outage = dt.beat(
        "evaluate",
        w,
        title="Failure injected for the recording",
        plain="",
        tech="Any exception on the decision path becomes Deny (SYSTEM_ERROR), and the attempt is "
        "still written to the audit log.",
        artifacts=[dt.art("Injected failure", "text", "ConnectionError: state store unreachable")],
    )

    def fail() -> None:
        f.custom(
            "outage", "A dependency of the control plane fails", "It cannot check totals, and does not guess.",
            box="2", rows=[row("Counter store", "fail", "unreachable")], state="stop",
            tool=TOOLS["controls"], ref=[outage], fresh=False,
        )  # fmt: skip

    f.flow(
        d3,
        act="Control plane outage",
        lead="A write-off, while a dependency is down.",
        quick=True,
        between=fail,
    )
    f.blocked(
        [fu.blocked_beat(w, d3, "Control plane outage")],
        "Nothing runs: fail closed",
        "No decision, no action.",
    )
    return f.beats, [d1, d2, d3]


SCENARIO_FNS: list[tuple[str, Callable[[], Scenario]]] = [
    ("p2p-invoice", s_invoice),
    ("p2p-payment", s_payment),
    ("p2p-bank-change", s_bank_change),
    ("o2c-billing", s_billing),
    ("o2c-writeoff", s_writeoff),
    ("r2r-journal", s_journal),
    ("r2r-closed-period", s_closed_period),
    ("r2r-adjustment", s_adjustment),
    ("kill-switch", s_kill_switch),
]
CORE = {"p2p-invoice", "p2p-payment", "p2p-bank-change", "r2r-journal"}


def fingerprint(beats: list[dict[str, Any]], decisions: list[Decision]) -> dict[str, Any]:
    """The stable part of a recording: outcomes, reasons, rule results and step statuses."""
    return {
        "decisions": [
            {
                "outcome": d.entry.outcome,
                "stage": d.entry.decided_at_stage,
                "reasons": list(d.body["reason_codes"]),
                "rules": [[r.control_id, r.result] for r in d.entry.rules_applied],
            }
            for d in decisions
        ],
        "beats": [[b["id"], b["status"], b["code"]] for b in beats],
    }


def build_data() -> dict[str, Any]:
    """Run every scenario on the real engine and return the page data."""
    world = build_world(Path(tempfile.mkdtemp(prefix="arg-internal-")))
    scenarios = []
    for sid, fn in SCENARIO_FNS:
        beats, decisions = fn()
        meta = SCENARIOS[sid]
        scenarios.append(
            {
                "id": sid,
                "core": sid in CORE,
                "domain": meta["domain"],
                "title": meta["title"],
                "blurb": meta["blurb"],
                "system": meta["system"],
                "outcomes": [d.entry.outcome for d in decisions],
                "beats": beats,
                "fingerprint": fingerprint(beats, decisions),
            }
        )
    stack = [
        component(world, r) for r in ROLES if r in world.runtime.components and r != "authenticator"
    ]
    return {"scenarios": scenarios, "stack": stack, "tokens": sorted(TOKENS)}


def build_page(data: dict[str, Any]) -> str:
    """Inline style, script and data into the page template."""
    page = (HERE / "page.html").read_text()
    page = page.replace("/*STYLE*/", (HERE / "style.css").read_text())
    page = page.replace("/*SCRIPT*/", (HERE / "app.js").read_text())
    blob = json.dumps(data, indent=1, ensure_ascii=False)
    return MARK.sub(lambda m: f"{m.group(1)}\nconst DATA = {blob};\n{m.group(2)}", page)


def main() -> None:
    """Write the page and print one line per scenario."""
    data = build_data()
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(build_page(data))
    for s in data["scenarios"]:
        print(f"{s['id']:<20} {','.join(s['outcomes']):<32} {len(s['beats'])} beats")


if __name__ == "__main__":
    main()
