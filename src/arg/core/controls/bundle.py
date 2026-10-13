"""Controls bundle loading with manifest hash (CTL-07, T-301, T-302).

Layout: ``<bundle>/controls/*.yaml`` (one control per file); other files (e.g. the
calibration file of Phase 4) live beside it. The manifest hash covers every YAML file in the
bundle, so editing any of them changes the policy version.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from arg.core.canonical import canonical_hash, sha256_hex
from arg.core.models import Control, ControlsLoadError, ReviewStatus


@dataclass(frozen=True)
class ControlBundle:
    """Loaded controls plus the manifest hash that identifies this policy version."""

    controls: tuple[Control, ...]
    manifest_hash: str


def manifest_hash(root: Path) -> str:
    """Hash of ``[{path, sha256}]`` over all YAML files under ``root``, sorted by path."""
    entries = [
        {"path": p.relative_to(root).as_posix(), "sha256": sha256_hex(p.read_bytes())}
        for p in sorted(root.rglob("*.yaml"))
    ]
    return canonical_hash({"files": entries})


def load_bundle(root: Path, *, production: bool = True) -> ControlBundle:
    """Load and validate a bundle; in production mode refuse any non-approved control."""
    files = sorted((root / "controls").glob("*.yaml"))
    if not files:
        raise ControlsLoadError(f"no controls found in {root / 'controls'}")
    controls: list[Control] = []
    for f in files:
        try:
            controls.append(Control(**(yaml.safe_load(f.read_text()) or {})))
        except (ValidationError, TypeError, ValueError) as exc:
            raise ControlsLoadError(f"{f.name}: invalid control: {exc}") from exc
    ids = [c.control_id for c in controls]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ControlsLoadError(f"duplicate control_id: {dupes}")
    if production:
        unapproved = [
            c.control_id for c in controls if c.review_status is not ReviewStatus.APPROVED
        ]
        if unapproved:
            raise ControlsLoadError(f"production mode refuses unapproved controls: {unapproved}")
    return ControlBundle(tuple(controls), manifest_hash(root))
