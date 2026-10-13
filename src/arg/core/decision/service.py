"""The decision service: validate → identity → mandate → retrieve → evaluate → reserve →
audit → respond (Action Lifecycle, T-602, T-603).

Guarantees: every path writes an audit entry (AUD-01); any internal error yields Deny
(INT-05); a duplicate ``envelope_id`` returns the original decision without re-reserving
(ENV-06); reservation and audit succeed together or the reservation is released (SG-04).
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from arg.core.audit.builder import (
    content_for_reviewer,
    content_from_disposition,
    content_from_rejection,
)
from arg.core.models import (
    AuditConflict,
    AuditContent,
    AuditEntry,
    DecisionResponse,
    EscalationError,
    EscalationRecord,
    EscalationState,
    IdentityBinding,
    IdentityRejection,
    MandateRejection,
    Outcome,
    Reservation,
    StageRejection,
)
from arg.core.ports import (
    AuditStore,
    ControlsRepository,
    EscalationQueue,
    PipelineStage,
    StateStore,
)


@dataclass(frozen=True)
class ResolutionResult:
    """A reviewer resolution: the updated record and, for modify, the child decision."""

    escalation: EscalationRecord
    child: DecisionResponse | None = None


def system_clock() -> datetime:
    """Wall clock in UTC (the only place core reads the time)."""
    return datetime.now(UTC)


class DecisionService:
    """Runs the pipeline and owns audit, idempotency, escalation and fail-closed handling."""

    def __init__(
        self,
        stages: Sequence[PipelineStage],
        state_store: StateStore,
        audit_store: AuditStore,
        escalation_queue: EscalationQueue,
        controls_repository: ControlsRepository,
        clock: Callable[[], datetime] = system_clock,
        amount_parameter: str = "amount",
    ) -> None:
        """Inject the ordered stages and stores (wired by the composition root)."""
        self.stages = list(stages)
        self.state = state_store
        self.audit = audit_store
        self.queue = escalation_queue
        self.repo = controls_repository
        self.clock = clock
        self.amount_parameter = amount_parameter

    # ---- decide ---------------------------------------------------------------------
    def decide(
        self,
        raw: Mapping[str, Any],
        *,
        claimed_agent_id: str | None = None,
        internal_identity: IdentityBinding | None = None,
    ) -> DecisionResponse:
        """Decide one proposed action. ``internal_identity`` is for reviewer re-entry only."""
        envelope_id = raw.get("envelope_id") if isinstance(raw, Mapping) else None
        now = self.clock()
        try:
            if isinstance(envelope_id, str):
                prior = self.state.get_decision(envelope_id)
                if prior is not None:
                    return DecisionResponse.model_validate_json(prior)
            response = self._run(raw, now, claimed_agent_id, internal_identity)
            if isinstance(envelope_id, str):
                stored = self.state.put_decision(envelope_id, response.model_dump_json())
                response = DecisionResponse.model_validate_json(stored)
            return response
        except Exception:  # noqa: BLE001 - fail closed (INT-05)
            return self._fail_closed(raw, now)

    def _run(
        self,
        raw: Mapping[str, Any],
        now: datetime,
        claim: str | None,
        internal: IdentityBinding | None,
    ) -> DecisionResponse:
        state: dict[str, Any] = {"raw": raw, "claimed_agent_id": claim, "now": now}
        if internal is not None:
            state["identity"] = internal
        timings: dict[str, float] = {}
        try:
            for stage in self.stages:
                t0 = time.perf_counter()
                state = stage.run(state)
                name = type(stage).__name__.removesuffix("Stage").lower()
                timings[name] = round((time.perf_counter() - t0) * 1000, 3)
        except (IdentityRejection, MandateRejection, StageRejection) as exc:
            stage_name = (
                "identity"
                if isinstance(exc, IdentityRejection)
                else "mandate"
                if isinstance(exc, MandateRejection)
                else exc.stage
            )
            return self._reject(raw, state, stage_name, exc.code, exc.detail, now, timings)

        disposition = state["disposition"]
        env, identity = state["envelope"], state["identity"]
        escalation_id: str | None = None
        record: EscalationRecord | None = None
        if disposition.outcome is Outcome.ESCALATE:
            route = disposition.escalation
            esc_id = f"esc-{env.envelope_id}"
            if route is not None:
                record = self.queue.open(
                    escalation_id=esc_id,
                    decision_id="pending",
                    envelope=env.model_dump(mode="json"),
                    identity=identity.model_dump(),
                    agent_stream=env.context.agent_id,
                    route=route,
                    amount=disposition.risk_profile.materiality_value,
                    at=now,
                    reservations=state["specs"],
                )
            if record is None:
                code = "ESC_NO_ROUTE" if route is None else "ESC_QUEUE_FULL"
                disposition = replace(
                    disposition,
                    outcome=Outcome.DENY,
                    escalation=None,
                    controlling_codes=(code,),
                    contributing_codes=disposition.reason_codes,
                    reason_codes=(code, *disposition.reason_codes),
                )
            else:
                escalation_id = record.escalation_id
        content = content_from_disposition(
            env,
            identity,
            disposition,
            recorded_at=now,
            policy_version=self.repo.policy_version,
            mandate=state.get("mandate"),
            state_snapshot=state["snapshot"],
            stage_timings_ms=timings,
            escalation_id=escalation_id,
        )
        try:
            entry = self._append(content)
        except Exception:
            self._undo(state.get("reserved", []), record, now)
            raise
        if record is not None:
            self.state.transition_escalation(
                record.escalation_id,
                EscalationState.PENDING,
                record.model_copy(update={"decision_id": entry.entry_id}),
            )
        return self._response(entry, content)

    def _reject(
        self,
        raw: Mapping[str, Any],
        state: Mapping[str, Any],
        stage: str,
        code: str,
        detail: str,
        now: datetime,
        timings: dict[str, float],
    ) -> DecisionResponse:
        content = content_from_rejection(
            raw,
            stage,
            code,
            detail,
            recorded_at=now,
            policy_version=self.repo.policy_version,
            identity=state.get("identity") if stage != "identity" else None,
            stage_timings_ms=timings,
        )
        return self._response(self._append(content), content)

    def _fail_closed(self, raw: Any, now: datetime) -> DecisionResponse:
        safe_raw = dict(raw) if isinstance(raw, Mapping) else {}
        try:
            content = content_from_rejection(
                safe_raw,
                "engine",
                "SYSTEM_ERROR",
                recorded_at=now,
                policy_version=None,
            )
            return self._response(self._append(content), content)
        except Exception:  # noqa: BLE001 - audit itself unavailable; still never allow
            return DecisionResponse(
                decision_id=None,
                outcome="deny",
                reason_codes=["SYSTEM_ERROR"],
                decided_at_stage="engine",
            )

    def _append(self, content: AuditContent) -> AuditEntry:
        for attempt in range(3):
            head = self.audit.head(content.agent_stream)
            try:
                return self.audit.append(content, head.entry_hash if head else None)
            except AuditConflict:
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _undo(
        self, reserved: Sequence[Reservation], record: EscalationRecord | None, now: datetime
    ) -> None:
        for r in reserved:
            self.state.release(r.key, r.amount, r.window_seconds, now)
        if record is not None:
            self.state.transition_escalation(
                record.escalation_id,
                EscalationState.PENDING,
                record.model_copy(
                    update={"state": EscalationState.DECLINED, "note": "audit unavailable"}
                ),
            )

    @staticmethod
    def _response(entry: AuditEntry, content: AuditContent) -> DecisionResponse:
        return DecisionResponse(
            decision_id=entry.entry_id,
            outcome=content.outcome,
            reason_codes=[*content.basis.controlling, *content.basis.contributing],
            rules_applied=content.rules_applied,
            policy_version=content.policy_version,
            observations=content.observations,
            stage_timings_ms=content.stage_timings_ms,
            decided_at_stage=content.decided_at_stage,
            escalation_id=content.escalation_id,
        )

    # ---- reviewers (ESC-03..05) -----------------------------------------------------
    def resolve_escalation(
        self,
        escalation_id: str,
        reviewer_id: str,
        action: Literal["approve", "decline", "modify"],
        *,
        modified_parameters: Mapping[str, Any] | None = None,
        note: str = "",
    ) -> ResolutionResult:
        """Apply a reviewer decision; refusals are audited and re-raised (S07)."""
        now = self.clock()
        current = self.queue.get(escalation_id)
        amount = None
        if action == "modify" and modified_parameters:
            value = modified_parameters.get(self.amount_parameter)
            amount = float(value) if isinstance(value, int | float) else None
        child_id = f"{current.envelope_id}-m1" if current and action == "modify" else None
        try:
            record = self.queue.resolve(
                escalation_id,
                reviewer_id,
                action,
                now,
                amount=amount,
                note=note,
                child_envelope_id=child_id,
            )
        except EscalationError as exc:
            if current is not None:
                self._append(
                    content_for_reviewer(
                        current,
                        "escalate",
                        exc.code,
                        {"action": action, "reviewer_id": reviewer_id, "status": "refused"},
                        recorded_at=now,
                        policy_version=self.repo.policy_version,
                    )
                )
            raise
        decision: dict[str, Any] = {"action": action, "reviewer_id": reviewer_id, "note": note}
        if action == "approve":
            for r in record.reservations:  # reviewer approval carries the institution's weight
                self.state.reserve(r.key, r.amount, None, r.window_seconds, now)
            outcome, code = "auto_execute", "ESC_APPROVED"
        elif action == "decline":
            outcome, code = "deny", "ESC_DECLINED"
        else:
            outcome, code = "deny", "ESC_MODIFIED"
            decision["child_envelope_id"] = child_id
        self._append(
            content_for_reviewer(
                record,
                outcome,
                code,
                decision,
                recorded_at=now,
                policy_version=self.repo.policy_version,
            )
        )
        child: DecisionResponse | None = None
        if action == "modify":
            child = self._reenter(record, reviewer_id, dict(modified_parameters or {}), now)
        return ResolutionResult(record, child)

    def _reenter(
        self, record: EscalationRecord, reviewer_id: str, parameters: dict[str, Any], now: datetime
    ) -> DecisionResponse:
        env: dict[str, Any] = dict(record.envelope)
        action = dict(env["action"])
        action["parameters"] = {**action.get("parameters", {}), **parameters}
        action["parent_envelope_id"] = record.envelope_id
        env.update(
            envelope_id=record.child_envelope_id,
            created_at=now.isoformat(),
            action=action,
            provenance={"origin": "native", "adapter_id": f"reviewer:{reviewer_id}"},
        )
        binding = IdentityBinding.model_validate({**record.identity, "origin": "reviewer"})
        return self.decide(env, claimed_agent_id=binding.agent_id, internal_identity=binding)

    def sweep(self) -> list[EscalationRecord]:
        """Apply timeout defaults and audit each change (ESC-03)."""
        now = self.clock()
        changed = self.queue.sweep(now)
        for record in changed:
            timed_out = record.state is EscalationState.TIMED_OUT
            self._append(
                content_for_reviewer(
                    record,
                    "deny" if timed_out else "escalate",
                    "ESC_TIMEOUT_BLOCKED" if timed_out else "ESC_TIMEOUT_REASSIGNED_SENIOR",
                    {"action": "timeout", "state": record.state.value},
                    recorded_at=now,
                    policy_version=self.repo.policy_version,
                )
            )
        return changed
