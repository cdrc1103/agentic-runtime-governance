"""RFC 8785 (JCS) canonical JSON and SHA-256 hashing (ENV-05, T-103).

Uses the vetted ``rfc8785`` library rather than a hand-rolled serialiser.
"""

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from pydantic import BaseModel


def to_jsonable(obj: BaseModel | Mapping[str, Any]) -> Any:
    """Return a plain JSON-compatible structure (datetimes become ISO strings)."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", exclude_none=False)
    return obj


def canonical_bytes(obj: BaseModel | Mapping[str, Any]) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``obj``."""
    return rfc8785.dumps(to_jsonable(obj))


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def canonical_hash(obj: BaseModel | Mapping[str, Any]) -> str:
    """Return ``sha256(canonical(obj))`` as hex."""
    return sha256_hex(canonical_bytes(obj))
