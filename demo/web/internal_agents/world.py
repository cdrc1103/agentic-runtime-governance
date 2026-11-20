"""The bank's finance and operations world for the internal-agents demo.

Fictional agents, mandates, reviewers and keys. Keys are generated at call time. Wires the
real reference runtime with SQLite state and audit so the demo shows the stack it describes.
Not regulatory guidance; demo only.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from arg.core import crypto
from arg.core.models import (
    Action,
    ActionTrace,
    Context,
    Envelope,
    Mandate,
    MandateLimits,
    Provenance,
    TraceStep,
)
from arg.runtime import GovernanceRuntime, build_runtime
from arg.service.app import create_app
from arg.service.auth import BearerTokenAuthenticator
from demo.common.example_bank import Clock

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
CONFIG = Path(__file__).parent / "config"
BUNDLE = CONFIG / "bundle"
REVIEWERS = CONFIG / "reviewers.yaml"

# agent_id, class, principal, permitted actions, mandate per-action limit
AGENTS: list[tuple[str, str, str, list[str], float | None]] = [
    ("p2p-invoice-agent-1", "p2p", "ap-lead.example", ["invoice.approve"], 100000),
    (
        "p2p-payment-agent-1",
        "p2p",
        "ap-lead.example",
        ["supplier_payment.release"],
        25000,
    ),
    ("o2c-billing-agent-1", "o2c", "ar-lead.example", ["fee_invoice.issue"], None),
    ("o2c-collections-agent-1", "o2c", "ar-lead.example", ["receivable.write_off"], None),
    (
        "r2r-recon-agent-1",
        "r2r",
        "controller.example",
        ["journal.post", "journal.adjust"],
        None,
    ),
]

TOKENS = {
    "orch": {"principal": "agent-platform", "roles": ["submit"]},
    "target": {"principal": "target-system", "roles": ["consume"]},
    "ap-junior": {"principal": "reviewer-ap-junior", "roles": ["review"]},
    "ap-1": {"principal": "reviewer-ap-1", "roles": ["review"]},
    "ar-1": {"principal": "reviewer-ar-1", "roles": ["review"]},
    "controller": {"principal": "controller-1", "roles": ["review"]},
    "ops": {"principal": "ops", "roles": ["admin"]},
}

REQUIRED: dict[str, list[str]] = {
    "supplier.bank_details.change": ["supplier_id"],
    **{
        t: ["amount", "currency"]
        for t in (
            "invoice.approve",
            "supplier_payment.release",
            "fee_invoice.issue",
            "receivable.write_off",
            "journal.post",
            "journal.adjust",
            "journal.post_closed_period",
        )
    },
}


@dataclass
class World:
    """A wired runtime, its API client, the signing keys and the config it was built from."""

    runtime: GovernanceRuntime
    clock: Clock
    api: TestClient
    config: dict[str, Any]
    tmp: Path
    agent_keys: dict[str, Ed25519PrivateKey] = field(default_factory=dict)

    @property
    def registry_file(self) -> Path:
        """The agent register as written for this run."""
        return self.tmp / "agents.yaml"


def build_world(tmp: Path) -> World:
    """Build the runtime for the bank's agents inside ``tmp``."""
    agent_keys = {a[0]: crypto.generate_private_key() for a in AGENTS}
    principal_keys = {p: crypto.generate_private_key() for p in {a[2] for a in AGENTS}}

    def pem(key: Ed25519PrivateKey) -> str:
        return crypto.public_key_pem(key.public_key()).decode()

    records = [
        {
            "agent_id": aid,
            "agent_class": cls,
            "status": "active",
            "principal": principal,
            "public_keys": [pem(agent_keys[aid])],
            "allowed_network_contexts": ["internal"],
        }
        for aid, cls, principal, _, _ in AGENTS
    ]
    (tmp / "agents.yaml").write_text(yaml.safe_dump({"agents": records}, sort_keys=False))
    mandates = []
    for aid, _, principal, actions, per_action in AGENTS:
        m = Mandate(
            mandate_id=f"mandate-{aid}",
            principal=principal,
            agent_id=aid,
            permitted_actions=actions,
            limits=MandateLimits(per_action=per_action),
            not_before=T0 - timedelta(days=1),
            not_after=T0 + timedelta(days=90),
        )
        mandates.append(crypto.sign_mandate(m, principal_keys[principal]).model_dump(mode="json"))
    (tmp / "mandates.yaml").write_text(
        yaml.safe_dump(
            {"mandates": mandates, "principals": {p: pem(k) for p, k in principal_keys.items()}},
            sort_keys=False,
        )
    )
    (tmp / "token.pem").write_bytes(crypto.private_key_pem(crypto.generate_private_key()))
    config: dict[str, Any] = {
        "components": {
            "state_store": {"type": "sqlite", "path": str(tmp / "state.db")},
            "audit_store": {"type": "sqlite", "path": str(tmp / "audit.db")},
            "anchor_sink": {"type": "file", "path": str(tmp / "anchors.jsonl")},
            "agent_registry": {"type": "file", "path": str(tmp / "agents.yaml")},
            "envelope_authenticator": {"type": "by-origin", "trusted_gateways": []},
            "identity_verifier": {"type": "default"},
            "controls_repository": {"type": "bundle", "path": str(BUNDLE)},
            "mandate_resolver": {"type": "file", "path": str(tmp / "mandates.yaml")},
            "risk_calibrator": {"type": "config", "path": str(BUNDLE / "calibration.yaml")},
            "resolution_policy": {"type": "precedence"},
            "escalation_queue": {
                "type": "state",
                "reviewers_path": str(REVIEWERS),
                "max_open": 20,
            },
            "token_service": {
                "type": "ed25519",
                "private_key_path": str(tmp / "token.pem"),
                "issuer": "bank-control-plane",
                "ttl_seconds": 300,
            },
        },
        "evaluators": {n: {"type": n} for n in ("authorisation", "exposure", "rate", "evidence")},
        "pipeline": [
            {
                "type": "validate",
                "requirements": {
                    t: {"required_parameters": req, "trace_required": True}
                    for t, req in REQUIRED.items()
                },
            },
            "identity",
            "mandate",
            "retrieve",
            "evaluate",
            "reserve",
        ],
    }
    runtime = build_runtime(config)
    assert runtime.decision_service is not None
    clock = Clock(T0)
    runtime.decision_service.clock = clock
    api = TestClient(create_app(runtime, BearerTokenAuthenticator(TOKENS)))
    return World(runtime, clock, api, config, tmp, agent_keys)


def envelope(
    world: World,
    agent: str,
    action_type: str,
    parameters: dict[str, Any],
    *,
    envelope_id: str,
    trace: list[tuple[str, str]],
    scope: str,
    confidence: float = 0.95,
    signing_key: Ed25519PrivateKey | None = None,
) -> dict[str, Any]:
    """A signed native envelope as submitted JSON; ``trace`` is ``(kind, name)`` pairs."""
    now = world.clock.now
    steps = [
        TraceStep(
            step_id=f"s{i}",
            kind=kind,  # type: ignore[arg-type]
            name=name,
            started_at=now + timedelta(seconds=i),
            ended_at=now + timedelta(seconds=i + 1),
        )
        for i, (kind, name) in enumerate(trace, 1)
    ]
    env = Envelope(
        envelope_id=envelope_id,
        created_at=now,
        action=Action(type=action_type, scope=scope, parameters=parameters),
        action_trace=ActionTrace(steps=steps),
        context=Context(
            agent_id=agent,
            mandate_ref=f"mandate-{agent}",
            network_context="internal",
            signals={"confidence": confidence},
        ),
        provenance=Provenance(origin="native", adapter_id=f"adapter-{agent}"),
    )
    signed = crypto.sign_envelope(env, signing_key or world.agent_keys[agent])
    return signed.model_dump(mode="json")


def hdr(key: str) -> dict[str, str]:
    """Authorization header for a demo bearer token."""
    return {"Authorization": f"Bearer {key}"}
