"""Builds component instances from config blocks such as ``{type: sqlite, path: ...}``."""

from collections.abc import Mapping
from typing import Any

from arg.core.registry import ComponentRegistry


class ComponentFactory[T]:
    """Creates instances of one abstract class from configuration."""

    def __init__(self, registry: ComponentRegistry[T]) -> None:
        """Bind the factory to ``registry``."""
        self.registry = registry

    def create(self, config: Mapping[str, Any], **deps: Any) -> T:
        """Instantiate ``config["type"]`` with the remaining keys plus injected ``deps``."""
        if "type" not in config:
            raise ValueError(f"{self.registry.base.__name__} config needs a 'type' key")
        kwargs = {k: v for k, v in config.items() if k != "type"}
        overlap = kwargs.keys() & deps.keys()
        if overlap:
            raise ValueError(f"config keys shadow injected dependencies: {sorted(overlap)}")
        return self.registry.get(config["type"])(**kwargs, **deps)
