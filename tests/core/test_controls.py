"""Controls bundle, repository, mandates, and evaluator dispatch (CTL-01..07)."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from arg.core import crypto
from arg.core.controls.bundle import load_bundle
from arg.core.controls.dispatch import evaluate_controls
from arg.core.controls.mandates import FileMandateResolver
from arg.core.controls.repository import BundleControlsRepository
from arg.core.models import (
    Action,
    Control,
    ControlsLoadError,
    Effect,
    EvaluationContext,
    Finding,
    IdentityBinding,
    Mandate,
    MandateLimits,
    MandateRejection,
)
from arg.core.ports import ControlEvaluator
from tests.core.factories import T0, make_envelope

CTRL: dict[str, Any] = {
    "control_id": "c-1",
    "version": 1,
    "source": "policy",
    "category": "exposure",
    "logic": {"type": "exposure", "limit": 100},
    "effect": "deny",
    "owner": "risk",
    "review_status": "approved",
}
ID = IdentityBinding(
    agent_id="treasury-agent-1",
    agent_class="treasury",
    principal="alice.example",
    registry_id="default",
    origin="native",
)
PAY = Action(type="payment.initiate", scope="s")


def bundle(tmp_path: Path, *controls: dict[str, Any]) -> Path:
    """Write controls into a bundle directory."""
    d = tmp_path / "controls"
    d.mkdir(parents=True, exist_ok=True)
    for c in controls:
        (d / f"{c['control_id']}.yaml").write_text(yaml.safe_dump(c))
    return tmp_path


@pytest.mark.req("CTL-04")
def test_control_model_requires_logic_type_and_escalation_block() -> None:
    """A control encodes decision logic and, for escalate, its routing and timeout."""
    with pytest.raises(ValueError, match="logic.type"):
        Control(**{**CTRL, "logic": {"limit": 1}})
    with pytest.raises(ValueError, match="escalation"):
        Control(**{**CTRL, "effect": "escalate"})
    ok = Control(
        **{
            **CTRL,
            "effect": "escalate",
            "escalation": {"queue": "q", "timeout_seconds": 60, "reviewer_role": "r"},
        }
    )
    assert ok.escalation is not None and ok.escalation.on_timeout == "block"


@pytest.mark.req("CTL-01", "CTL-02", "CTL-05")
def test_sample_bundle_loads_with_categories_and_kinds() -> None:
    """The shipped sample bundle loads in production mode; categories and sources parse."""
    b = load_bundle(Path("config"), production=True)
    cats = {c.category.value for c in b.controls}
    assert {"authorisation", "exposure"} <= cats
    assert all(c.source.value in {"policy", "regulatory", "product", "mandate"} for c in b.controls)
    assert Control(**{**CTRL, "kind": "ai_specific"}).kind.value == "ai_specific"


@pytest.mark.req("CTL-07", "DSP-04")
def test_production_mode_refuses_unapproved_controls(tmp_path: Path) -> None:
    """S14: a draft control blocks the production load; development mode accepts it."""
    root = bundle(tmp_path, CTRL, {**CTRL, "control_id": "c-2", "review_status": "draft"})
    with pytest.raises(ControlsLoadError, match=r"unapproved.*c-2"):
        load_bundle(root, production=True)
    assert len(load_bundle(root, production=False).controls) == 2


@pytest.mark.req("CTL-07")
def test_manifest_hash_changes_with_any_file_and_is_stable(tmp_path: Path) -> None:
    """Policy version is a content hash: stable on reload, different after an edit."""
    root = bundle(tmp_path, CTRL)
    h1 = load_bundle(root).manifest_hash
    assert load_bundle(root).manifest_hash == h1
    (root / "controls" / "c-1.yaml").write_text(
        yaml.safe_dump({**CTRL, "logic": {"type": "exposure", "limit": 999}})
    )
    assert load_bundle(root).manifest_hash != h1
    (root / "calibration.yaml").write_text("x: 1\n")
    assert load_bundle(root).manifest_hash != h1


def test_loader_rejects_invalid_empty_and_duplicate(tmp_path: Path) -> None:
    """Invalid schema, empty bundle, and duplicate ids are load errors."""
    with pytest.raises(ControlsLoadError, match="no controls"):
        load_bundle(tmp_path)
    bad = bundle(tmp_path / "bad", {**CTRL, "surprise": 1})
    with pytest.raises(ControlsLoadError, match="invalid control"):
        load_bundle(bad)
    dup = tmp_path / "dup" / "controls"
    dup.mkdir(parents=True)
    for n in ("a", "b"):
        (dup / f"{n}.yaml").write_text(yaml.safe_dump(CTRL))
    with pytest.raises(ControlsLoadError, match="duplicate"):
        load_bundle(tmp_path / "dup")


@pytest.mark.req("CTL-01", "CTL-04")
def test_repository_selects_by_action_class_and_validity(tmp_path: Path) -> None:
    """Retrieval filters on action type, agent class, and validity period."""
    root = bundle(
        tmp_path,
        {**CTRL, "control_id": "b-any"},
        {**CTRL, "control_id": "a-pay", "applies_to": {"action_types": ["payment.initiate"]}},
        {**CTRL, "control_id": "c-fx", "applies_to": {"action_types": ["fx.trade"]}},
        {**CTRL, "control_id": "d-ops", "applies_to": {"agent_classes": ["ops"]}},
        {
            **CTRL,
            "control_id": "e-future",
            "validity": {"not_before": (T0 + timedelta(days=1)).isoformat()},
        },
        {
            **CTRL,
            "control_id": "f-expired",
            "validity": {"not_after": (T0 - timedelta(days=1)).isoformat()},
        },
    )
    repo = BundleControlsRepository(root)
    assert [c.control_id for c in repo.retrieve(ID, PAY, T0)] == ["a-pay", "b-any"]
    assert "e-future" in [c.control_id for c in repo.retrieve(ID, PAY, T0 + timedelta(days=2))]
    assert repo.policy_version == load_bundle(root).manifest_hash


# ---- mandates -------------------------------------------------------------------------
PKEY = crypto.generate_private_key()
PPEM = crypto.public_key_pem(PKEY.public_key()).decode()


def mandate(**kw: Any) -> Mandate:
    """A valid signed mandate for treasury-agent-1, valid for 30 days around T0."""
    base: dict[str, Any] = {
        "mandate_id": "mandate-1",
        "principal": "alice.example",
        "agent_id": "treasury-agent-1",
        "permitted_actions": ["payment.initiate"],
        "limits": MandateLimits(per_action=5000),
        "not_before": T0 - timedelta(days=1),
        "not_after": T0 + timedelta(days=30),
    }
    base.update(kw)
    return crypto.sign_mandate(Mandate(**base), PKEY)


def resolver(*ms: Mandate, **kw: Any) -> FileMandateResolver:
    """Resolver holding ``ms`` and the principal's key."""
    return FileMandateResolver(mandates=ms, principals={"alice.example": PPEM}, **kw)


def reject(
    r: FileMandateResolver, ref: str = "mandate-1", agent: str = "treasury-agent-1", at: Any = T0
) -> str:
    """Return the rejection code."""
    with pytest.raises(MandateRejection) as ei:
        r.resolve(ref, agent, at)
    return ei.value.code


@pytest.mark.req("CTL-03", "CTL-04")
def test_valid_mandate_resolves() -> None:
    """A signed, in-validity, unrevoked, shallow mandate resolves for its agent."""
    assert (
        resolver(mandate()).resolve("mandate-1", "treasury-agent-1", T0).limits.per_action == 5000
    )


@pytest.mark.req("CTL-03", "CTL-04")
def test_mandate_rejections() -> None:
    """S04: expiry, not-yet-valid, revocation, depth, agent, signature, principal failures."""
    r = resolver(mandate())
    assert reject(r, "nope") == "MND_NOT_FOUND"
    assert reject(r, agent="other") == "MND_AGENT_MISMATCH"
    assert reject(r, at=T0 + timedelta(days=31)) == "MND_EXPIRED"
    assert reject(r, at=T0 - timedelta(days=2)) == "MND_NOT_YET_VALID"
    assert reject(resolver(mandate(revocation_ref="rev-1"), revoked=["rev-1"])) == "MND_REVOKED"
    deep = mandate(depth=2, delegation_chain=["bob.example", "carol.example"])
    assert reject(resolver(deep, max_depth=1)) == "MND_DEPTH_EXCEEDED"
    assert resolver(deep, max_depth=2).resolve("mandate-1", "treasury-agent-1", T0).depth == 2
    assert reject(resolver(mandate(depth=1))) == "MND_DEPTH_INCOHERENT"
    assert reject(resolver(mandate(not_after=T0 - timedelta(days=5)))) == "MND_VALIDITY_INVERTED"
    unsigned = Mandate(**{**mandate().model_dump(), "signature": None})
    assert reject(resolver(unsigned)) == "MND_SIGNATURE_INVALID"
    forged = crypto.sign_mandate(mandate(), crypto.generate_private_key())
    assert reject(resolver(forged)) == "MND_SIGNATURE_INVALID"
    assert reject(FileMandateResolver(mandates=[mandate()])) == "MND_PRINCIPAL_UNKNOWN"


@pytest.mark.req("CTL-03")
def test_agent_cannot_widen_a_mandate() -> None:
    """S17: changing any signed field (limits) invalidates the principal's signature."""
    m = mandate()
    widened = m.model_copy(update={"limits": MandateLimits(per_action=10_000_000)})
    assert reject(resolver(widened)) == "MND_SIGNATURE_INVALID"
    wider_actions = m.model_copy(update={"permitted_actions": ["payment.initiate", "fx.trade"]})
    assert reject(resolver(wider_actions)) == "MND_SIGNATURE_INVALID"


def test_resolver_loads_file_and_rejects_duplicates(tmp_path: Path) -> None:
    """File form parses; duplicate mandate ids are refused."""
    m = mandate()
    p = tmp_path / "m.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "mandates": [m.model_dump(mode="json")],
                "principals": {"alice.example": PPEM},
                "revoked": [],
            }
        )
    )
    assert (
        FileMandateResolver(path=p).resolve("mandate-1", "treasury-agent-1", T0).mandate_id
        == "mandate-1"
    )
    with pytest.raises(ValueError, match="duplicate"):
        FileMandateResolver(mandates=[m, m])
    bad_key = FileMandateResolver(
        mandates=[m],
        principals={"alice.example": crypto.private_key_pem(PKEY).decode()},
    )
    assert reject(bad_key) == "MND_PRINCIPAL_KEY_INVALID"
    rsa_like = FileMandateResolver(mandates=[m], principals={"alice.example": "not a pem"})
    assert reject(rsa_like) == "MND_PRINCIPAL_KEY_INVALID"


# ---- evaluator dispatch ----------------------------------------------------------------
class Fires(ControlEvaluator):
    """Test evaluator that always fires the control's effect."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Fire."""
        return [Finding(control.control_id, control.version, "fire", control.effect, "T_FIRE")]


class Boom(ControlEvaluator):
    """Test evaluator that crashes."""

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Raise."""
        raise RuntimeError("boom")


@pytest.mark.req("DSP-01")
def test_dispatch_by_logic_type_and_fail_closed() -> None:
    """Evaluators are chosen by logic.type; missing or crashing ones yield a Deny finding."""
    ctx = EvaluationContext(envelope=make_envelope(), identity=ID)
    fires = Control(**CTRL)
    other = Control(**{**CTRL, "control_id": "c-2", "logic": {"type": "unknown"}})
    boom = Control(**{**CTRL, "control_id": "c-3", "logic": {"type": "boom"}, "effect": "observe"})
    out = evaluate_controls([fires, other, boom], {"exposure": Fires(), "boom": Boom()}, ctx)
    assert [(f.control_id, f.effect, f.reason_code) for f in out] == [
        ("c-1", Effect.DENY, "T_FIRE"),
        ("c-2", Effect.DENY, "CTL_NO_EVALUATOR"),
        ("c-3", Effect.DENY, "CTL_EVALUATOR_ERROR"),
    ]


@pytest.mark.req("CTL-06")
def test_every_control_names_an_owner() -> None:
    """Configuration ownership (risk and compliance) is recorded on each control."""
    without_owner = {k: v for k, v in CTRL.items() if k != "owner"}
    with pytest.raises(ValueError, match="owner"):
        Control(**without_owner)
    assert Control(**CTRL).owner == "risk"
