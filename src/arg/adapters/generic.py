"""Framework-free adapter and ``governed_tool`` wrapper (T-801).

Works for any Python agent whose tools are plain callables. It is also the reference for
how a framework adapter is shaped: subclass ``NativeAdapter``, implement ``build_envelope``
and ``enforce``.
"""

import functools
import inspect
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arg.adapters.base import NativeAdapter
from arg.adapters.client import GovernanceClient
from arg.adapters.trace import TraceRecorder
from arg.core.models import Action, ActionTrace, Context, Envelope, Provenance
from arg.core.registry import register

F = TypeVar("F", bound=Callable[..., Any])

# The decision token of the call currently executing, for code that cannot take a parameter.
current_decision_token: ContextVar[str | None] = ContextVar("current_decision_token", default=None)


@dataclass(frozen=True)
class ToolCallEvent:
    """The generic adapter's event: one proposed tool call."""

    action_type: str
    scope: str
    parameters: dict[str, Any] = field(default_factory=dict)


@register(NativeAdapter, "generic")
class GenericToolAdapter(NativeAdapter):
    """Builds envelopes for plain tool calls and enforces with the default mapping."""

    def __init__(
        self,
        client: GovernanceClient,
        *,
        agent_id: str,
        adapter_id: str = "generic-adapter",
        signer: Ed25519PrivateKey | None = None,
        mandate_ref: str | None = None,
        network_context: str | None = None,
        signals: Callable[[], dict[str, float | str | bool]] | None = None,
        recorder: TraceRecorder | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        require_token: bool = False,
    ) -> None:
        """``signals`` supplies probabilistic assessments (computed outside the core)."""
        super().__init__(client, signer, require_token)
        self.agent_id = agent_id
        self.adapter_id = adapter_id
        self.mandate_ref = mandate_ref
        self.network_context = network_context
        self.signals = signals
        self.recorder = recorder or TraceRecorder()
        self.clock = clock

    def build_envelope(self, event: ToolCallEvent) -> Envelope:
        """Declare the action, the trace so far, and the context (ENV-02)."""
        return Envelope(
            envelope_id=f"env-{uuid.uuid4().hex}",
            created_at=self.clock(),
            action=Action(type=event.action_type, scope=event.scope, parameters=event.parameters),
            action_trace=ActionTrace(steps=self.recorder.drain()),
            context=Context(
                agent_id=self.agent_id,
                mandate_ref=self.mandate_ref,
                network_context=self.network_context,
                signals=self.signals() if self.signals else {},
            ),
            provenance=Provenance(origin="native", adapter_id=self.adapter_id),
        )


def governed_tool(
    adapter: GenericToolAdapter,
    *,
    action_type: str,
    scope: str | Callable[..., str],
    parameters: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[F], F]:
    """Decorator: ask governance before the tool body runs.

    ``scope`` and ``parameters`` may be callables receiving the tool's arguments; by default
    the parameters are the bound call arguments. The tool runs only on Auto-Execute/Observe.
    If the tool has a ``decision_token`` parameter it receives the token; the token is also
    available through ``current_decision_token``. Deny raises ``ActionBlocked``; Escalate
    returns a ``PendingAction``.
    """

    def decorate(fn: F) -> F:
        sig = inspect.signature(fn)
        wants_token = "decision_token" in sig.parameters

        def event_for(args: tuple[Any, ...], kwargs: dict[str, Any]) -> ToolCallEvent:
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            values = {k: v for k, v in bound.arguments.items() if k != "decision_token"}
            params = parameters(**values) if parameters else values
            where = scope(**values) if callable(scope) else scope
            return ToolCallEvent(action_type, where, params)

        def with_token(kwargs: dict[str, Any], token: str | None) -> dict[str, Any]:
            return {**kwargs, "decision_token": token} if wants_token else kwargs

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                event = event_for(args, kwargs)
                result = adapter.guard(event)
                if not result.allowed:
                    return adapter.enforce(result, event)
                reset = current_decision_token.set(result.token)
                try:
                    return await fn(*args, **with_token(kwargs, result.token))
                finally:
                    current_decision_token.reset(reset)

            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            event = event_for(args, kwargs)

            def execute(result: Any) -> Any:
                reset = current_decision_token.set(result.token)
                try:
                    return fn(*args, **with_token(kwargs, result.token))
                finally:
                    current_decision_token.reset(reset)

            return adapter.run(event, execute)

        return wrapper  # type: ignore[return-value]

    return decorate
