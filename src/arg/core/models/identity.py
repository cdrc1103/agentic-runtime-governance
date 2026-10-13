"""Agent identity models (IDN-05, IDN-06)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AgentStatus(StrEnum):
    """Lifecycle status of a registry entry."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AgentRecord(BaseModel):
    """A registry entry (IDN-06)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=1)
    agent_class: str = Field(min_length=1)
    status: AgentStatus
    principal: str = Field(min_length=1)
    # PEM-encoded Ed25519 public keys of the agent instance(s) (SG-02).
    public_keys: list[str] = Field(default_factory=list)
    # Empty means "any context" (closed-loop registry).
    allowed_network_contexts: list[str] = Field(default_factory=list)
    # Identifier of this agent in other registries: registry name -> identifier (IDN-04).
    aliases: dict[str, str] = Field(default_factory=dict)
    # Set by the registry that returned the record, never read from files.
    registry_id: str = "default"


class IdentityBinding(BaseModel):
    """Confirmed binding of an action to a registered agent (IDN-05)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    agent_class: str
    principal: str
    registry_id: str
    origin: str
    network_context: str | None = None


class IdentityRejection(Exception):  # noqa: N818 - domain term, not an error class suffix
    """Identity verification failed; carries a reason code for the audit entry (IDN-02)."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Store the reason ``code`` (``IDN_*``) and a human-readable ``detail``."""
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
