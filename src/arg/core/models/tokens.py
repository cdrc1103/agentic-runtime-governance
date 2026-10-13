"""Decision token models (INT-04)."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenClaims(BaseModel):
    """Claims of a decision token (contracts.md). Times are NumericDate seconds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    iss: str = Field(min_length=1)
    sub: str = Field(min_length=1)
    jti: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    outcome: Literal["auto_execute", "observe"]
    act_hash: str = Field(pattern="^[0-9a-f]{64}$")
    policy_version: str
    iat: int
    exp: int


@dataclass(frozen=True)
class IssuedToken:
    """A signed token and its claims."""

    token: str
    claims: TokenClaims


class TokenError(Exception):
    """Token rejected; ``code`` is a ``TOK_*`` reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Store reason ``code`` and ``detail``."""
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
