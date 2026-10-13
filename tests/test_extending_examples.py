"""The worked examples in docs/extending.md really run (and pass the shared contracts)."""

from pathlib import Path
from typing import Any

import pytest

from arg.core.controls.dispatch import evaluate_controls
from arg.core.models import Action, Control, EvaluationContext, IdentityBinding
from arg.core.ports import AuditStore, ControlEvaluator
from arg.core.registry import registry_for
from docs.examples.beneficiary_blocklist import BeneficiaryBlocklistEvaluator
from docs.examples.jsonl_audit_store import JsonlAuditStore
from tests.core.audit_factories import content
from tests.core.factories import T0, make_envelope

ID = IdentityBinding(agent_id="a", agent_class="c", principal="p", registry_id="r", origin="native")


def test_blocklist_evaluator_registers_and_fires() -> None:
    """The custom evaluator is discoverable by name and enforces its list."""
    assert registry_for(ControlEvaluator).get("blocklist") is BeneficiaryBlocklistEvaluator
    control = Control.model_validate(
        {
            "control_id": "blk-1",
            "version": 1,
            "source": "regulatory",
            "category": "custom",
            "logic": {"type": "blocklist", "blocked": ["vendor-666"]},
            "effect": "deny",
            "owner": "compliance",
            "review_status": "approved",
        }
    )

    def ctx(beneficiary: Any) -> EvaluationContext:
        env = make_envelope(
            action=Action(
                type="payment.initiate", scope="s", parameters={"beneficiary": beneficiary}
            )
        )
        return EvaluationContext(env, ID, T0)

    ev = {"blocklist": BeneficiaryBlocklistEvaluator()}

    def codes(c: Any) -> list[str]:
        return [f.reason_code for f in evaluate_controls([control], ev, ctx(c))]

    assert codes("vendor-17") == [""]
    assert codes("vendor-666") == ["BLK_BENEFICIARY_BLOCKED"]
    assert codes(None) == ["BLK_BENEFICIARY_UNREADABLE"]


def test_jsonl_audit_store_inherits_chain_and_verification(tmp_path: Path) -> None:
    """The custom store gets chaining, conflict detection and verify for free."""
    assert registry_for(AuditStore).get("jsonl") is JsonlAuditStore
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    e1 = store.append(content("a-1"), None)
    e2 = store.append(content("a-1", "deny"), e1.entry_hash)
    assert e2.prev_hash == e1.entry_hash and store.verify("a-1").ok
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    (tmp_path / "audit.jsonl").write_text(
        "\n".join([lines[0].replace('"auto_execute"', '"deny"'), lines[1]]) + "\n"
    )
    assert store.verify("a-1").code == "AUD_ENTRY_MODIFIED"
    with pytest.raises(Exception, match="head is"):
        store.append(content("a-1"), None)
