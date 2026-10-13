"""Contract: every AgentRegistry resolves a claimed agent to one entry or to nothing."""

from collections.abc import Callable
from typing import Any

import pytest

from arg.core.identity.registries import CompositeRegistry, FileRegistry
from arg.core.models import AgentRecord, AgentStatus
from arg.core.ports import AgentRegistry

BASE = AgentRegistry
REC = AgentRecord(
    agent_id="a-1", agent_class="treasury", status=AgentStatus.ACTIVE, principal="p.example"
)

# Every registered implementation must be buildable from a list of records here.
BUILDERS: dict[type, Callable[[list[AgentRecord]], AgentRegistry]] = {
    FileRegistry: lambda recs: FileRegistry(records=recs),
    CompositeRegistry: lambda recs: CompositeRegistry(
        {"main": FileRegistry(records=recs, registry_id="main")}, {}, default="main"
    ),
}


@pytest.mark.req("IDN-01", "IDN-03")
def test_resolves_known_agent_and_returns_none_for_unknown(component_cls: Any) -> None:
    """Known agents resolve to their entry; unknown claims resolve to nothing."""
    assert component_cls in BUILDERS, "add a builder for the new implementation"
    reg = BUILDERS[component_cls]([REC])
    found = reg.resolve("a-1", None)
    assert found is not None and found.agent_id == "a-1" and found.principal == "p.example"
    assert reg.resolve("ghost", None) is None
