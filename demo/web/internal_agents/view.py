"""Presentation layer: a few words and one picture per step (DOC-04).

A ``Film`` turns recorded decisions into beats. Each beat carries a full snapshot of the
diagram (agent card, the three control-plane steps with their check rows, the lit
disposition, the system and the reviewer), so the page can step forward and back by simply
drawing a snapshot. Every row comes from the recorded decision. The reference-implementation
detail sits behind each beat as ``ref`` (DOC-05).
"""

import copy
from collections.abc import Callable
from typing import Any

from demo.web.internal_agents import detail as dt
from demo.web.internal_agents.story import (
    AGENT_NAME,
    CONTROL_LABEL,
    DISPOSITION,
    LEAD,
    REASON,
    TOOLS,
    VERB,
)
from demo.web.internal_agents.trace import Decision
from demo.web.internal_agents.world import World

GROUPS = {
    "propose": ("propose", "envelope"),
    "identity": ("validate", "identity", "mandate"),
    "controls": ("controls", "evaluate", "risk"),
    "decide": ("resolve",),
    "evidence": ("audit",),
}
IDENTITY_ROWS = [
    "Request is complete",
    "Agent is registered",
    "Agent is active",
    "Signature matches its key",
    "Mandate is valid",
]
FAIL_AT = {
    "IDN_AGENT_UNKNOWN": 1,
    "IDN_AGENT_SUSPENDED": 2,
    "IDN_AGENT_REVOKED": 2,
    "IDN_CONTEXT_NOT_ALLOWED": 2,
}
OUTCOME_STATE = {"deny": "fail", "escalate": "warn", "observe": "mon", "auto_execute": "ok"}
BOX_STATE = {"fail": "stop", "warn": "wait"}
RISK_WORD = {
    "auto_execute": "low",
    "observe": "sensitive, watch",
    "escalate": "high, ask a person",
    "deny": "too high",
}


def row(text: str, state: str, detail: str = "") -> dict[str, str]:
    """One check row inside a control-plane step; state is ok, fail, warn, mon or skip."""
    return {"t": text, "s": state, "d": detail}


def trim(b: dict[str, Any]) -> dict[str, Any]:
    """Keep only what the reference panel shows."""
    keep = ("title", "tech", "stack", "components", "artifacts", "estate")
    return {k: b[k] for k in keep}


def ref_items(old: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """The reference-implementation detail items grouped under one simple step."""
    return [trim(b) for b in old if b["id"] in GROUPS.get(key, (key,))]


def rule_detail(r: Any) -> str:
    """A few words of real numbers for one control result."""
    i = r.inputs
    if "used" in i:
        return f"{i['used'] + i['amount']:,.0f} against a cap of {i['limit']:,.0f}"
    if "limit" in i:
        return f"{i['amount']:,.0f} against a limit of {i['limit']:,.0f}"
    if "max_actions" in i:
        return f"{i['count']:.0f} of {i['max_actions']} allowed"
    if "minimum" in i:
        return f"confidence {i['value']}, needs {i['minimum']}"
    if "value" in i:
        return f"confidence {i['value']}"
    if "missing" in i:
        return f"missing: {i['missing']}"
    return str(i.get("action_type", ""))


class Film:
    """Builds the beats of one scenario, keeping the diagram state between beats."""

    def __init__(self, world: World, sid: str) -> None:
        """Start an empty film for scenario ``sid``."""
        self.world, self.sid = world, sid
        self.beats: list[dict[str, Any]] = []
        self.act: str | None = None
        self._reset()

    def _reset(self) -> None:
        self.agent = {"name": "", "ask": ""}
        self.boxes: dict[str, dict[str, Any]] = {
            n: {"state": "idle", "rows": []} for n in ("1", "2", "3")
        }
        self.disp: str | None = None
        self.system = {"state": "idle", "text": ""}
        self.review = {"state": "idle", "text": ""}

    def emit(
        self,
        bid: str,
        head: str,
        sub: str,
        *,
        at: str,
        active: str,
        tool: str,
        status: str = "ok",
        pstate: str = "",
        ref: list[dict[str, Any]] | None = None,
        ptext: str | None = None,
        code: str = "",
    ) -> None:
        """Append a beat with a snapshot of the diagram as it is now."""
        view = {
            "agent": self.agent,
            "boxes": self.boxes,
            "disp": self.disp,
            "system": self.system,
            "review": self.review,
            "packet": {"at": at, "state": pstate, "text": ptext or self.agent["ask"]},
        }
        self.beats.append(
            {
                "id": bid,
                "act": self.act,
                "head": head,
                "sub": sub,
                "tool": tool,
                "active": active,
                "status": status,
                "code": code,
                "view": copy.deepcopy(view),
                "ref": [trim(r) for r in ref or []],
            }
        )

    # ---- one decision ---------------------------------------------------------------

    def flow(
        self,
        d: Decision,
        *,
        act: str | None = None,
        lead: str | None = None,
        compact: bool = False,
        quick: bool = False,
        between: Callable[[], None] | None = None,
        rego: bool = False,
    ) -> None:
        """Propose, identity, controls, decide, evidence. ``compact`` drops the quiet steps.

        ``quick`` keeps only propose and decide; ``between`` runs after the proposal.
        """
        self.act = act
        old = dt.decision_beats(self.world, self.sid, d, act=act, rego=rego)
        stage = d.entry.decided_at_stage
        engaged = stage == "engine" and "retrieve" in d.states
        self._propose(d, lead, old)
        if between:
            between()
        if quick:
            self._decide(d, old)
            return
        if not compact or not engaged:
            self._identity(d, old, stage)
        if engaged:
            self._controls(d, old)
        self._decide(d, old)
        if not compact:
            self._evidence(d, old)

    def _propose(self, d: Decision, lead: str | None, old: list[dict[str, Any]]) -> None:
        self._reset()
        a = d.raw["action"]
        amount = a["parameters"].get("amount")
        ask = VERB[a["type"]] + (f" · {amount:,.0f}" if amount else "")
        agent = d.raw["context"]["agent_id"]
        self.agent = {"name": AGENT_NAME[agent], "ask": ask}
        self.emit(
            "propose",
            "An agent asks to act",
            lead or LEAD[self.sid],
            at="agent",
            active="agent",
            tool=TOOLS["propose"],
            ref=ref_items(old, "propose"),
        )

    def _identity(self, d: Decision, old: list[dict[str, Any]], stage: str) -> None:
        code = d.body["reason_codes"][0] if d.body["reason_codes"] else ""
        fail = None
        if stage == "validation":
            fail = 0
        elif stage == "identity":
            fail = FAIL_AT.get(code, 3)
        elif stage == "mandate":
            fail = 4
        mandate = d.states.get("mandate", {}).get("mandate")
        grant = ""
        if mandate is not None:
            per_action = mandate.limits.per_action
            grant = (
                f"up to {per_action:,.0f} per action"
                if per_action
                else "permits " + ", ".join(mandate.permitted_actions)
            )
        rows = []
        for i, label in enumerate(IDENTITY_ROWS):
            state = "ok" if fail is None or i < fail else ("fail" if i == fail else "skip")
            detail = grant if i == 4 and state == "ok" else ""
            if state == "fail":
                detail = REASON.get(code, code)
            rows.append(row(label, state, detail))
        self.boxes["1"] = {"state": "stop" if fail is not None else "pass", "rows": rows}
        self.emit(
            "identity",
            "1 · Identity and mandate",
            REASON.get(code, code) if fail is not None else "Known agent, valid mandate.",
            at="b1",
            active="1",
            tool=TOOLS["identity"],
            status="stop" if fail is not None else "ok",
            pstate="stop" if fail is not None else "",
            ref=ref_items(old, "identity"),
        )

    def _controls(self, d: Decision, old: list[dict[str, Any]]) -> None:
        rows = []
        first: str | None = None
        for r in d.entry.rules_applied:
            state = "ok" if r.result == "pass" else OUTCOME_STATE.get(r.effect or "deny", "fail")
            detail = rule_detail(r)
            rows.append(row(CONTROL_LABEL[r.control_id], state, detail))
            if r.result == "fire" and first is None:
                first = f"{REASON.get(r.reason_code, r.reason_code)}: {detail}"
        risk = d.states["evaluate"]["disposition"].risk_profile.indicated_outcome.value
        rows.append(row("Risk of this kind of action", OUTCOME_STATE[risk], RISK_WORD[risk]))
        states = {x["s"] for x in rows}
        worst = "fail" if "fail" in states else "warn" if "warn" in states else ""
        self.boxes["2"] = {"state": BOX_STATE.get(worst, "pass"), "rows": rows}
        sub = first or (
            "Allowed, but a sensitive action." if risk == "observe" else "Every control passes."
        )
        self.emit(
            "controls",
            "2 · Limits and controls",
            sub,
            at="b2",
            active="2",
            tool=TOOLS["controls"],
            status={"fail": "stop", "warn": "wait"}.get(worst, "ok"),
            pstate=BOX_STATE.get(worst, ""),
            ref=ref_items(old, "controls"),
        )

    def _decide(self, d: Decision, old: list[dict[str, Any]]) -> None:
        e = d.entry
        codes = list(e.basis.controlling) or list(d.body["reason_codes"])
        because = {
            "auto_execute": "No control objected.",
            "observe": REASON["RISK_OBSERVE_THRESHOLD"] + ".",
        }.get(e.outcome) or REASON.get(codes[0], codes[0])
        state = OUTCOME_STATE[e.outcome]
        if self.boxes["2"]["state"] == "idle":
            self.boxes["2"]["state"] = "skip"
        self.boxes["3"] = {
            "state": BOX_STATE.get(state, "pass"),
            "rows": [
                row("Decision", state, DISPOSITION[e.outcome]),
                row("Because", state, because),
            ],
        }
        self.disp = e.outcome
        self.emit(
            "decide",
            "3 · " + DISPOSITION[e.outcome],
            because,
            at="b3",
            active="3",
            tool=TOOLS["decide"],
            status={"fail": "stop", "warn": "wait"}.get(state, "ok"),
            pstate=BOX_STATE.get(state, ""),
            ref=ref_items(old, "decide"),
        )

    def _evidence(self, d: Decision, old: list[dict[str, Any]]) -> None:
        e = d.entry
        self.boxes["3"]["rows"].append(
            row("Audit log", "ok", f"entry #{e.seq}, chained to the one before")
        )
        observe = e.outcome == "observe"
        self.emit(
            "evidence",
            "3 · Evidence recorded",
            "Flagged for follow-up review." if observe else "Chained, tamper-evident log entry.",
            at="b3",
            active="3",
            tool=TOOLS["evidence"],
            pstate=BOX_STATE.get(OUTCOME_STATE[e.outcome], ""),
            ref=ref_items(old, "evidence"),
        )

    # ---- what happens next ----------------------------------------------------------

    def _b3_state(self) -> str:
        return {"fail": "stop", "warn": "wait"}.get(self.boxes["3"]["rows"][0]["s"], "")

    def accept(
        self, ref: list[dict[str, Any]], head: str, sub: str, *, text: str = "Accepted"
    ) -> None:
        """The bank system takes the action (token valid)."""
        self.system = {"state": "ok", "text": text}
        self.emit(
            "system", head, sub, at="system", active="system", tool=TOOLS["system"],
            ref=ref, code=ref[-1]["artifacts"][-1]["label"],
        )  # fmt: skip

    def refuse(
        self, ref: list[dict[str, Any]], head: str, sub: str, *, ptext: str | None = None
    ) -> None:
        """The bank system turns the call away; ``ptext`` is what actually arrived."""
        self.system = {"state": "stop", "text": "Refused"}
        self.emit(
            "system", head, sub, at="system", active="system", tool=TOOLS["system"],
            status="stop", pstate="stop", ref=ref, ptext=ptext,
            code=ref[-1]["artifacts"][-1]["label"],
        )  # fmt: skip

    def blocked(self, ref: list[dict[str, Any]], head: str, sub: str) -> None:
        """Deny: nothing reaches the bank system."""
        self.system = {"state": "idle", "text": "Nothing arrives"}
        self.emit(
            "system", head, sub, at="b3", active="system", tool=TOOLS["system"],
            status="stop", pstate="stop", ref=ref, code=ref[-1]["artifacts"][-1]["label"],
        )  # fmt: skip

    def hold(self, ref: list[dict[str, Any]], head: str, sub: str) -> None:
        """Escalate: the action waits for a person."""
        self.review = {"state": "wait", "text": "Waiting for a reviewer"}
        self.system = {"state": "idle", "text": "On hold"}
        self.emit(
            "hold", head, sub, at="review", active="review", tool=TOOLS["review"],
            status="wait", pstate="wait", ref=ref,
        )  # fmt: skip

    def reviewed(self, ok: bool, ref: list[dict[str, Any]], head: str, sub: str, who: str) -> None:
        """A reviewer approves or declines."""
        self.review = {"state": "ok" if ok else "stop", "text": who}
        self.emit(
            "review", head, sub, at="review", active="review", tool=TOOLS["review"],
            status="ok" if ok else "stop", pstate="" if ok else "stop", ref=ref,
        )  # fmt: skip

    def custom(
        self,
        bid: str,
        head: str,
        sub: str,
        *,
        box: str,
        rows: list[dict[str, str]],
        state: str,
        tool: str,
        ref: list[dict[str, Any]],
        fresh: bool = True,
    ) -> None:
        """A one-off beat that changes a single step (kill switch, outage)."""
        if fresh:
            agent = self.agent
            self._reset()
            self.agent = agent
        self.boxes[box] = {"state": state, "rows": rows}
        self.emit(
            bid, head, sub, at=f"b{box}", active=box, tool=tool,
            status="stop", pstate="stop", ref=ref,
        )  # fmt: skip
