"""Hand-rolled compact JWS (EdDSA) and the decision token service (INT-04, T-701, T-703)."""

import base64
import json
from datetime import timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.core import crypto
from arg.core.models import Action, TokenError
from arg.core.state.memory import InMemoryStateStore
from arg.core.tokens import jws
from arg.core.tokens.service import Ed25519TokenService, action_hash
from tests.core.factories import T0

ACTION = Action(type="payment.initiate", scope="account:ACME-001", parameters={"amount": 500})
ACT = action_hash(ACTION)


def b64(data: bytes) -> str:
    """Unpadded base64url."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def svc(**kw: Any) -> Ed25519TokenService:
    """A token service with a fresh key."""
    return Ed25519TokenService(private_key=crypto.generate_private_key(), **kw)


def issue(s: Ed25519TokenService, **kw: Any) -> str:
    """Issue a token for the default action/agent at T0."""
    args: dict[str, Any] = {
        "subject": "treasury-agent-1",
        "decision_id": "treasury-agent-1#1",
        "outcome": "auto_execute",
        "act_hash": ACT,
        "policy_version": "p" * 64,
        "at": T0,
    }
    args.update(kw)
    return s.issue(**args).token


def code(s: Ed25519TokenService, token: str, **kw: Any) -> str:
    """Return the TokenError code from verifying ``token``."""
    args: dict[str, Any] = {"act_hash": ACT, "agent_id": "treasury-agent-1", "at": T0}
    args.update(kw)
    with pytest.raises(TokenError) as ei:
        s.verify(token, **args)
    return ei.value.code


# ---- JWS layer --------------------------------------------------------------------------
def test_rfc8037_appendix_a_ed25519_signature() -> None:
    """RFC 8037 A.4: Ed25519 over ``BASE64URL({"alg":"EdDSA"}).BASE64URL(payload)``.

    Verifies our primitive against the published key pair, independent of our header typ.
    """
    d = base64.urlsafe_b64decode("nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A=")
    key = Ed25519PrivateKey.from_private_bytes(d)
    x = base64.urlsafe_b64decode("11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo=")
    from cryptography.hazmat.primitives import serialization

    assert (
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        == x
    )
    header = b64(b'{"alg":"EdDSA"}')
    payload = b64(b"Example of Ed25519 signing")
    assert header == "eyJhbGciOiJFZERTQSJ9"
    assert payload == "RXhhbXBsZSBvZiBFZDI1NTE5IHNpZ25pbmc"
    signing_input = f"{header}.{payload}".encode()
    sig = b64(key.sign(signing_input))
    assert sig == (
        "hgyY0il_MGCjP0JzlnLWG1PPOt7-09PGcvMg3AIbQR6dWbhijcNR4ki4iylGjg5BhVsPt9g7sVvpAr_MuM0KAg"
    )


def test_compact_structure_and_header() -> None:
    """Three base64url segments; header carries only alg/typ(/kid); signature is 64 bytes."""
    s = svc(kid="k1")
    h, p, sig = issue(s).split(".")
    header = json.loads(base64.urlsafe_b64decode(h + "=="))
    assert header == {"alg": "EdDSA", "kid": "k1", "typ": "arg-decision+jwt"}
    assert len(base64.urlsafe_b64decode(sig + "==")) == 64
    assert "=" not in issue(s)
    assert json.loads(base64.urlsafe_b64decode(p + "=="))["act_hash"] == ACT


def test_output_is_canonical_json() -> None:
    """Header and payload are RFC 8785: keys sorted, no whitespace."""
    h, p, _ = issue(svc()).split(".")
    for seg in (h, p):
        raw = base64.urlsafe_b64decode(seg + "==").decode()
        assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("bad", ["", "a.b", "a.b.c.d", "a..c", "....", "###.###.###"])
def test_malformed_structures_rejected(bad: str) -> None:
    """Wrong segment count or alphabet is TOK_MALFORMED."""
    assert code(svc(), bad) == "TOK_MALFORMED"


def test_algorithm_confusion_rejected() -> None:
    """alg none, HS256, RS256, and missing alg are refused before any verification."""
    s = svc()
    _, p, sig = issue(s).split(".")
    for alg in ("none", "HS256", "RS256", "ES256", "eddsa"):
        h = b64(json.dumps({"alg": alg, "typ": jws.TYP}).encode())
        assert code(s, f"{h}.{p}.{sig}") == "TOK_ALG_UNSUPPORTED", alg
    h = b64(json.dumps({"typ": jws.TYP}).encode())
    assert code(s, f"{h}.{p}.{sig}") == "TOK_ALG_UNSUPPORTED"


def test_header_hardening() -> None:
    """Wrong typ, unexpected/critical parameters, and non-object headers are refused."""
    s = svc()
    _, p, sig = issue(s).split(".")

    def tok(header: Any) -> str:
        return f"{b64(json.dumps(header).encode())}.{p}.{sig}"

    assert code(s, tok({"alg": "EdDSA", "typ": "JWT"})) == "TOK_MALFORMED"
    assert code(s, tok({"alg": "EdDSA", "typ": jws.TYP, "crit": ["x"], "x": 1})) == "TOK_MALFORMED"
    assert code(s, tok({"alg": "EdDSA", "typ": jws.TYP, "jku": "http://evil"})) == "TOK_MALFORMED"
    assert code(s, tok(["alg"])) == "TOK_MALFORMED"
    assert code(s, f"{b64(b'not json')}.{p}.{sig}") == "TOK_MALFORMED"


def test_base64url_must_be_canonical() -> None:
    """Padding, std-base64 characters, and non-zero trailing bits are refused (malleability)."""
    s = svc()
    h, p, sig = issue(s).split(".")
    assert code(s, f"{h}.{p}.{sig}=") == "TOK_MALFORMED"
    assert code(s, f"{h}.{p}.{sig[:-1]}+") == "TOK_MALFORMED"
    last = sig[-1]
    alt = "AQgw"[("AQgw".index(last) + 1) % 4] if last in "AQgw" else None
    if alt:  # the final char of a 64-byte sig encodes 4 bits + 2 zero bits
        assert code(s, f"{h}.{p}.{sig[:-1]}{alt}") in {"TOK_MALFORMED", "TOK_SIGNATURE_INVALID"}


# ---- service ----------------------------------------------------------------------------
@pytest.mark.req("INT-04")
def test_valid_token_claims() -> None:
    """Issue/verify round trip: all contract claims present and bound to the action."""
    s = svc(ttl_seconds=60, issuer="example-bank-arg")
    issued = s.issue(
        subject="treasury-agent-1",
        decision_id="d-1",
        outcome="observe",
        act_hash=ACT,
        policy_version="p" * 64,
        at=T0,
    )
    claims = s.verify(issued.token, act_hash=ACT, agent_id="treasury-agent-1", at=T0)
    assert claims == issued.claims
    assert (claims.iss, claims.outcome, claims.act_hash) == ("example-bank-arg", "observe", ACT)
    assert claims.exp - claims.iat == 60 and len(claims.jti) == 32
    assert issue(s) != issue(s)  # fresh jti per token


@pytest.mark.req("INT-04")
def test_expiry_boundaries() -> None:
    """Valid up to, but excluding, exp; not valid before iat."""
    s = svc(ttl_seconds=60)
    t = issue(s)
    assert s.verify(t, act_hash=ACT, agent_id="treasury-agent-1", at=T0 + timedelta(seconds=59))
    assert code(s, t, at=T0 + timedelta(seconds=60)) == "TOK_EXPIRED"
    assert code(s, t, at=T0 - timedelta(seconds=1)) == "TOK_NOT_YET_VALID"


@pytest.mark.req("INT-04")
def test_wrong_agent_and_altered_action_refused() -> None:
    """S12: altered parameters or another agent never verify."""
    s = svc()
    t = issue(s)
    assert code(s, t, agent_id="treasury-agent-2") == "TOK_SUBJECT_MISMATCH"
    altered = action_hash(
        Action(type="payment.initiate", scope="account:ACME-001", parameters={"amount": 50000})
    )
    assert code(s, t, act_hash=altered) == "TOK_ACTION_MISMATCH"
    assert action_hash(ACTION) == action_hash(ACTION.model_copy(update={"parent_envelope_id": "p"}))


@pytest.mark.req("INT-04")
def test_tampering_and_foreign_keys_refused() -> None:
    """Payload edits, signature edits, and a token from another key all fail signature check."""
    s, other = svc(), svc()
    h, p, sig = issue(s).split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    claims["exp"] += 10_000
    forged_p = b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    assert code(s, f"{h}.{forged_p}.{sig}") == "TOK_SIGNATURE_INVALID"
    flipped = bytearray(base64.urlsafe_b64decode(sig + "=="))
    flipped[0] ^= 1
    assert code(s, f"{h}.{p}.{b64(bytes(flipped))}") == "TOK_SIGNATURE_INVALID"
    assert code(s, issue(other)) == "TOK_SIGNATURE_INVALID"
    assert code(s, f"{h}.{p}.{b64(b'short')}") == "TOK_MALFORMED"


def test_claim_schema_and_issuer_enforced() -> None:
    """A correctly signed payload with wrong shape/issuer is still refused."""
    key = crypto.generate_private_key()
    s = Ed25519TokenService(private_key=key, issuer="arg")
    good = json.loads(
        base64.urlsafe_b64decode(issue(Ed25519TokenService(private_key=key)).split(".")[1] + "==")
    )
    assert code(s, jws.sign_compact({**good, "outcome": "deny"}, key)) == "TOK_CLAIMS_INVALID"
    assert code(s, jws.sign_compact({**good, "iat": "now"}, key)) == "TOK_CLAIMS_INVALID"
    assert code(s, jws.sign_compact({**good, "extra": 1}, key)) == "TOK_CLAIMS_INVALID"
    assert code(s, jws.sign_compact({**good, "iss": "evil"}, key)) == "TOK_ISSUER_MISMATCH"
    assert code(s, jws.sign_compact({k: v for k, v in good.items() if k != "jti"}, key)) == (
        "TOK_CLAIMS_INVALID"
    )


@pytest.mark.req("INT-04")
def test_s11_replay_refused_and_failed_verification_does_not_burn_token() -> None:
    """S11: second redemption is TOK_REPLAYED; a wrong-hash attempt leaves the token usable."""
    s, store = svc(), InMemoryStateStore()
    t = issue(s)
    kw: dict[str, Any] = {"agent_id": "treasury-agent-1", "at": T0, "state_store": store}
    with pytest.raises(TokenError) as bad:
        s.redeem(t, act_hash="0" * 64, **kw)
    assert bad.value.code == "TOK_ACTION_MISMATCH"
    assert s.redeem(t, act_hash=ACT, **kw).sub == "treasury-agent-1"
    with pytest.raises(TokenError) as replay:
        s.redeem(t, act_hash=ACT, **kw)
    assert replay.value.code == "TOK_REPLAYED"


def test_verify_only_service_and_configuration(tmp_path: Any) -> None:
    """A public-key service verifies but cannot issue; key loading and TTL validated."""
    key = crypto.generate_private_key()
    full = Ed25519TokenService(private_key=key)
    pub = tmp_path / "pub.pem"
    pub.write_bytes(crypto.public_key_pem(key.public_key()))
    priv = tmp_path / "priv.pem"
    priv.write_bytes(crypto.private_key_pem(key))
    verify_only = Ed25519TokenService(public_key_path=pub)
    assert verify_only.verify(issue(full), act_hash=ACT, agent_id="treasury-agent-1", at=T0)
    with pytest.raises(TokenError, match="TOK_NO_SIGNING_KEY"):
        issue(verify_only)
    assert Ed25519TokenService(private_key_path=priv).issuer == "arg"
    with pytest.raises(ValueError, match="key is required"):
        Ed25519TokenService()
    with pytest.raises(ValueError, match="ttl"):
        Ed25519TokenService(private_key=key, ttl_seconds=0)
    with pytest.raises(TokenError, match="TOK_CLAIMS_INVALID"):
        issue(full, outcome="deny")
    with pytest.raises(TokenError, match="TOK_CLAIMS_INVALID"):
        issue(full, act_hash="nothex")
