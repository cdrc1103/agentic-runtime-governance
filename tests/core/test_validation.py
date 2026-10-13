"""Completeness and coherence checks (ENV-03, SG-08, ENV-04 observed-call binding)."""

from datetime import timedelta
from typing import Any

import pytest

from arg.core.canonical import canonical_hash
from arg.core.models import Action, ActionTrace, Context, ObservedCall, Provenance
from arg.core.validation import ActionRequirements, validate_envelope
from tests.core.factories import make_envelope, step

REQS = {
    "payment.initiate": ActionRequirements(
        required_parameters=("amount", "currency"), trace_required=True
    ),
}


def run(env: Any, **kw: Any) -> list[str]:
    """Validate with default fixtures; return reason codes."""
    args: dict[str, Any] = {
        "supported_versions": {"1.0"},
        "requirements": REQS,
        "identity_claim": "treasury-agent-1",
        "mandate_exists": lambda ref: ref == "mandate-1",
    }
    args.update(kw)
    return validate_envelope(env, **args).codes


@pytest.mark.req("ENV-03")
def test_valid_envelope_passes() -> None:
    """A complete, coherent envelope has no issues."""
    assert run(make_envelope()) == []


@pytest.mark.req("ENV-03")
def test_completeness_failures() -> None:
    """Missing parameters, mandate, trace, or unknown action type are reported."""
    ctx = Context(agent_id="treasury-agent-1")
    act = Action(type="payment.initiate", scope="s", parameters={"amount": 1})
    env = make_envelope(action=act, context=ctx, action_trace=ActionTrace())
    assert run(env) == [
        "ENV_PARAMETER_MISSING",
        "ENV_MANDATE_MISSING",
        "ENV_TRACE_EMPTY",
    ]
    unknown = make_envelope(action=Action(type="wire.exotic", scope="s"))
    assert run(unknown) == ["ENV_ACTION_TYPE_UNKNOWN"]


@pytest.mark.req("ENV-03")
def test_coherence_failures() -> None:
    """Version, identity claim, timestamps, and mandate reference are cross-checked."""
    assert run(make_envelope(schema_version="9.9")) == ["ENV_VERSION_UNSUPPORTED"]
    assert run(make_envelope(), identity_claim="someone-else") == ["ENV_IDENTITY_MISMATCH"]
    assert run(make_envelope(), mandate_exists=lambda _: False) == ["ENV_MANDATE_UNRESOLVED"]
    backwards = make_envelope(action_trace=ActionTrace(steps=[step(1, 10), step(2, 0)]))
    assert run(backwards) == ["ENV_TRACE_NOT_MONOTONIC"]
    s = step(1)
    inverted = s.model_copy(update={"ended_at": s.started_at - timedelta(seconds=1)})
    assert run(make_envelope(action_trace=ActionTrace(steps=[inverted]))) == [
        "ENV_TRACE_STEP_INVERTED"
    ]


@pytest.mark.req("ENV-04")
def test_gateway_observed_call_must_match_declared_parameters() -> None:
    """Gateway origin: parameters must hash to the observed call, else forged/altered."""
    env = make_envelope()
    params_hash = canonical_hash(env.action.parameters)

    def gw(h: str | None) -> Any:
        oc = ObservedCall(method="POST", target="/pay", params_hash=h) if h else None
        return make_envelope(
            provenance=Provenance(origin="gateway", adapter_id="gw-1", observed_call=oc)
        )

    assert run(gw(params_hash)) == []
    assert run(gw("0" * 64)) == ["ENV_OBSERVED_CALL_MISMATCH"]
    assert run(gw(None)) == ["ENV_OBSERVED_CALL_MISSING"]
