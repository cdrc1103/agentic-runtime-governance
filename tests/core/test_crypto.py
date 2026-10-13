"""Ed25519 helpers and envelope signing (ENV-04)."""

from pathlib import Path

import pytest

from arg.core import crypto
from arg.core.models import Action
from tests.core.factories import make_envelope


def test_sign_verify_roundtrip_and_rejections() -> None:
    """Valid signatures verify; altered payloads, wrong keys, garbage do not."""
    key, other = crypto.generate_private_key(), crypto.generate_private_key()
    sig = crypto.sign(key, b"payload")
    assert crypto.verify(key.public_key(), b"payload", sig)
    assert not crypto.verify(key.public_key(), b"payloaD", sig)
    assert not crypto.verify(other.public_key(), b"payload", sig)
    assert not crypto.verify(key.public_key(), b"payload", "!!not-base64!!")


def test_keys_load_from_file_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PEM keys round-trip through a file and an environment variable."""
    key = crypto.generate_private_key()
    priv = tmp_path / "k.pem"
    priv.write_bytes(crypto.private_key_pem(key))
    pub_pem = crypto.public_key_pem(key.public_key())
    monkeypatch.setenv("ARG_TEST_PUB", pub_pem.decode())
    loaded = crypto.load_private_key(path=priv)
    pub = crypto.load_public_key(env="ARG_TEST_PUB")
    assert crypto.verify(pub, b"x", crypto.sign(loaded, b"x"))
    with pytest.raises(ValueError, match="exactly one"):
        crypto.load_public_key()
    with pytest.raises(ValueError, match="not set"):
        crypto.load_public_key(env="ARG_TEST_MISSING")


def test_load_rejects_wrong_key_type(tmp_path: Path) -> None:
    """A non-Ed25519 PEM is refused."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    p = tmp_path / "rsa.pem"
    p.write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(ValueError, match="Ed25519"):
        crypto.load_private_key(path=p)
    q = tmp_path / "rsa.pub"
    q.write_bytes(
        rsa_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    with pytest.raises(ValueError, match="Ed25519"):
        crypto.load_public_key(path=q)


@pytest.mark.req("ENV-04")
def test_signed_envelope_verifies_and_tampering_is_detected() -> None:
    """A native envelope is authenticated against the adapter key, not taken on trust."""
    key = crypto.generate_private_key()
    env = crypto.sign_envelope(make_envelope(), key)
    assert env.provenance.signature
    assert crypto.verify_envelope_signature(env, key.public_key())
    tampered = env.model_copy(
        update={
            "action": Action(
                type="payment.initiate", scope="account:ACME-001", parameters={"amount": 999999}
            )
        }
    )
    assert not crypto.verify_envelope_signature(tampered, key.public_key())
    assert not crypto.verify_envelope_signature(make_envelope(), key.public_key())  # unsigned
    other = crypto.generate_private_key()
    assert not crypto.verify_envelope_signature(env, other.public_key())
