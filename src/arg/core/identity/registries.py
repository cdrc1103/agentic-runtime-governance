"""Agent registries: file-backed and composite (IDN-03, IDN-04, T-201, T-202)."""

from collections.abc import Mapping
from pathlib import Path

import yaml

from arg.core.models import AgentRecord
from arg.core.ports import AgentRegistry
from arg.core.registry import register


@register(AgentRegistry, "file")
class FileRegistry(AgentRegistry):
    """YAML-backed registry: direct lookup in the institution's own register (IDN-03)."""

    def __init__(
        self,
        path: str | Path | None = None,
        registry_id: str = "default",
        records: list[AgentRecord] | None = None,
    ) -> None:
        """Load records from ``path`` (``agents:`` list) or take ``records`` directly."""
        loaded = list(records or [])
        if path is not None:
            data = yaml.safe_load(Path(path).read_text()) or {}
            loaded += [AgentRecord(**a) for a in data.get("agents", [])]
        ids = [r.agent_id for r in loaded]
        if len(ids) != len(set(ids)):
            raise ValueError(f"registry {registry_id!r} has duplicate agent_id entries")
        self.registry_id = registry_id
        self._by_id = {
            r.agent_id: r.model_copy(update={"registry_id": registry_id}) for r in loaded
        }

    def resolve(self, agent_id: str, network_context: str | None) -> AgentRecord | None:  # noqa: ARG002
        """Return the entry or None; context policy is applied by the verifier."""
        return self._by_id.get(agent_id)


@register(AgentRegistry, "composite")
class CompositeRegistry(AgentRegistry):
    """Open-network context: choose the authoritative registry per network context (IDN-04).

    ``authority`` maps network context to registry name; ``default`` (optional) covers
    contexts not listed. A claim found only in a non-authoritative registry is followed
    through that entry's ``aliases`` to the identifier used in the authoritative one; status
    and keys always come from the authoritative registry.
    """

    def __init__(
        self,
        registries: Mapping[str, AgentRegistry],
        authority: Mapping[str, str],
        default: str | None = None,
    ) -> None:
        """Bind named registries and the context -> registry map."""
        referenced = {*authority.values(), *([default] if default else [])}
        missing = referenced - set(registries)
        if missing:
            raise ValueError(f"authority references unknown registries: {sorted(missing)}")
        self.registries = dict(registries)
        self.authority = dict(authority)
        self.default = default

    def _authoritative(self, network_context: str | None) -> str | None:
        if network_context is not None and network_context in self.authority:
            return self.authority[network_context]
        return self.default

    def resolve(self, agent_id: str, network_context: str | None) -> AgentRecord | None:
        """Resolve ``agent_id`` in the registry that is authoritative for the context."""
        name = self._authoritative(network_context)
        if name is None:
            return None
        auth = self.registries[name]
        direct = auth.resolve(agent_id, network_context)
        if direct is not None:
            return direct
        for other_name, other in self.registries.items():
            if other_name == name:
                continue
            pointer = other.resolve(agent_id, network_context)
            if pointer is not None and name in pointer.aliases:
                return auth.resolve(pointer.aliases[name], network_context)
        return None
