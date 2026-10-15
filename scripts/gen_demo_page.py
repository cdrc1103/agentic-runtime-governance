"""Regenerate the data embedded in ``docs/demo/index.html`` from the real engine.

The page replays recorded runs; it re-implements no decision logic. Each scenario is run on a
fresh in-process runtime over Example Bank (fictional data), so the page cannot drift from the
engine without this script showing a diff. Not regulatory guidance; demo only.

Run: ``uv run python -m scripts.gen_demo_page``
"""

import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from arg.core import crypto
from arg.core.models import Action
from arg.core.tokens.service import action_hash
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from demo.example_bank import ExampleBank, build_example_bank, payment_envelope

PAGE = Path(__file__).resolve().parents[1] / "docs" / "demo" / "index.html"
TOKENS = {
    "orch": {"principal": "orchestrator", "roles": ["submit"]},
    "rail": {"principal": "settlement-rail", "roles": ["consume"]},
    "rita": {"principal": "rita.reviewer", "roles": ["review"]},
    "ivan": {"principal": "ivan.intern", "roles": ["review"]},
    "ops": {"principal": "ops", "roles": ["admin"]},
}
MARK = re.compile(r"(/\*DATA_START\*/).*?(/\*DATA_END\*/)", re.S)


def hdr(key: str) -> dict[str, str]:
    """Authorization header for a demo token."""
    return {"Authorization": f"Bearer {key}"}


class Run:
    """One fresh runtime plus an in-process API client."""

    def __init__(self) -> None:
        """Build an isolated Example Bank runtime."""
        self.bank: ExampleBank = build_example_bank(Path(tempfile.mkdtemp(prefix="arg-page-")))
        self.api = TestClient(create_app(self.bank.runtime, BearerTokenAuthenticator(TOKENS)))
        self.raw: dict[str, Any] = {}

    def submit(self, amount: float, **kw: Any) -> dict[str, Any]:
        """Submit a signed payment envelope and return the decision body."""
        self.raw = payment_envelope(self.bank, amount, envelope_id="demo-1", **kw)
        r = self.api.post("/v1/decisions", json=self.raw, headers=hdr("orch"))
        body: dict[str, Any] = r.json()
        return body

    def redeem(self, token: str, amount: float | None = None) -> dict[str, Any]:
        """Redeem a token at the rail, optionally with an altered amount."""
        p = dict(self.raw["action"]["parameters"])
        if amount is not None:
            p["amount"] = amount
        a = self.raw["action"]
        h = action_hash(Action(type=a["type"], scope=a["scope"], parameters=p))
        r = self.api.post(
            "/v1/tokens/consume",
            json={"token": token, "agent_id": "treasury-agent-1", "act_hash": h},
            headers=hdr("rail"),
        )
        code = "ok" if r.status_code == 200 else r.json().get("detail", {}).get("code", "error")
        return {"status": r.status_code, "code": code}

    def entry(self) -> Any:
        """The most recent audit entry in the only populated stream."""
        store = self.bank.runtime.components["audit_store"]
        streams = [s for s in store._streams.values() if s]
        return streams[-1][-1]


def decision(run: Run, body: dict[str, Any]) -> dict[str, Any]:
    """Shape a decision plus its audit entry for the page."""
    e = run.entry()
    return {
        "outcome": body["outcome"],
        "reasons": body.get("reason_codes", []),
        "stage": e.decided_at_stage,
        "policy": e.policy_version[:12],
        "controlling": list(e.basis.controlling),
        "rules": [
            {"id": r.control_id, "result": r.result, "inputs": dict(r.inputs)}
            for r in e.rules_applied
        ],
        "next": [],
    }


def s_within() -> dict[str, Any]:
    """Within limits: token, then altered, exact, replay at the rail."""
    run = Run()
    d = decision(run, body := run.submit(500))
    tok = body["token"]
    d["next"] = [
        {
            "label": "Rail redeems with the amount changed to 50,000",
            "why": "action mismatch",
            **run.redeem(tok, 50000),
        },
        {"label": "Rail redeems the exact action", "why": "ok", **run.redeem(tok)},
        {"label": "Agent presents the same token again", "why": "replay", **run.redeem(tok)},
    ]
    return d


def s_escalate() -> dict[str, Any]:
    """Over the per-action limit: reviewer paths, each on its own fresh runtime."""
    run = Run()
    d = decision(run, body := run.submit(20000))
    url = f"/v1/escalations/{body['escalation_id']}/resolution"
    r = run.api.post(url, json={"action": "approve"}, headers=hdr("ivan"))
    d["next"].append(
        {
            "label": "Intern (limit 100) tries to approve",
            "why": "authority",
            "status": r.status_code,
            "code": r.json()["detail"]["code"],
        }
    )
    r = run.api.post(url, json={"action": "approve", "note": "called client"}, headers=hdr("rita"))
    d["next"].append(
        {
            "label": "Senior reviewer approves",
            "why": "approved",
            "status": r.status_code,
            "code": r.json()["escalation"]["state"],
        }
    )
    d["next"].append(
        {"label": "Rail redeems the approved token", "why": "ok", **run.redeem(r.json()["token"])}
    )
    run2 = Run()
    b2 = run2.submit(20000)
    r = run2.api.post(
        f"/v1/escalations/{b2['escalation_id']}/resolution",
        json={"action": "modify", "modified_parameters": {"amount": 400}},
        headers=hdr("rita"),
    )
    d["next"].append(
        {
            "label": "Reviewer modifies the amount to 400",
            "why": "modified",
            "status": r.status_code,
            "code": r.json()["child"]["outcome"],
        }
    )
    run3 = Run()
    run3.submit(20000)
    run3.bank.clock.advance(seconds=1000)
    sw = run3.api.post("/v1/escalations/sweep", headers=hdr("ops")).json()
    d["next"].append(
        {
            "label": "Nobody reviews it in time",
            "why": "timeout",
            "status": 200,
            "code": sw[0]["state"],
        }
    )
    return d


def simple(amount: float, **kw: Any) -> Callable[[], dict[str, Any]]:
    """A scenario with no follow-up actions."""

    def go() -> dict[str, Any]:
        run = Run()
        k = dict(kw)
        if k.pop("wrong_key", False):
            k["key"] = crypto.generate_private_key()
        return decision(run, run.submit(amount, **k))

    return go


SCENARIOS: list[tuple[str, str, str, Callable[[], dict[str, Any]]]] = [
    ("within", "Pay 500", "A routine payment inside every limit.", s_within),
    ("over", "Pay 20,000", "More than the per-action limit allows.", s_escalate),
    (
        "doubt",
        "Pay 10, model unsure",
        "Small amount, but the agent reports low confidence.",
        simple(10, signals={"confidence": 0.4}),
    ),
    (
        "expired",
        "Pay 500, expired mandate",
        "The agent's authority lapsed.",
        simple(500, mandate="mandate-exp"),
    ),
    (
        "ghost",
        "Pay 500, unknown agent",
        "An agent nobody registered.",
        simple(500, agent="ghost-agent"),
    ),
    (
        "forged",
        "Pay 500, wrong signing key",
        "Envelope signed with a key that is not the agent's.",
        simple(500, wrong_key=True),
    ),
]


def build_data() -> dict[str, Any]:
    """Run every scenario on the real engine and return the page data."""
    return {
        "scenarios": [
            {"id": sid, "title": title, "blurb": blurb, **fn()}
            for sid, title, blurb, fn in SCENARIOS
        ]
    }


def main() -> None:
    """Rebuild the embedded data block."""
    data = build_data()["scenarios"]
    text = PAGE.read_text()
    blob = json.dumps({"scenarios": data}, indent=1)
    PAGE.write_text(MARK.sub(lambda m: f"{m.group(1)}\nconst DATA = {blob};\n{m.group(2)}", text))
    for s in data:
        print(f"{s['id']:<8} {s['outcome']:<14} {s['stage']:<9} {','.join(s['reasons']) or '-'}")


if __name__ == "__main__":
    main()
