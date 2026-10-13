"""Composition root: the only place components are wired together (constitution rule 14).

``build_runtime(config)`` builds every component named in ``runtime.yaml`` through the
factory. No other module imports a concrete implementation.
"""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import arg.builtins  # noqa: F401  (registers reference implementations)
from arg.core.decision.service import DecisionService
from arg.core.engine.disposition import DispositionEngine
from arg.core.factory import ComponentFactory
from arg.core.ports import (
    AgentRegistry,
    AnchorSink,
    AuditStore,
    ControlEvaluator,
    ControlsRepository,
    EnvelopeAuthenticator,
    EscalationQueue,
    IdentityVerifier,
    MandateResolver,
    PipelineStage,
    ResolutionPolicy,
    RiskCalibrator,
    StateStore,
    TokenService,
)
from arg.core.registry import ComponentRegistry, registry_for
from arg.service.auth import Authenticator

# Role name in runtime.yaml -> abstract class. Order = construction order, so a component
# may depend on any role listed before it (e.g. identity_verifier takes agent_registry).
ROLES: dict[str, type] = {
    "state_store": StateStore,
    "audit_store": AuditStore,
    "anchor_sink": AnchorSink,
    "agent_registry": AgentRegistry,
    "envelope_authenticator": EnvelopeAuthenticator,
    "identity_verifier": IdentityVerifier,
    "controls_repository": ControlsRepository,
    "mandate_resolver": MandateResolver,
    "risk_calibrator": RiskCalibrator,
    "resolution_policy": ResolutionPolicy,
    "token_service": TokenService,
    "escalation_queue": EscalationQueue,
    "authenticator": Authenticator,
}


@dataclass
class GovernanceRuntime:
    """Wired components and the ordered decision pipeline."""

    components: dict[str, Any] = field(default_factory=dict)
    evaluators: dict[str, ControlEvaluator] = field(default_factory=dict)
    pipeline: list[PipelineStage] = field(default_factory=list)
    decision_service: DecisionService | None = None


def _accepted_deps(cls: type, built: Mapping[str, Any]) -> dict[str, Any]:
    """Pick already-built components whose role name is a constructor parameter of ``cls``."""
    params = inspect.signature(cls).parameters
    return {name: obj for name, obj in built.items() if name in params}


def build_runtime(config: Mapping[str, Any]) -> GovernanceRuntime:
    """Build a ``GovernanceRuntime`` from a parsed ``runtime.yaml`` mapping."""
    runtime = GovernanceRuntime()
    section = config.get("components", {})
    unknown = set(section) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown component roles: {sorted(unknown)}")
    for role, base in ROLES.items():
        if role not in section:
            continue
        reg: ComponentRegistry[Any] = registry_for(base)
        cls = reg.get(section[role]["type"])
        factory: ComponentFactory[Any] = ComponentFactory(reg)
        runtime.components[role] = factory.create(
            section[role], **_accepted_deps(cls, runtime.components)
        )
    for name, block in config.get("evaluators", {}).items():
        runtime.evaluators[name] = ComponentFactory(registry_for(ControlEvaluator)).create(block)
    if "risk_calibrator" in runtime.components and "resolution_policy" in runtime.components:
        runtime.components["disposition_engine"] = DispositionEngine(
            runtime.evaluators,
            runtime.components["risk_calibrator"],
            runtime.components["resolution_policy"],
        )
    stage_reg = registry_for(PipelineStage)
    stage_factory: ComponentFactory[PipelineStage] = ComponentFactory(stage_reg)
    for stage in config.get("pipeline", []):
        block = {"type": stage} if isinstance(stage, str) else stage
        runtime.pipeline.append(
            stage_factory.create(
                block, **_accepted_deps(stage_reg.get(block["type"]), runtime.components)
            )
        )
    needed = ("state_store", "audit_store", "escalation_queue", "controls_repository")
    if runtime.pipeline and all(n in runtime.components for n in needed):
        service_cfg = config.get("service", {})
        runtime.decision_service = DecisionService(
            runtime.pipeline,
            runtime.components["state_store"],
            runtime.components["audit_store"],
            runtime.components["escalation_queue"],
            runtime.components["controls_repository"],
            **service_cfg,
        )
    return runtime


def load_config(path: Path) -> dict[str, Any]:
    """Read a ``runtime.yaml`` file."""
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return loaded
