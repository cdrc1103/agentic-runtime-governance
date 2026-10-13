"""Pipeline stage: identity runs first, before any controls retrieval (IDN-01, IDN-02)."""

from typing import Any

from arg.core.ports import IdentityVerifier, PipelineStage
from arg.core.registry import register


@register(PipelineStage, "identity")
class IdentityStage(PipelineStage):
    """Bind ``state["envelope"]`` to a registered agent; rejection propagates (fail closed)."""

    def __init__(self, identity_verifier: IdentityVerifier) -> None:
        """Inject the verifier."""
        self.verifier = identity_verifier

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Add ``state["identity"]``; raise ``IdentityRejection`` on failure."""
        return {**state, "identity": self.verifier.verify(state["envelope"])}
