"""Rego evaluator: parity with built-in evaluators (needs ``opa`` on PATH; skipped otherwise)."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from arg.core.controls.dispatch import evaluate_controls
from arg.core.engine.evaluators import AuthorisationEvaluator, ExposureEvaluator
from arg.core.engine.rego import RegoControlEvaluator
from arg.core.models import Control, MandateLimits
from tests.core.test_engine import ID, MANDATE, ctl, ctx

pytestmark = [
    pytest.mark.rego,
    pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed"),
]
ROOT = Path("config/bundle")
REGO = RegoControlEvaluator(ROOT)


def view(evaluator: Any, control: Control, c: Any) -> list[tuple[str, Any, str]]:
    """Comparable (result, effect, reason) triples."""
    return [(f.result, f.effect, f.reason_code) for f in evaluator.evaluate(control, c)]


EXPOSURE = {"scope": "per_action", "amount_parameter": "amount", "limit": 10000}
AUTH = {"permitted_action_types": ["payment.initiate"], "max_delegation_depth": 1}


@pytest.mark.parametrize("amount", [1, 10000, 10000.5, 250000, "lots"])
def test_exposure_parity(amount: Any) -> None:
    """Built-in and Rego exposure controls give the same finding for each scenario."""
    esc = {"queue": "q", "timeout_seconds": 60, "reviewer_role": "r"}
    builtin = ctl(
        "e",
        "exposure",
        {"type": "exposure", **EXPOSURE},
        effect="escalate",
        escalation=esc,
    )
    rego = ctl(
        "e",
        "exposure",
        {
            "type": "rego",
            "policy": "rego/exposure.rego",
            "query": "data.arg.exposure.result",
            **EXPOSURE,
        },
        effect="escalate",
        escalation=esc,
    )
    c = ctx(amount)
    assert view(ExposureEvaluator(), builtin, c) == view(REGO, rego, c)


def test_authorisation_parity() -> None:
    """Authorisation scenarios agree between YAML-parameterised and Rego evaluators."""
    builtin = ctl("a", "authorisation", {"type": "authorisation", **AUTH})
    rego = ctl(
        "a",
        "authorisation",
        {
            "type": "rego",
            "policy": "rego/authorisation.rego",
            "query": "data.arg.authorisation.result",
            **AUTH,
        },
    )
    deep = MANDATE.model_copy(update={"depth": 2, "delegation_chain": ["x", "y"]})
    scenarios = [
        ctx(),
        ctx(mandate=None),
        ctx(mandate=MANDATE.model_copy(update={"permitted_actions": ["fx.trade"]})),
        ctx(mandate=MANDATE.model_copy(update={"principal": "bob.example"})),
        ctx(mandate=MANDATE.model_copy(update={"agent_id": "someone"})),
        ctx(mandate=deep),
        ctx(mandate=MANDATE.model_copy(update={"limits": MandateLimits(per_action=1)})),
    ]
    for c in scenarios:
        assert view(AuthorisationEvaluator(), builtin, c) == view(REGO, rego, c)
    assert ID.agent_id == "treasury-agent-1"


def test_rego_failures_fail_closed_through_dispatch() -> None:
    """Missing policy file, path escape, and missing binary all end in a Deny finding."""
    bad_file = ctl("r1", "custom", {"type": "rego", "policy": "rego/nope.rego", "query": "data.x"})
    escape = ctl(
        "r2", "custom", {"type": "rego", "policy": "../../pyproject.toml", "query": "data.x"}
    )
    no_bin = RegoControlEvaluator(ROOT, opa_binary="opa-does-not-exist")
    ok = ctl(
        "r3",
        "custom",
        {
            "type": "rego",
            "policy": "rego/exposure.rego",
            "query": "data.arg.exposure.result",
            **EXPOSURE,
        },
    )
    c = ctx()
    out = evaluate_controls([bad_file, escape], {"rego": REGO}, c)
    assert [f.reason_code for f in out] == ["CTL_EVALUATOR_ERROR"] * 2
    assert evaluate_controls([ok], {"rego": no_bin}, c)[0].reason_code == "CTL_EVALUATOR_ERROR"
