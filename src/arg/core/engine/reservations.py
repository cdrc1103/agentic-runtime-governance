"""Counters a decision touches: snapshot reads and reservations (SG-04, T10).

One function derives them from the retrieved controls, so what the engine *reads* and what
the reserve stage *writes* cannot drift apart. Rego controls reserve nothing (documented).
"""

from collections.abc import Sequence

from arg.core.engine.evaluators import (
    _ExposureLogic,
    _RateLogic,
    amount_of,
    effective_limit,
)
from arg.core.engine.keys import counter_key
from arg.core.models import Control, EvaluationContext, Reservation


def counter_specs(controls: Sequence[Control], context: EvaluationContext) -> list[Reservation]:
    """Reservations this action would make: aggregate exposure and rate controls."""
    specs: list[Reservation] = []
    for control in controls:
        kind = control.logic.get("type")
        if kind == "exposure":
            exposure = _ExposureLogic(**control.logic)  # type: ignore[arg-type]
            if exposure.scope != "aggregate":
                continue
            amount = amount_of(context, exposure.amount_parameter)
            if amount is None:  # the evaluator fires EXP_AMOUNT_UNREADABLE; nothing to reserve
                continue
            specs.append(
                Reservation(
                    key=counter_key(control, context),
                    amount=amount,
                    limit=effective_limit(exposure, context),
                    window_seconds=exposure.window_seconds or 1,
                )
            )
        elif kind == "rate":
            rate = _RateLogic(**control.logic)  # type: ignore[arg-type]
            specs.append(
                Reservation(
                    key=counter_key(control, context),
                    amount=1,
                    limit=float(rate.max_actions),
                    window_seconds=rate.window_seconds,
                )
            )
    return specs
