"""Agent identity: registries, authenticators, verifier, and stage ordering."""

from pathlib import Path
from typing import Any

import pytest

from arg.core import crypto
from arg.core.canonical import canonical_hash
from arg.core.identity.authenticators import OriginDispatchAuthenticator
from arg.core.identity.registries import CompositeRegistry, FileRegistry
from arg.core.identity.stage import IdentityStage
from arg.core.identity.verifier import DefaultIdentityVerifier
from arg.core.models import (
    AgentRecord,
    AgentStatus,
    Context,
    IdentityRejection,
    ObservedCall,
    Provenance,
)
from arg.core.ports import PipelineStage
from arg.runtime import build_runtime
from tests.core.factories import make_envelope

KEY = crypto.generate_private_key()
PEM = crypto.public_key_pem(KEY.public_key()).decode()


def rec(agent_id: str = "treasury-agent-1", **kw: Any) -> AgentRecord:
    """A registry record with a registered key."""
    base: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_class": "treasury",
        "status": AgentStatus.ACTIVE,
        "principal": "alice.example",
        "public_keys": [PEM],
    }
    base.update(kw)
    return AgentRecord(**base)


def verifier(records: list[AgentRecord], gateways: tuple[str, ...] = ("gw-1",)) -> Any:
    """Default verifier over a file registry and origin dispatch."""
    return DefaultIdentityVerifier(
        FileRegistry(records=records), OriginDispatchAuthenticator(gateways)
    )


def signed(**kw: Any) -> Any:
    """A native envelope signed with the registered key."""
    return crypto.sign_envelope(make_envelope(**kw), KEY)


def code(v: Any, env: Any) -> str:
    """Return the rejection code raised for ``env``."""
    with pytest.raises(IdentityRejection) as ei:
        v.verify(env)
    return str(ei.value.code)


@pytest.mark.req("IDN-01", "IDN-05", "IDN-06")
def test_registered_active_agent_gets_binding() -> None:
    """A known active agent with a valid signature yields a confirmed binding."""
    b = verifier([rec()]).verify(signed())
    assert (b.agent_id, b.agent_class, b.principal, b.origin) == (
        "treasury-agent-1",
        "treasury",
        "alice.example",
        "native",
    )


@pytest.mark.req("IDN-01", "IDN-05")
def test_unknown_suspended_revoked_are_rejected_with_codes() -> None:
    """Unregistered, suspended, and revoked agents are rejected with reason codes."""
    assert code(verifier([]), signed()) == "IDN_AGENT_UNKNOWN"
    sus = verifier([rec(status=AgentStatus.SUSPENDED)])
    assert code(sus, signed()) == "IDN_AGENT_SUSPENDED"
    rev = verifier([rec(status=AgentStatus.REVOKED)])
    assert code(rev, signed()) == "IDN_AGENT_REVOKED"


@pytest.mark.req("ENV-04", "IDN-01")
def test_native_signature_required_and_must_verify() -> None:
    """Missing, foreign-key, and tampered signatures are rejected (S09)."""
    v = verifier([rec()])
    assert code(v, make_envelope()) == "IDN_SIGNATURE_MISSING"
    other = crypto.sign_envelope(make_envelope(), crypto.generate_private_key())
    assert code(v, other) == "IDN_SIGNATURE_INVALID"
    tampered = signed().model_copy(update={"envelope_id": "env-evil"})
    assert code(v, tampered) == "IDN_SIGNATURE_INVALID"
    assert code(verifier([rec(public_keys=[])]), signed()) == "IDN_SIGNATURE_INVALID"


def test_network_context_must_be_allowed() -> None:
    """An agent restricted to contexts is rejected elsewhere, and without a context."""
    v = verifier([rec(allowed_network_contexts=["internal"])])
    ok = signed(
        context=Context(agent_id="treasury-agent-1", mandate_ref="m", network_context="internal")
    )
    assert v.verify(ok).network_context == "internal"
    bad = signed(
        context=Context(agent_id="treasury-agent-1", mandate_ref="m", network_context="open")
    )
    assert code(v, bad) == "IDN_CONTEXT_NOT_ALLOWED"
    assert code(v, signed()) == "IDN_CONTEXT_NOT_ALLOWED"


@pytest.mark.req("ENV-04", "IDN-01")
def test_gateway_envelope_needs_trusted_gateway_and_observed_call() -> None:
    """Gateway origin: untrusted adapter or missing observed call is rejected."""
    h = canonical_hash(make_envelope().action.parameters)
    oc = ObservedCall(method="POST", target="/pay", params_hash=h)

    def gw(adapter: str, observed: ObservedCall | None) -> Any:
        return make_envelope(
            provenance=Provenance(origin="gateway", adapter_id=adapter, observed_call=observed)
        )

    v = verifier([rec(public_keys=[])])
    assert v.verify(gw("gw-1", oc)).origin == "gateway"
    assert code(v, gw("rogue", oc)) == "IDN_GATEWAY_UNTRUSTED"
    assert code(v, gw("gw-1", None)) == "IDN_GATEWAY_ATTESTATION_MISSING"


def test_authenticator_rejects_wrong_origin_strategy() -> None:
    """Strategies refuse envelopes of the other origin when used directly."""
    from arg.core.identity.authenticators import (
        AdapterSignatureAuthenticator,
        GatewayObservedAuthenticator,
    )

    gw_env = make_envelope(provenance=Provenance(origin="gateway", adapter_id="gw-1"))
    with pytest.raises(IdentityRejection, match="ORIGIN_UNSUPPORTED"):
        AdapterSignatureAuthenticator().authenticate(gw_env, rec())
    with pytest.raises(IdentityRejection, match="ORIGIN_UNSUPPORTED"):
        GatewayObservedAuthenticator(["gw-1"]).authenticate(signed(), rec())


@pytest.mark.req("IDN-03")
def test_file_registry_loads_yaml_and_rejects_duplicates(tmp_path: Path) -> None:
    """Closed-loop lookup from YAML; the shipped sample parses; duplicates are refused."""
    sample = FileRegistry(path=Path("config/agents.yaml"))
    found = sample.resolve("treasury-agent-1", None)
    assert found is not None and found.status is AgentStatus.ACTIVE
    p = tmp_path / "dup.yaml"
    p.write_text(
        "agents:\n"
        "  - {agent_id: a, agent_class: c, status: active, principal: p}\n"
        "  - {agent_id: a, agent_class: c, status: active, principal: p}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        FileRegistry(path=p)


@pytest.mark.req("IDN-04")
def test_composite_picks_authoritative_registry_by_context() -> None:
    """The same claim resolves differently per context; aliases are followed (S25)."""
    internal = FileRegistry(
        records=[rec("agent-int", principal="in-house.example", aliases={"network": "agent-net"})],
        registry_id="internal",
    )
    network = FileRegistry(
        records=[rec("agent-net", principal="network.example")], registry_id="network"
    )
    comp = CompositeRegistry(
        {"internal": internal, "network": network},
        authority={"open-net": "network"},
        default="internal",
    )
    closed = comp.resolve("agent-int", "bank-internal")
    assert closed is not None and closed.registry_id == "internal"
    via_alias = comp.resolve("agent-int", "open-net")
    assert via_alias is not None
    assert (via_alias.agent_id, via_alias.registry_id) == ("agent-net", "network")
    assert comp.resolve("agent-net", "open-net") is not None
    assert comp.resolve("ghost", "open-net") is None
    no_default = CompositeRegistry({"network": network}, {"open-net": "network"})
    assert no_default.resolve("agent-net", "other") is None


def test_composite_rejects_unknown_authority_reference() -> None:
    """Configuration naming a missing registry is an error at build time."""
    with pytest.raises(ValueError, match="unknown registries"):
        CompositeRegistry({}, {"x": "nope"})


@pytest.mark.req("IDN-01", "IDN-02")
def test_identity_rejection_occurs_before_controls_retrieval() -> None:
    """A rejected envelope never reaches the retrieve stage."""
    calls: list[str] = []

    class Retrieve(PipelineStage):
        """Spy standing in for controls retrieval."""

        def run(self, state: dict[str, Any]) -> dict[str, Any]:
            calls.append("retrieve")
            return state

    stages = [IdentityStage(verifier([])), Retrieve()]
    state: dict[str, Any] = {"envelope": signed()}
    with pytest.raises(IdentityRejection) as ei:
        for s in stages:
            state = s.run(state)
    assert ei.value.code == "IDN_AGENT_UNKNOWN" and calls == []

    ok_stages = [IdentityStage(verifier([rec()])), Retrieve()]
    state = {"envelope": signed()}
    for s in ok_stages:
        state = s.run(state)
    assert calls == ["retrieve"] and state["identity"].agent_id == "treasury-agent-1"


def test_runtime_wires_identity_from_config(tmp_path: Path) -> None:
    """The composition root builds registry -> authenticator -> verifier -> stage by role."""
    cfg = {
        "components": {
            "agent_registry": {"type": "file", "path": "config/agents.yaml"},
            "envelope_authenticator": {"type": "by-origin", "trusted_gateways": ["gw-1"]},
            "identity_verifier": {"type": "default"},
        },
        "pipeline": ["identity"],
    }
    rt = build_runtime(cfg)
    assert isinstance(rt.pipeline[0], IdentityStage)
    assert isinstance(rt.components["identity_verifier"], DefaultIdentityVerifier)
