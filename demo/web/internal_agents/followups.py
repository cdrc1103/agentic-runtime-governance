"""What happens after a decision: token, redemption, escalation and review (DOC-05).

Each function performs the real API call once and returns a detail item for the page.
"""

from typing import Any

import yaml

from arg.core.models import Action
from arg.core.tokens.service import action_hash
from demo.web.internal_agents.detail import art, beat, js
from demo.web.internal_agents.trace import Decision, clean_paths, short, token_claims
from demo.web.internal_agents.world import REVIEWERS, World, hdr

# ---- what happens after the decision ------------------------------------------------


def redeem(world: World, d: Decision, token: str, amount: float | None = None) -> dict[str, Any]:
    """Present ``token`` at the target system, optionally for an altered amount."""
    a = dict(d.raw["action"])
    params = dict(a["parameters"])
    if amount is not None:
        params["amount"] = amount
    h = action_hash(Action(type=a["type"], scope=a["scope"], parameters=params))
    payload = {"token": token, "agent_id": d.raw["context"]["agent_id"], "act_hash": h}
    r = world.api.post("/v1/tokens/consume", json=payload, headers=hdr("target"))
    body = r.json()
    code = "ok" if r.status_code == 200 else body["detail"]["code"]
    return {"status": r.status_code, "code": code, "body": body, "act_hash": h}


def token_beat(
    world: World, d: Decision, act: str | None = None, observe: bool = False
) -> dict[str, Any]:
    """The token that proves the decision (Auto-Execute and Observe)."""
    claims = token_claims(d.body["token"])
    plain = (
        "Permission is a one-time token, signed by the control plane. It names this agent, this "
        "exact action and the policy version, and it expires in five minutes."
    )
    if observe:
        plain += " The action is also flagged for monitoring, so it shows up in follow-up."
    arts = [art("Token claims (decoded)", "json", js(claims))]
    if observe and d.entry.observations:
        arts.append(art("Observation recorded", "json", js(d.entry.observations[0].model_dump())))
    return beat(
        "token",
        world,
        title="A one-time token is issued" + (" and the action is flagged" if observe else ""),
        plain=plain,
        tech="Ed25519 JWS (compact). Claims: issuer, subject = agent, act_hash = hash of the "
        "action, policy_version, decision_id, outcome, jti, iat, exp. The id is single-use.",
        artifacts=arts,
        act=act,
    )


def execute_beat(
    world: World, r: dict[str, Any], d: Decision, *, title: str, plain: str, act: str | None = None
) -> dict[str, Any]:
    """The target system tries a token; ``r`` comes from ``redeem``."""
    ok = r["status"] == 200
    req = {
        "POST": "/v1/tokens/consume",
        "agent_id": d.raw["context"]["agent_id"],
        "act_hash": short(r["act_hash"], 16),
    }
    return beat(
        "execute",
        world,
        title=title,
        plain=plain,
        tech="The target system calls the decision API with the token and the hash of the action "
        "it was just asked to run. Signature, expiry, subject, action hash and one-time use "
        "are all checked.",
        status="ok" if ok else "stop",
        artifacts=[
            art("Request", "json", js(req)),
            art(
                f"Response {r['status']}",
                "json",
                js({"code": r["code"], **({} if not ok else {"consumed_jti": r["body"]["jti"]})}),
            ),
        ],
        act=act,
    )


def blocked_beat(
    world: World, d: Decision, act: str | None = None, why: str | None = None
) -> dict[str, Any]:
    """Nothing executes after Deny: no token exists, and the target system refuses without one."""
    r = redeem(world, d, "no-token")
    return execute_beat(
        world,
        r,
        d,
        title="Nothing reaches the bank system",
        plain=why
        or "There is no token, so there is nothing to show. If the agent tried to reach the "
        "system anyway, the system would refuse: it only acts on a valid token.",
        act=act,
    )


def escalation_beat(world: World, d: Decision, act: str | None = None) -> dict[str, Any]:
    """The held action in the review queue, with the reviewer directory for its role."""
    rec = world.api.get(f"/v1/escalations/{d.body['escalation_id']}", headers=hdr("ops")).json()
    view = {
        k: rec[k]
        for k in (
            "escalation_id",
            "state",
            "queue",
            "reviewer_role",
            "amount",
            "opened_at",
            "deadline",
            "on_timeout",
        )
    }
    roles = yaml.safe_load(REVIEWERS.read_text())["reviewers"]
    mine = [r for r in roles if rec["reviewer_role"] in r["roles"] or r.get("senior")]
    return beat(
        "escalation",
        world,
        title="The action waits for a person",
        plain="The action is parked in a review queue with a deadline. The agent is told to wait, "
        "and nothing has run. Only a reviewer with the right role and a high enough "
        "authority limit may decide.",
        tech="EscalationQueue over the state store. Asynchronous: no connection is held open. "
        "Reviewer authority comes from the reviewer directory. At the deadline the configured "
        "default applies (block).",
        status="wait",
        artifacts=[
            art("Queue record", "json", js(view)),
            art("Eligible reviewers (YAML)", "yaml", yaml.safe_dump(mine, sort_keys=False)),
        ],
        act=act,
    )


def review_beat(
    world: World,
    d: Decision,
    reviewer_key: str,
    body: dict[str, Any],
    *,
    title: str,
    plain: str,
    act: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A reviewer acts on the held action. Returns the beat and the API response."""
    esc = d.body["escalation_id"]
    r = world.api.post(f"/v1/escalations/{esc}/resolution", json=body, headers=hdr(reviewer_key))
    out = r.json()
    ok = r.status_code == 200
    shown = {"escalation": {"state": out["escalation"]["state"]}} if ok else out["detail"]
    if ok and out.get("token"):
        shown["token"] = short(out["token"], 24)
    b = beat(
        "escalation",
        world,
        title=title,
        plain=plain,
        tech="POST /v1/escalations/{id}/resolution as a reviewer. Role, authority limit and "
        "deadline are checked. Approval issues the same kind of token as Auto-Execute.",
        status="ok" if ok else "stop",
        artifacts=[
            art("Reviewer request", "json", js({"reviewer": reviewer_key, **body})),
            art(f"Response {r.status_code}", "json", js(clean_paths(shown, world))),
        ],
        act=act,
        tech_key="escalation",
    )
    return b, out
