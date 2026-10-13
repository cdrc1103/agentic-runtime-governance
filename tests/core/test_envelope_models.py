"""Envelope model, canonical hashing, and schema export."""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from arg.core.canonical import canonical_bytes, canonical_hash
from arg.core.models import SCHEMA_VERSION, Action, Envelope
from scripts.export_schemas import OUT, render
from tests.core.factories import make_envelope

RFC8785_SAMPLE_IN = (
    '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],'
    '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
    '"literals":[null,true,false]}'
)
RFC8785_SAMPLE_OUT = (
    '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
    '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
)


@pytest.mark.req("ENV-02")
def test_envelope_carries_action_trace_and_context() -> None:
    """The three information classes of ENV-02 are all present and typed."""
    env = make_envelope()
    assert env.action.type and env.action.scope and env.action.parameters
    assert [s.step_id for s in env.action_trace.steps] == ["s1", "s2"]
    assert env.context.agent_id and env.context.mandate_ref and env.context.signals
    assert env.provenance.origin == "native"


def test_envelope_rejects_unknown_fields_naive_times_and_empty_id() -> None:
    """Strict schema: extras, naive datetimes, and blank identifiers are refused."""
    good = make_envelope().model_dump()
    with pytest.raises(ValidationError):
        Envelope(**good, surprise=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Envelope(**{**good, "envelope_id": ""})
    with pytest.raises(ValidationError):
        Envelope(**{**good, "created_at": "2026-01-05T09:00:00"})
    with pytest.raises(ValidationError):
        Action(type="x", scope="y", unexpected=True)  # type: ignore[call-arg]


@pytest.mark.req("ENV-05")
def test_schema_version_is_declared() -> None:
    """Envelopes are versioned (ENV-05)."""
    assert make_envelope().schema_version == SCHEMA_VERSION == "1.0"


@pytest.mark.req("ENV-05")
def test_canonicalisation_matches_rfc8785_sample() -> None:
    """The RFC 8785 example input canonicalises to the published output."""
    assert canonical_bytes(json.loads(RFC8785_SAMPLE_IN)).decode() == RFC8785_SAMPLE_OUT


@pytest.mark.req("ENV-05")
def test_hash_is_independent_of_key_order_and_stable() -> None:
    """Same content in any key order hashes identically; a change alters the hash."""
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    env = make_envelope()
    assert canonical_hash(env) == canonical_hash(make_envelope())
    assert canonical_hash(env) != canonical_hash(make_envelope(envelope_id="env-002"))


@pytest.mark.req("ENV-05")
@given(
    st.dictionaries(
        st.text(max_size=8),
        st.one_of(
            st.integers(-(2**53 - 1), 2**53 - 1), st.text(max_size=8), st.booleans(), st.none()
        ),
        max_size=6,
    )
)
def test_hash_deterministic_under_reordering(d: dict[str, object]) -> None:
    """Property: reversing insertion order never changes the hash."""
    assert canonical_hash(d) == canonical_hash(dict(reversed(list(d.items()))))


@pytest.mark.req("ENV-05")
def test_integers_beyond_safe_range_are_refused() -> None:
    """JCS cannot represent them exactly; hashing fails loudly rather than silently rounding."""
    with pytest.raises(Exception, match="safe integer"):
        canonical_bytes({"amount": 2**53})


def test_exported_schema_has_no_drift() -> None:
    """Committed ``schemas/`` equals the schema generated from the models (T-102)."""
    for name, text in render().items():
        assert (OUT / name).read_text() == text, f"run scripts/export_schemas.py ({name})"
    assert Path(OUT / "envelope.schema.json").exists()
