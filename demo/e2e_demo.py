"""End-to-end demo over the HTTP API, no framework adapters (fictional Example Bank).

Scripted agents submit envelopes; a rail redeems decision tokens; reviewers resolve
escalations; an operator verifies and anchors the audit log. The API runs in-process (ASGI),
so no network or server is needed. Not regulatory guidance; demo only.

Run: ``uv run python -m demo.e2e_demo``
"""

import base64
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from arg.core import crypto
from arg.core.audit.anchor import FileAnchorSink
from arg.core.models import Action
from arg.core.tokens.service import action_hash
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from demo.example_bank import build_example_bank, payment_envelope

TOKENS = {
    "tok-orchestrator": {"principal": "orchestrator", "roles": ["submit"]},
    "tok-rail": {"principal": "settlement-rail", "roles": ["consume"]},
    "tok-rita": {"principal": "rita.reviewer", "roles": ["review"]},
    "tok-ivan": {"principal": "ivan.intern", "roles": ["review"]},
    "tok-ops": {"principal": "ops", "roles": ["admin"]},
}


def h(token: str) -> dict[str, str]:
    """Authorization header."""
    return {"Authorization": f"Bearer {token}"}


def say(title: str) -> None:
    """Section heading."""
    print(f"\n== {title}")


def main() -> None:
    """Run the narrative."""
    tmp = Path(tempfile.mkdtemp(prefix="arg-e2e-"))
    bank = build_example_bank(tmp, max_open=5)
    rt = bank.runtime
    rt.components["anchor_sink"] = FileAnchorSink(tmp / "anchors.jsonl")
    api = TestClient(create_app(rt, BearerTokenAuthenticator(TOKENS)))
    n = 0

    def submit(amount: float, **kw: Any) -> dict[str, Any]:
        nonlocal n
        n += 1
        raw = payment_envelope(bank, amount, envelope_id=f"pay-{n:03d}", **kw)
        r = api.post("/v1/decisions", json=raw, headers=h("tok-orchestrator"))
        body: dict[str, Any] = r.json()
        body["_raw"] = raw
        print(
            f"  payment {amount:>9,.0f} -> {body['outcome'].upper():<12} "
            f"{', '.join(body['reason_codes']) or '-'}"
        )
        return body

    def redeem(token: str, raw: dict[str, Any], label: str, **override: Any) -> None:
        a = raw["action"]
        body = {
            "token": token,
            "agent_id": "treasury-agent-1",
            "act_hash": action_hash(
                Action(type=a["type"], scope=a["scope"], parameters=a["parameters"])
            ),
        } | override
        r = api.post("/v1/tokens/consume", json=body, headers=h("tok-rail"))
        detail = r.json().get("detail", {}).get("code", "ok") if r.status_code != 200 else "ok"
        print(f"  rail redeems token ({label}) -> {r.status_code} {detail}")

    say("1. Within limits: Auto-Execute with a one-time decision token")
    ok = submit(500)
    claims = json.loads(base64.urlsafe_b64decode(ok["token"].split(".")[1] + "=="))
    print(
        f"  token claims: sub={claims['sub']} outcome={claims['outcome']} "
        f"act_hash={claims['act_hash'][:12]}… ttl={claims['exp'] - claims['iat']}s"
    )

    say("2. The rail enforces the token: altered action, then replay")
    redeem(
        ok["token"],
        ok["_raw"],
        "altered amount",
        act_hash=action_hash(
            Action(
                type="payment.initiate",
                scope="account:ACME-001",
                parameters={"amount": 50000, "currency": "USD", "beneficiary": "vendor-17"},
            )
        ),
    )
    redeem(ok["token"], ok["_raw"], "exact action")
    redeem(ok["token"], ok["_raw"], "second use")

    say("3. Above the per-action limit: held for a human, with authority checks")
    held = submit(20000)
    eid = held["escalation_id"]
    url = f"/v1/escalations/{eid}/resolution"
    r = api.post(url, json={"action": "approve"}, headers=h("tok-ivan"))
    print(f"  intern (limit 100) tries to approve -> {r.status_code} {r.json()['detail']['code']}")
    r = api.post(url, json={"action": "approve", "note": "called client"}, headers=h("tok-rita"))
    print(f"  rita.reviewer approves -> {r.status_code} state={r.json()['escalation']['state']}")
    redeem(r.json()["token"], held["_raw"], "approved action")

    say("4. Reviewer 'modify' re-enters the full pipeline with a parent link")
    big = submit(20000)
    r = api.post(
        f"/v1/escalations/{big['escalation_id']}/resolution",
        json={"action": "modify", "modified_parameters": {"amount": 400}},
        headers=h("tok-rita"),
    )
    child = r.json()["child"]
    print(
        f"  modified to 400 -> child decision {child['outcome'].upper()} ({child['decision_id']})"
    )

    say("5. Aggregate exposure: small payments add up (new hourly window, per principal)")
    bank.clock.advance(hours=1)
    for _ in range(3):
        submit(9000)

    say("6. Timeouts: unreviewed escalation is blocked by the sweeper")
    submit(20000)
    bank.clock.advance(seconds=1000)
    swept = api.post("/v1/escalations/sweep", headers=h("tok-ops")).json()
    print(f"  sweep -> {[(s['escalation_id'], s['state']) for s in swept]}")

    say("7. Identity and mandate failures, all recorded")
    submit(500, key=crypto.generate_private_key())
    submit(500, agent="ghost-agent")
    submit(500, mandate="mandate-exp")

    say("8. Anomalous but within limits: Observe")
    submit(500, signals={"confidence": 0.95, "anomaly_score": 0.92})

    say("9. Audit log: verify, anchor, tamper, verify again")
    v = api.get("/v1/audit/treasury-agent-1/verify", headers=h("tok-ops")).json()
    print(f"  verify -> ok={v['ok']} entries={v['checked']}")
    a = api.post("/v1/audit/treasury-agent-1/anchor", headers=h("tok-ops")).json()
    print(f"  anchored head seq={a['seq']} hash={a['entry_hash'][:12]}…")
    store = rt.components["audit_store"]
    victim = store._streams["treasury-agent-1"][2]
    store._streams["treasury-agent-1"][2] = victim.model_copy(update={"outcome": "auto_execute"})
    v = api.get("/v1/audit/treasury-agent-1/verify", headers=h("tok-ops")).json()
    print(f"  after editing entry #3 -> ok={v['ok']} code={v['code']} at seq={v['seq']}")

    say("10. Reconstructing one decision from its audit entry alone")
    e = store._streams["treasury-agent-1"][1]
    print(
        f"  {e.entry_id}: outcome={e.outcome} stage={e.decided_at_stage} "
        f"policy={e.policy_version[:12]}…"
    )
    print(f"  controlling={e.basis.controlling} contributing={e.basis.contributing}")
    for rule in e.rules_applied:
        print(f"    {rule.control_id:<32} {rule.result:<5} {dict(rule.inputs)}")


if __name__ == "__main__":
    main()
