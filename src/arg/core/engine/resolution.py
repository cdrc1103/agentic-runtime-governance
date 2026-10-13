"""Resolution precedence (DSP-02, DSP-06, T-403)."""

from collections.abc import Sequence

from arg.core.models import Effect, Finding, Outcome
from arg.core.ports import ResolutionPolicy
from arg.core.registry import register

_EFFECT_OUTCOME = {
    Effect.DENY: Outcome.DENY,
    Effect.ESCALATE: Outcome.ESCALATE,
    Effect.OBSERVE: Outcome.OBSERVE,
}


@register(ResolutionPolicy, "precedence")
class PrecedenceResolutionPolicy(ResolutionPolicy):
    """Deny > Escalate > Observe > Auto-Execute across fired controls and the risk profile."""

    def resolve(self, findings: Sequence[Finding], indicated: Outcome) -> Outcome:
        """Return the most restrictive of all fired effects and the risk-indicated outcome."""
        candidates = [indicated]
        candidates += [
            _EFFECT_OUTCOME[f.effect] for f in findings if f.result == "fire" and f.effect
        ]
        return max(candidates, key=lambda o: o.restrictiveness)
