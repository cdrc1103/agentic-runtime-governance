"""A fully wired runtime of fictional Example Bank components for service-level tests."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.core import crypto
from arg.core.decision.service import DecisionService
from arg.core.models import Action, DecisionResponse
from arg.runtime import GovernanceRuntime
from demo.example_bank import BUNDLE, Clock, build_example_bank
from tests.core.factories import make_envelope


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
    """Build the Example Bank runtime; clock fixed at T0."""
    bank = build_example_bank(
        tmp,
        max_open=max_open,
        state=state,
        audit=audit,
        controls_path=controls_path,
        tokens=tokens,
    )
    rt = bank.runtime
    assert rt.decision_service is not None
    return World(rt, rt.decision_service, bank.clock, bank.agent_key, bank.principal_key)
