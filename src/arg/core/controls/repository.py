"""File-bundle controls repository (CTL-01, CTL-04, CTL-07, T-303)."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from arg.core.controls.bundle import load_bundle
from arg.core.models import Action, Control, IdentityBinding
from arg.core.ports import ControlsRepository
from arg.core.registry import register


@register(ControlsRepository, "bundle")
class BundleControlsRepository(ControlsRepository):
    """Serves controls from a bundle directory; production mode is the safe default."""

    def __init__(self, path: str | Path, production: bool = True) -> None:
        """Load the bundle at ``path`` (fails closed on invalid or unapproved content)."""
        self._bundle = load_bundle(Path(path), production=production)

    @property
    def policy_version(self) -> str:
        """Manifest hash of the loaded bundle."""
        return self._bundle.manifest_hash

    def retrieve(
        self, identity: IdentityBinding, action: Action, at: datetime
    ) -> Sequence[Control]:
        """Controls whose scope and validity period match, ordered by id for determinism."""
        out = []
        for c in self._bundle.controls:
            scope = c.applies_to
            if scope.action_types and action.type not in scope.action_types:
                continue
            if scope.agent_classes and identity.agent_class not in scope.agent_classes:
                continue
            v = c.validity
            if (v.not_before and at < v.not_before) or (v.not_after and at > v.not_after):
                continue
            out.append(c)
        return sorted(out, key=lambda c: c.control_id)
