"""Inputs and outputs of control evaluation (DSP-01, DSP-07)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue

from arg.core.models.controls import Effect, Mandate
from arg.core.models.envelope import Envelope
from arg.core.models.identity import IdentityBinding


@dataclass(frozen=True)
class EvaluationContext:
    """Everything an evaluator may look at; nothing else (determinism, DSP-07).

    ``state`` is a snapshot of exposure/rate counters taken by the caller;
    ``signals`` are probabilistic assessments computed outside the core (constitution 8).
    """

    envelope: Envelope
    identity: IdentityBinding
    mandate: Mandate | None = None
    state: Mapping[str, float] = field(default_factory=dict)
    signals: Mapping[str, float | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """Result of evaluating one control (audit ``rules_applied`` entry)."""

    control_id: str
    version: int
    result: Literal["pass", "fire"]
    effect: Effect | None = None
    reason_code: str = ""
    inputs: Mapping[str, JsonValue] = field(default_factory=dict)
