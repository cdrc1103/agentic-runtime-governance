"""Component registry: name -> implementation, per abstract class (reference principles 1A)."""

from collections.abc import Callable


class ComponentRegistry[T]:
    """Maps implementation names to concrete classes of one abstract base class."""

    def __init__(self, base: type[T]) -> None:
        """Create an empty registry for ``base``."""
        self.base = base
        self._classes: dict[str, type[T]] = {}

    def register(self, name: str, cls: type[T]) -> None:
        """Register ``cls`` under ``name``; duplicate names and foreign classes are errors."""
        if not issubclass(cls, self.base):
            raise TypeError(f"{cls.__name__} is not a subclass of {self.base.__name__}")
        if name in self._classes:
            raise ValueError(f"{self.base.__name__} implementation {name!r} already registered")
        self._classes[name] = cls

    def get(self, name: str) -> type[T]:
        """Return the class registered under ``name``."""
        try:
            return self._classes[name]
        except KeyError:
            known = ", ".join(sorted(self._classes)) or "<none>"
            raise KeyError(
                f"unknown {self.base.__name__} implementation {name!r}; known: {known}"
            ) from None

    def names(self) -> list[str]:
        """Return registered names, sorted."""
        return sorted(self._classes)


# Import-time registration table behind the ``register`` decorator. This is the single
# permitted piece of module-level state; the factory and composition root take registries
# explicitly.
_REGISTRIES: dict[type, ComponentRegistry] = {}  # type: ignore[type-arg]


def registry_for[T](base: type[T]) -> ComponentRegistry[T]:
    """Return (creating on first use) the registry for ``base``."""
    if base not in _REGISTRIES:
        _REGISTRIES[base] = ComponentRegistry(base)
    return _REGISTRIES[base]


def register[T](base: type[T], name: str) -> Callable[[type[T]], type[T]]:
    """Class decorator: ``@register(AuditStore, "sqlite")``."""

    def decorator(cls: type[T]) -> type[T]:
        registry_for(base).register(name, cls)
        return cls

    return decorator
