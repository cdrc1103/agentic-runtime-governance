"""Checkpoint P4 demo: sample envelopes through identity, mandate, controls, and the engine.

Fictional Example Bank data; keys are generated at run time. Not regulatory guidance.
Run: ``uv run python demo/engine_demo.py``.
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.core import crypto
from arg.core.engine.disposition import DispositionEngine
from arg.core.engine.keys import counter_key
from arg.core.models import (
    Action,
    ActionTrace,
    Context,
    Envelope,
    EvaluationContext,
    IdentityRejection,
    Mandate,
    MandateLimits,
    MandateRejection,
    Provenance,
    TraceStep,
)
from arg.runtime import build_runtime

AT = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
BUNDLE = Path(__file__).parent.parent / "config" / "bundle"


def mandate(mid: str, agent: str, **kw: Any) -> Mandate:
    """A mandate from alice.example, valid for a month around AT."""
    base: dict[str, Any] = {
        "mandate_id": mid,
        "principal": "alice.example",
        "agent_id": agent,
        "permitted_actions": ["payment.initiate"],
        "limits": MandateLimits(per_action=50000),
        "not_before": AT - timedelta(days=1),
        "not_after": AT + timedelta(days=30),
    }
    return Mandate(**{**base, **kw})


def envelope(
    env_id: str,
    agent: str,
    mandate_ref: str,
    amount: float,
    *,
    action_type: str = "payment.initiate",
    signals: dict[str, Any] | None = None,
) -> Envelope:
    """A native envelope with a one-step trace."""
    step = TraceStep(
        step_id="s1",
        kind="retrieval",
        name="lookup_balance",
        started_at=AT,
        ended_at=AT + timedelta(seconds=1),
    )
    return Envelope(
        envelope_id=env_id,
        created_at=AT,
        action=Action(
            type=action_type,
            scope="account:ACME-001",
            parameters={"amount": amount, "currency": "USD"},
        ),
        action_trace=ActionTrace(steps=[step]),
        context=Context(
            agent_id=agent,
            mandate_ref=mandate_ref,
            network_context="internal",
            signals=signals if signals is not None else {"confidence": 0.95},
        ),
        provenance=Provenance(origin="native", adapter_id=f"adapter-{agent}"),
    )


def main() -> None:
    """Build the runtime, run the scenarios, print a table."""
    agent_key = crypto.generate_private_key()
    rogue_key = crypto.generate_private_key()
    principal_key = crypto.generate_private_key()

    def pem(key: Ed25519PrivateKey) -> str:
        return crypto.public_key_pem(key.public_key()).decode()

    mandates = [
        mandate("m-ok", "treasury-agent-1"),
        mandate("m-expired", "treasury-agent-1", not_after=AT - timedelta(days=1)),
        mandate("m-fx-only", "treasury-agent-1", permitted_actions=["fx.trade"]),
    ]
    signed = [crypto.sign_mandate(m, principal_key) for m in mandates]
    widened = signed[2].model_copy(update={"permitted_actions": ["fx.trade", "payment.initiate"]})
    signed.append(widened.model_copy(update={"mandate_id": "m-widened"}))

    tmp = Path(tempfile.mkdtemp(prefix="arg-demo-"))
    (tmp / "agents.yaml").write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "agent_id": "treasury-agent-1",
                        "agent_class": "treasury",
                        "status": "active",
                        "principal": "alice.example",
                        "public_keys": [pem(agent_key)],
                        "allowed_network_contexts": ["internal"],
                    },
                    {
                        "agent_id": "payments-agent-1",
                        "agent_class": "payments",
                        "status": "suspended",
                        "principal": "bob.example",
                        "public_keys": [pem(agent_key)],
                    },
                ]
            }
        )
    )
    (tmp / "mandates.yaml").write_text(
        yaml.safe_dump(
            {
                "mandates": [m.model_dump(mode="json") for m in signed],
                "principals": {"alice.example": pem(principal_key)},
            }
        )
    )
    rt = build_runtime(
        {
            "components": {
                "agent_registry": {"type": "file", "path": str(tmp / "agents.yaml")},
                "envelope_authenticator": {"type": "by-origin"},
                "identity_verifier": {"type": "default"},
                "controls_repository": {"type": "bundle", "path": str(BUNDLE)},
                "mandate_resolver": {"type": "file", "path": str(tmp / "mandates.yaml")},
                "risk_calibrator": {"type": "config", "path": str(BUNDLE / "calibration.yaml")},
                "resolution_policy": {"type": "precedence"},
            },
            "evaluators": {
                n: {"type": n} for n in ("authorisation", "exposure", "rate", "evidence")
            },
        }
    )
    c = rt.components
    engine = DispositionEngine(rt.evaluators, c["risk_calibrator"], c["resolution_policy"])
    print(
        f"policy_version {c['controls_repository'].policy_version[:16]}…  at {AT:%Y-%m-%d %H:%MZ}\n"
    )

    def run(label: str, env: Envelope, state_for: dict[str, float] | None = None) -> None:
        """Run one scenario; print outcome and reason codes."""
        try:
            ident = c["identity_verifier"].verify(env)
        except IdentityRejection as e:
            print(f"{label:<44} REJECTED@identity   {e.code}")
            return
        try:
            m = c["mandate_resolver"].resolve(env.context.mandate_ref or "", ident.agent_id, AT)
        except MandateRejection as e:
            print(f"{label:<44} DENY@mandate        {e.code}")
            return
        controls = c["controls_repository"].retrieve(ident, env.action, AT)
        state: dict[str, float] = {}
        if state_for:
            probe = EvaluationContext(env, ident, AT, m)
            for ctl in controls:
                if ctl.control_id in state_for:
                    state[counter_key(ctl, probe)] = state_for[ctl.control_id]
        d = engine.evaluate(env, ident, controls, state, env.context.signals, at=AT, mandate=m)
        print(f"{label:<44} {d.outcome.value.upper():<19} {', '.join(d.reason_codes) or '-'}")

    def signed_env(*a: Any, key: Ed25519PrivateKey = agent_key, **kw: Any) -> Envelope:
        return crypto.sign_envelope(envelope(*a, **kw), key)

    treasurer = "treasury-agent-1"
    print(f"{'scenario':<44} {'outcome':<19} reasons")
    print("-" * 100)
    run("S01 payment 500, within limits", signed_env("e1", treasurer, "m-ok", 500))
    run("    payment 5,000 (medium materiality)", signed_env("e2", treasurer, "m-ok", 5000))
    run("S02 payment 20,000 > per-action limit", signed_env("e3", treasurer, "m-ok", 20000))
    run(
        "S21 payment 500, anomalous signal",
        signed_env(
            "e4", treasurer, "m-ok", 500, signals={"confidence": 0.95, "anomaly_score": 0.9}
        ),
    )
    run(
        "S20 payment 10, low confidence",
        signed_env("e5", treasurer, "m-ok", 10, signals={"confidence": 0.4}),
    )
    run(
        "S03 payment 2,000, principal already at 24,000",
        signed_env("e6", treasurer, "m-ok", 2000),
        {"exposure-payment-aggregate": 24000},
    )
    run(
        "S19 payment 100, rate window full",
        signed_env("e7", treasurer, "m-ok", 100),
        {"rate-payments": 20},
    )
    run("S04 expired mandate", signed_env("e8", treasurer, "m-expired", 500))
    run("S17 mandate widened by agent", signed_env("e9", treasurer, "m-widened", 500))
    run("    mandate permits fx only", signed_env("e10", treasurer, "m-fx-only", 500))
    run(
        "    uncalibrated action type",
        signed_env("e11", treasurer, "m-ok", 500, action_type="wire.exotic"),
    )
    run("S05 suspended agent", signed_env("e12", "payments-agent-1", "m-ok", 500))
    run(
        "S09 envelope signed with wrong key",
        signed_env("e13", treasurer, "m-ok", 500, key=rogue_key),
    )
    run("    unknown agent", signed_env("e14", "ghost-agent", "m-ok", 500))


if __name__ == "__main__":
    main()
