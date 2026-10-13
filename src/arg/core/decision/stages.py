"""Pipeline stages mirroring the action lifecycle (DSP-05, INT-05, T-602).

Audit is deliberately not a configurable stage: AUD-01 requires an entry on every path,
including rejections, so ``DecisionService`` always performs it.
State keys: raw, claimed_agent_id, now, envelope, identity, mandate, controls, snapshot,
specs, disposition, reserved.
"""

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from arg.core.engine.disposition import DispositionEngine
from arg.core.engine.reservations import counter_specs
from arg.core.models import (
    Envelope,
    EvaluationContext,
    Outcome,
    Reservation,
    StageRejection,
)
from arg.core.ports import (
    ControlsRepository,
    MandateResolver,
    PipelineStage,
    StateStore,
)
from arg.core.registry import register
from arg.core.validation import ActionRequirements, validate_envelope


@register(PipelineStage, "validate")
class ValidateStage(PipelineStage):
    """Schema, completeness and coherence checks (ENV-03, SG-08)."""

    def __init__(
        self,
        mandate_resolver: MandateResolver,
        requirements: dict[str, dict[str, Any]] | None = None,
        supported_versions: list[str] | None = None,
    ) -> None:
        """``requirements``: action type -> ActionRequirements fields (YAML-friendly)."""
        self.resolver = mandate_resolver
        self.requirements = {
            k: ActionRequirements(
                required_parameters=tuple(v.get("required_parameters", ())),
                trace_required=v.get("trace_required", False),
                mandate_required=v.get("mandate_required", True),
            )
            for k, v in (requirements or {}).items()
        }
        self.supported = set(supported_versions or ["1.0"])

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Parse the raw envelope and validate it; raise ``StageRejection`` on failure."""
        try:
            envelope = Envelope.model_validate(state["raw"])
        except ValidationError as exc:
            raise StageRejection(
                "validation", "ENV_SCHEMA_INVALID", str(exc.error_count())
            ) from exc
        claim = state.get("claimed_agent_id") or envelope.context.agent_id
        result = validate_envelope(
            envelope,
            supported_versions=self.supported,
            requirements=self.requirements,
            identity_claim=claim,
            mandate_exists=self.resolver.exists,
        )
        if not result.ok:
            raise StageRejection("validation", result.issues[0].code, result.issues[0].detail)
        return {**state, "envelope": envelope}


@register(PipelineStage, "mandate")
class MandateStage(PipelineStage):
    """Resolve and validate the referenced mandate (CTL-03, CTL-04)."""

    def __init__(self, mandate_resolver: MandateResolver) -> None:
        """Inject the resolver."""
        self.resolver = mandate_resolver

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Add ``mandate`` (None if the envelope names none); rejections propagate."""
        ref = state["envelope"].context.mandate_ref
        if ref is None:
            return {**state, "mandate": None}
        mandate = self.resolver.resolve(ref, state["identity"].agent_id, state["now"])
        return {**state, "mandate": mandate}


@register(PipelineStage, "retrieve")
class RetrieveStage(PipelineStage):
    """Fetch applicable controls and take the counter snapshot (CTL-01, SG-04)."""

    def __init__(self, controls_repository: ControlsRepository, state_store: StateStore) -> None:
        """Inject repository and state store."""
        self.repo = controls_repository
        self.store = state_store

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Add ``controls``, ``specs`` and ``snapshot``."""
        env, identity, now = state["envelope"], state["identity"], state["now"]
        controls = self.repo.retrieve(identity, env.action, now)
        probe = EvaluationContext(env, identity, now, state.get("mandate"))
        specs = counter_specs(controls, probe)
        snapshot = {s.key: self.store.usage(s.key, s.window_seconds, now) for s in specs}
        return {**state, "controls": controls, "specs": specs, "snapshot": snapshot}


@register(PipelineStage, "evaluate")
class EvaluateStage(PipelineStage):
    """Run the disposition engine (DSP-01..07)."""

    def __init__(self, disposition_engine: DispositionEngine) -> None:
        """Inject the engine."""
        self.engine = disposition_engine

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Add ``disposition``."""
        env = state["envelope"]
        disposition = self.engine.evaluate(
            env,
            state["identity"],
            state["controls"],
            state["snapshot"],
            env.context.signals,
            at=state["now"],
            mandate=state.get("mandate"),
        )
        return {**state, "disposition": disposition}


@register(PipelineStage, "reserve")
class ReserveStage(PipelineStage):
    """Reserve exposure/rate when the action proceeds (SG-04); all or nothing."""

    def __init__(self, state_store: StateStore) -> None:
        """Inject the state store."""
        self.store = state_store

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Reserve for Auto-Execute/Observe; a refused reservation becomes a rejection."""
        if state["disposition"].outcome not in (Outcome.AUTO_EXECUTE, Outcome.OBSERVE):
            return {**state, "reserved": []}
        made: list[Reservation] = []
        now: datetime = state["now"]
        for spec in state["specs"]:
            if not self.store.reserve(spec.key, spec.amount, spec.limit, spec.window_seconds, now):
                for done in made:
                    self.store.release(done.key, done.amount, done.window_seconds, now)
                raise StageRejection("engine", "STATE_RESERVATION_REFUSED", spec.key)
            made.append(spec)
        return {**state, "reserved": made}
