"""Reference-implementation detail for each pipeline step (DOC-05).

Each function turns one stage of a recorded decision into a detail item: the real artifacts,
the live components behind it and the technology. The presentation layer (``view``) groups
these under its simple steps. Nothing here decides anything.
"""

import json
from pathlib import Path
from typing import Any

import yaml

from arg.core.models import Action
from arg.core.tokens.service import action_hash
from demo.web.internal_agents.story import DISPOSITION, ESTATE, GENERIC, SCENARIOS, TECH
from demo.web.internal_agents.trace import (
    Decision,
    component,
    jsonable,
    short,
)
from demo.web.internal_agents.world import BUNDLE, World, hdr

REGO = Path(__file__).resolve().parents[3] / "config" / "bundle" / "rego" / "exposure.rego"
FOCUS = {
    "propose": "agent",
    "envelope": "adapter",
    "validate": "validate",
    "identity": "identity",
    "mandate": "mandate",
    "controls": "controls",
    "evaluate": "engine",
    "risk": "engine",
    "resolve": "engine",
    "audit": "audit",
    "token": "tokens",
    "escalation": "escalation",
    "execute": "system",
}
STEP = {"validate": 1, "identity": 1, "mandate": 1, "controls": 2, "evaluate": 2, "risk": 2}
ROLES_FOR = {
    "validate": ["stage:validate"],
    "identity": ["agent_registry", "identity_verifier", "envelope_authenticator"],
    "mandate": ["mandate_resolver"],
    "controls": ["controls_repository", "state_store"],
    "evaluate": ["evaluators", "state_store"],
    "risk": ["risk_calibrator"],
    "resolve": ["resolution_policy"],
    "audit": ["audit_store", "anchor_sink"],
    "token": ["token_service"],
    "escalation": ["escalation_queue", "state_store"],
    "execute": ["token_service", "state_store"],
}


def art(label: str, kind: str, body: Any) -> dict[str, Any]:
    """One artifact shown beside a step; ``body`` is text, or a table dict for ``table``."""
    return {"label": label, "kind": kind, "body": body}


def js(obj: Any) -> str:
    """Readable JSON text."""
    return json.dumps(jsonable(obj), indent=2, ensure_ascii=False)


def beat(
    key: str,
    world: World,
    *,
    title: str,
    plain: str,
    tech: str,
    status: str = "ok",
    artifacts: list[dict[str, Any]] | None = None,
    act: str | None = None,
    tech_key: str | None = None,
) -> dict[str, Any]:
    """Assemble a beat with its focus box, slide step, components and estate line."""
    tk = tech_key or key
    return {
        "id": key,
        "act": act,
        "focus": FOCUS[key],
        "step": STEP.get(key, 3 if key in ("resolve", "audit", "token", "escalation") else 0),
        "title": title,
        "plain": plain,
        "tech": tech,
        "status": status,
        "artifacts": artifacts or [],
        "components": [component(world, r) for r in ROLES_FOR.get(key, [])],
        "stack": TECH.get(tk, []),
        "estate": ESTATE.get(tk, ""),
    }


def _shorten(node: Any) -> Any:
    """Abbreviate signatures and keys in a copy of a JSON structure."""
    if isinstance(node, dict):
        return {
            k: short(v, 20)
            if k in ("signature", "public_key") and isinstance(v, str)
            else _shorten(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_shorten(v) for v in node]
    return node


def _registry_record(world: World, agent: str) -> str:
    data = yaml.safe_load(world.registry_file.read_text())
    rec = next((a for a in data["agents"] if a["agent_id"] == agent), None)
    if rec is None:
        return "# no such agent in the register"
    rec = {**rec, "public_keys": [short(k.replace("\n", ""), 40) for k in rec["public_keys"]]}
    return yaml.safe_dump(rec, sort_keys=False)


def _propose(
    world: World, sid: str, d: Decision, act: str | None, intent: str | None
) -> dict[str, Any]:
    meta, env = SCENARIOS[sid], d.raw
    a = env["action"]
    rows = [
        ["Agent", env["context"]["agent_id"]],
        ["Action type", a["type"]],
        ["Scope", a["scope"]],
        ["Parameters", json.dumps(a["parameters"])],
        ["Target system", meta["system"]],
    ]
    return beat(
        "propose",
        world,
        title=f"{env['context']['agent_id']} proposes an action",
        plain=intent or meta["intent"],
        tech="The agent decides what to do. It cannot do it yet: the call to the bank system is "
        "held until the control plane answers.",
        artifacts=[art("Proposed action", "table", {"head": ["Field", "Value"], "rows": rows})],
        act=act,
    )


def _envelope(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    a = d.raw["action"]
    h = action_hash(Action(type=a["type"], scope=a["scope"], parameters=a["parameters"]))
    return beat(
        "envelope",
        world,
        title=GENERIC["envelope"][0],
        plain=GENERIC["envelope"][1],
        tech=GENERIC["envelope"][2],
        artifacts=[
            art("Signed envelope (as submitted)", "json", js(_shorten(d.raw))),
            art("Action hash", "text", f"{h}\nA decision token later binds to exactly this value."),
        ],
        act=act,
    )


def _validate(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    e, t = d.entry, d.raw["action"]["type"]
    req = next(
        s["requirements"].get(t, {})
        for s in world.config["pipeline"]
        if isinstance(s, dict) and s["type"] == "validate"
    )
    stop = e.decided_at_stage == "validation"
    rows = [
        ["Required parameters", ", ".join(req.get("required_parameters", [])) or "none"],
        ["Trace steps recorded", ", ".join(s["name"] for s in d.raw["action_trace"]["steps"])],
        ["Result", f"rejected: {e.basis.controlling}" if stop else "complete and coherent"],
    ]
    g = GENERIC["validate"]
    return beat(
        "validate",
        world,
        title=g[0],
        plain=g[1],
        tech=g[2],
        status="stop" if stop else "ok",
        artifacts=[art("Checks", "table", {"head": ["Check", "Result"], "rows": rows})],
        act=act,
    )


def _identity(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    e = d.entry
    stop = e.decided_at_stage == "identity"
    g = GENERIC["identity"]
    return beat(
        "identity",
        world,
        title=g[0],
        plain=g[1],
        tech=g[2],
        status="stop" if stop else "ok",
        artifacts=[
            art(
                "Register entry (YAML)",
                "yaml",
                _registry_record(world, d.raw["context"]["agent_id"]),
            ),
            art("Identity result", "json", js(e.identity_result.model_dump(exclude_none=True))),
        ],
        act=act,
    )


def _mandate(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    e = d.entry
    stop = e.decided_at_stage == "mandate"
    g = GENERIC["mandate"]
    snap = _shorten(e.mandate_snapshot) if e.mandate_snapshot else {"mandate": "none found"}
    return beat(
        "mandate",
        world,
        title=g[0],
        plain=g[1],
        tech=g[2],
        status="stop" if stop else "ok",
        artifacts=[art("Mandate (signed by the accountable principal)", "json", js(snap))],
        act=act,
    )


def _controls(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    e, g = d.entry, GENERIC["controls"]
    ids = [r.control_id for r in e.rules_applied]
    arts = [
        art(
            "Selection",
            "table",
            {
                "head": ["Item", "Value"],
                "rows": [
                    ["Controls selected", ", ".join(ids)],
                    ["Policy version", short(e.policy_version or "", 24)],
                    ["Counters read", json.dumps(e.state_snapshot) if e.state_snapshot else "none"],
                ],
            },
        )
    ]
    arts += [art(f"{i}.yaml", "yaml", (BUNDLE / "controls" / f"{i}.yaml").read_text()) for i in ids]
    return beat("controls", world, title=g[0], plain=g[1], tech=g[2], artifacts=arts, act=act)


def _evaluate(world: World, sid: str, d: Decision, act: str | None, rego: bool) -> dict[str, Any]:
    e, g = d.entry, GENERIC["evaluate"]
    rows = [
        [r.control_id, r.result, r.reason_code or "-", json.dumps(jsonable(r.inputs))]
        for r in e.rules_applied
    ]
    marks = [i for i, r in enumerate(e.rules_applied) if r.result == "fire"]
    arts = [
        art(
            "Control results",
            "table",
            {"head": ["Control", "Result", "Reason", "Inputs"], "rows": rows, "mark": marks},
        )
    ]
    if rego and any("exposure" in r.control_id for r in e.rules_applied):
        arts.append(
            art(
                "Optional: the exposure control as Rego (display only, not what ran)",
                "rego",
                REGO.read_text(),
            )
        )
    return beat(
        "evaluate",
        world,
        title=g[0],
        plain=SCENARIOS[sid]["evaluate"] + " " + g[1]
        if act is None
        else SCENARIOS[sid]["evaluate"],
        tech=g[2],
        status="fire" if marks else "ok",
        artifacts=arts,
        act=act,
    )


def _risk(world: World, d: Decision, act: str | None) -> dict[str, Any]:
    p = d.states["evaluate"]["disposition"].risk_profile
    cal = world.runtime.components["risk_calibrator"].calibration.action_types[
        d.raw["action"]["type"]
    ]
    rows = (
        [
            ["Reversibility", jsonable(p.reversibility), p.reversibility.rank],
            [
                "Materiality",
                f"{jsonable(p.materiality)} ({p.materiality_value})",
                p.materiality.rank,
            ],
            ["Customer impact", jsonable(p.customer_impact), p.customer_impact.rank],
            [
                "Regulatory sensitivity",
                jsonable(p.regulatory_sensitivity),
                p.regulatory_sensitivity.rank,
            ],
            ["Novel for this agent", str(p.novelty).lower(), int(p.novelty)],
            ["Score", "", p.score],
            [
                "Thresholds",
                f"observe {cal.observe_at}, escalate {cal.escalate_at}, deny {cal.deny_at}",
                "",
            ],
            ["Indicated by risk alone", DISPOSITION[p.indicated_outcome.value], ""],
        ]
        if p.reversibility is not None
        else [["Uncalibrated action type", "", ""]]
    )
    g = GENERIC["risk"]
    return beat(
        "risk",
        world,
        title=g[0],
        plain=g[1],
        tech=g[2],
        artifacts=[
            art("Risk profile", "table", {"head": ["Factor", "Value", "Rank"], "rows": rows})
        ],
        act=act,
    )


def _resolve(
    world: World, sid: str, d: Decision, act: str | None, note: str | None
) -> dict[str, Any]:
    e, g = d.entry, GENERIC["resolve"]
    rows = [
        ["Disposition", DISPOSITION[e.outcome]],
        ["Decided at", e.decided_at_stage],
        ["Controlling reasons", ", ".join(e.basis.controlling) or "none"],
        ["Contributing reasons", ", ".join(e.basis.contributing) or "none"],
    ]
    body = {
        k: v
        for k, v in jsonable(d.body).items()
        if k in ("outcome", "reason_codes", "decided_at_stage")
    }
    b = beat(
        "resolve",
        world,
        title=f"Decision: {DISPOSITION[e.outcome]}",
        plain=note or SCENARIOS[sid]["resolve"],
        tech=g[2],
        status={"deny": "stop", "escalate": "wait"}.get(e.outcome, "ok"),
        artifacts=[
            art("Decision", "table", {"head": ["Field", "Value"], "rows": rows}),
            art("Response to the platform", "json", js(body)),
        ],
        act=act,
    )
    b["outcome"] = e.outcome
    return b


def _audit(world: World, d: Decision, act: str | None, verify: bool) -> dict[str, Any]:
    e, g = d.entry, GENERIC["audit"]
    summary: dict[str, Any] = {
        "seq": e.seq,
        "agent_stream": e.agent_stream,
        "outcome": e.outcome,
        "decided_at_stage": e.decided_at_stage,
        "policy_version": short(e.policy_version or "", 16),
        "rules_applied": [f"{r.control_id}: {r.result}" for r in e.rules_applied],
        "token_jti": e.token_jti,
        "escalation_id": e.escalation_id,
        "prev_hash": short(e.prev_hash, 16),
        "entry_hash": short(e.entry_hash, 16),
    }
    arts = [art("Audit entry (abridged)", "json", js(summary))]
    if verify:
        agent = e.agent_stream
        anchor = world.api.post(f"/v1/audit/{agent}/anchor", headers=hdr("ops")).json()
        check = world.api.get(f"/v1/audit/{agent}/verify", headers=hdr("ops")).json()
        arts.append(
            art(
                "Anchor and chain check",
                "json",
                js(
                    {
                        "anchored": {"seq": anchor["seq"], "hash": short(anchor["entry_hash"], 16)},
                        "verify": check,
                    }
                ),
            )
        )
    return beat("audit", world, title=g[0], plain=g[1], tech=g[2], artifacts=arts, act=act)


def decision_beats(
    world: World,
    sid: str,
    d: Decision,
    *,
    act: str | None = None,
    intent: str | None = None,
    note: str | None = None,
    compact: bool = False,
    rego: bool = False,
) -> list[dict[str, Any]]:
    """Beats for one decision. ``compact`` keeps only propose, evaluate, resolve and audit."""
    stage = d.entry.decided_at_stage
    out = [_propose(world, sid, d, act, intent)]
    if not compact:
        out.append(_envelope(world, d, act))
        out.append(_validate(world, d, act))
        if stage != "validation":
            out.append(_identity(world, d, act))
        if stage not in ("validation", "identity"):
            out.append(_mandate(world, d, act))
    if stage == "engine" and "retrieve" in d.states:
        if not compact:
            out.append(_controls(world, d, act))
        out.append(_evaluate(world, sid, d, act, rego))
        if not compact and "evaluate" in d.states:
            out.append(_risk(world, d, act))
    out.append(_resolve(world, sid, d, act, note))
    out.append(_audit(world, d, act, verify=not compact))
    return out
