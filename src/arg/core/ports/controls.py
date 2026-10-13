"""Controls repository extension points (CTL, DSP-01)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from arg.core.types import JsonObject


class ControlsRepository(ABC):
    """Condition: return exactly the controls that apply to an identity and action.

    Requirements: CTL-01, CTL-07.
    """

    @abstractmethod
    def retrieve(self, identity: JsonObject, action: JsonObject) -> Sequence[JsonObject]:
        """Return applicable controls, selected by action type, agent class, and source."""


class MandateResolver(ABC):
    """Condition: a mandate is resolved and validated (validity, signature, revocation, depth).

    An agent cannot extend a mandate by its own reasoning. Requirements: CTL-03, CTL-04.
    """

    @abstractmethod
    def resolve(self, mandate_ref: str, agent_id: str) -> JsonObject:
        """Return the validated mandate or raise a reason-coded failure."""


class ControlEvaluator(ABC):
    """Condition: one control kind is evaluated deterministically and yields findings.

    Requirements: CTL-02, CTL-05, DSP-01.
    """

    @abstractmethod
    def evaluate(self, control: JsonObject, context: JsonObject) -> Sequence[JsonObject]:
        """Return findings (control id, version, result, inputs) for ``control``."""
