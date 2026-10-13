"""Docking point for agent frameworks (INT-01, INT-06).

No framework-specific adapter ships in this repository; see ``docs/adapters/README.md``
for what exists, what does not, and how to write one.
"""

from arg.adapters.base import ActionBlocked, GuardResult, NativeAdapter, PendingAction
from arg.adapters.client import EmbeddedClient, GovernanceClient, GovernanceUnavailable, HttpClient
from arg.adapters.generic import GenericToolAdapter, ToolCallEvent, governed_tool
from arg.adapters.trace import TraceRecorder

__all__ = [
    "ActionBlocked",
    "EmbeddedClient",
    "GenericToolAdapter",
    "GovernanceClient",
    "GovernanceUnavailable",
    "GuardResult",
    "HttpClient",
    "NativeAdapter",
    "PendingAction",
    "ToolCallEvent",
    "TraceRecorder",
    "governed_tool",
]
