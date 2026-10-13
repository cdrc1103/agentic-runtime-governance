"""Controls repository extension points (CTL, DSP-01)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from arg.core.models import (
    Action,
    Control,
    EvaluationContext,
    Finding,
    IdentityBinding,
    Mandate,
)


class ControlsRepository(ABC):
    """Condition: return exactly the controls that apply to an identity and action.

    Requirements: CTL-01, CTL-07.
    """

    @property
    @abstractmethod
    def policy_version(self) -> str:
        """Hash of the loaded bundle; recorded in every audit entry (T6)."""

    @abstractmethod
    def retrieve(
        self, identity: IdentityBinding, action: Action, at: datetime
    ) -> Sequence[Control]:
        """Return controls valid at ``at``, selected by action type and agent class."""


class MandateResolver(ABC):
    """Condition: a mandate is resolved and validated (validity, signature, revocation, depth).

    An agent cannot extend a mandate by its own reasoning. Requirements: CTL-03, CTL-04.
    """

    @abstractmethod
    def resolve(self, mandate_ref: str, agent_id: str, at: datetime) -> Mandate:
        """Return the validated mandate or raise ``MandateRejection``."""


class ControlEvaluator(ABC):
    """Condition: one control kind is evaluated deterministically and yields findings.

    Requirements: CTL-02, CTL-05, DSP-01.
    """

    @abstractmethod
    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Return findings for ``control``; a pure function of its arguments."""
