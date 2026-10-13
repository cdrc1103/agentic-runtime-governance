"""A fully wired runtime of fictional Example Bank components for service-level tests."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.core import crypto
from arg.core.decision.service import DecisionService
from arg.core.models import Action, DecisionResponse, Mandate, MandateLimits
from arg.runtime import GovernanceRuntime, build_runtime
from tests.core.factories import T0, make_envelope

BUNDLE = Path("config/bundle")


class Clock:
    """Settable clock."""

    def __init__(self, now: datetime) -> None:
        """Start at ``now``."""
        self.now = now

    def __call__(self) -> datetime:
        """Return the current fake time."""
        return self.now

    def advance(self, **kw: float) -> None:
        """Move time forward."""
        self.now += timedelta(**kw)


@dataclass
class World:
    """Runtime plus helpers."""

    rt: GovernanceRuntime
    svc: DecisionService
    clock: Clock
    agent_key: Ed25519PrivateKey
    principal_key: Ed25519PrivateKey
    counter: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def raw(
        self,
        amount: float = 500,
        *,
        agent: str = "treasury-agent-1",
        mandate: str = "mandate-1",
        envelope_id: str | None = None,
        key: Ed25519PrivateKey | None = None,
        signals: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        sign: bool = True,
    ) -> dict[str, Any]:
        """A signed native payment envelope as submitted JSON."""
        self.counter += 1
        from arg.core.models import Context

        parameters = {"amount": amount, "currency": "USD", **(params or {})}
        env = make_envelope(
            envelope_id=envelope_id or f"env-{self.counter:04d}",
            created_at=self.clock.now,
            action=Action(type="payment.initiate", scope="account:ACME-001", parameters=parameters),
            context=Context(
                agent_id=agent,
                mandate_ref=mandate,
                network_context="internal",
                signals=signals if signals is not None else {"confidence": 0.95},
            ),
        )
        if sign:
            env = crypto.sign_envelope(env, key or self.agent_key)
        return env.model_dump(mode="json")

    def decide(self, amount: float = 500, **kw: Any) -> DecisionResponse:
        """Submit a payment."""
        return self.svc.decide(self.raw(amount, **kw))

    def audit(self, stream: str = "treasury-agent-1") -> Any:
        """Entries of the stream."""
        return self.rt.components["audit_store"].read_stream(stream)


def build_world(
    tmp: Path,
    *,
    max_open: int = 100,
    state: str = "memory",
    audit: str = "memory",
    controls_path: Path = BUNDLE,
    tokens: bool = True,
) -> World:
    """Build a runtime with keys generated now; clock fixed at T0."""
    agent_key = crypto.generate_private_key()
    principal_key = crypto.generate_private_key()

    def pem(key: Ed25519PrivateKey) -> str:
        return crypto.public_key_pem(key.public_key()).decode()

    (tmp / "agents.yaml").write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "agent_id": a,
                        "agent_class": "treasury",
                        "status": "active",
                        "principal": p,
                        "public_keys": [pem(agent_key)],
                    }
                    for a, p in (
                        ("treasury-agent-1", "alice.example"),
                        ("treasury-agent-2", "alice.example"),
                        ("treasury-agent-3", "bob.example"),
                    )
                ]
                + [
                    {
                        "agent_id": "suspended-agent",
                        "agent_class": "treasury",
                        "status": "suspended",
                        "principal": "alice.example",
                        "public_keys": [pem(agent_key)],
                    }
                ]
            }
        )
    )

    def mandate(
        mid: str, agent: str, principal: str = "alice.example", **kw: Any
    ) -> dict[str, Any]:
        m = Mandate(
            mandate_id=mid,
            principal=principal,
            agent_id=agent,
            permitted_actions=["payment.initiate"],
            limits=MandateLimits(per_action=100000),
            not_before=T0 - timedelta(days=1),
            not_after=T0 + timedelta(days=30),
            **kw,
        )
        return crypto.sign_mandate(m, principal_key).model_dump(mode="json")

    expired = Mandate(
        mandate_id="mandate-exp",
        principal="alice.example",
        agent_id="treasury-agent-1",
        permitted_actions=["payment.initiate"],
        not_before=T0 - timedelta(days=5),
        not_after=T0 - timedelta(hours=1),
    )
    mandates = [
        mandate("mandate-1", "treasury-agent-1"),
        mandate("mandate-2", "treasury-agent-2"),
        mandate("mandate-3", "treasury-agent-3"),
        crypto.sign_mandate(expired, principal_key).model_dump(mode="json"),
    ]
    (tmp / "mandates.yaml").write_text(
        yaml.safe_dump(
            {
                "mandates": mandates,
                "principals": {
                    "alice.example": pem(principal_key),
                    "bob.example": pem(principal_key),
                },
            }
        )
    )
    audit_cfg: dict[str, Any] = {"type": audit}
    if audit == "sqlite":
        audit_cfg["path"] = str(tmp / "audit.db")
    state_cfg: dict[str, Any] = {"type": state}
    if state == "sqlite":
        state_cfg["path"] = str(tmp / "state.db")
    cfg: dict[str, Any] = {
        "components": {
            "state_store": state_cfg,
            "audit_store": audit_cfg,
            "agent_registry": {"type": "file", "path": str(tmp / "agents.yaml")},
            "envelope_authenticator": {"type": "by-origin"},
            "identity_verifier": {"type": "default"},
            "controls_repository": {"type": "bundle", "path": str(controls_path)},
            "mandate_resolver": {"type": "file", "path": str(tmp / "mandates.yaml")},
            "risk_calibrator": {"type": "config", "path": str(controls_path / "calibration.yaml")},
            "resolution_policy": {"type": "precedence"},
            "escalation_queue": {
                "type": "state",
                "reviewers_path": "config/reviewers.yaml",
                "max_open": max_open,
            },
        },
        "evaluators": {n: {"type": n} for n in ("authorisation", "exposure", "rate", "evidence")},
        "pipeline": [
            {
                "type": "validate",
                "requirements": {
                    "payment.initiate": {
                        "required_parameters": ["amount", "currency"],
                        "trace_required": True,
                    }
                },
            },
            "identity",
            "mandate",
            "retrieve",
            "evaluate",
            "reserve",
        ],
    }
    if tokens:
        (tmp / "token.pem").write_bytes(crypto.private_key_pem(crypto.generate_private_key()))
        cfg["components"]["token_service"] = {
            "type": "ed25519",
            "private_key_path": str(tmp / "token.pem"),
            "ttl_seconds": 300,
        }
    rt = build_runtime(cfg)
    assert rt.decision_service is not None
    clock = Clock(T0)
    rt.decision_service.clock = clock
    return World(rt, rt.decision_service, clock, agent_key, principal_key)
