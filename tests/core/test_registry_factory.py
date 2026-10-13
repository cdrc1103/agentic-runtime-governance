"""Registry, factory, and composition-root behaviour (T-005)."""

from abc import ABC, abstractmethod
from typing import Any

import pytest

from arg.core.factory import ComponentFactory
from arg.core.ports import AuditStore, PipelineStage, StateStore
from arg.core.registry import ComponentRegistry, register, registry_for
from arg.core.state.memory import InMemoryStateStore
from arg.runtime import ROLES, build_runtime, load_config


class Greeter(ABC):
    """Test-only abstract class."""

    @abstractmethod
    def greet(self) -> str:
        """Return a greeting."""


class Hello(Greeter):
    """Test double."""

    def __init__(self, name: str = "x") -> None:
        """Store the name."""
        self.name = name

    def greet(self) -> str:
        """Return the greeting."""
        return f"hello {self.name}"


def test_registry_register_get_and_errors() -> None:
    """Names resolve; duplicates, foreign classes, and unknown names fail clearly."""
    reg = ComponentRegistry(Greeter)
    reg.register("hello", Hello)
    assert reg.get("hello") is Hello
    assert reg.names() == ["hello"]
    with pytest.raises(ValueError, match="already registered"):
        reg.register("hello", Hello)
    with pytest.raises(TypeError):
        reg.register("bad", int)  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="known: hello"):
        reg.get("nope")


def test_register_decorator_and_factory() -> None:
    """The decorator registers into the per-base registry; the factory builds from config."""

    @register(Greeter, "decorated")
    class Decorated(Hello):
        """Registered through the decorator."""

    factory = ComponentFactory(registry_for(Greeter))
    assert isinstance(factory.create({"type": "decorated", "name": "bob"}), Decorated)
    with pytest.raises(ValueError, match="'type'"):
        factory.create({})
    with pytest.raises(ValueError, match="shadow"):
        factory.create({"type": "decorated", "name": "a"}, name="b")


def test_build_runtime_wires_components_and_injects_dependencies() -> None:
    """Roles are built in order; later components receive earlier ones by role name."""

    @register(StateStore, "t-state")
    class FakeState(InMemoryStateStore):
        """Test double: the in-memory store registered under another name."""

    @register(PipelineStage, "t-stage")
    class FakeStage(PipelineStage):
        """Test double taking the state store by role name."""

        def __init__(self, state_store: StateStore) -> None:
            """Keep the injected store."""
            self.state_store = state_store

        def run(self, state: dict[str, Any]) -> dict[str, Any]:
            """Pass state through."""
            return state

    rt = build_runtime(
        {"components": {"state_store": {"type": "t-state"}}, "pipeline": ["t-stage"]}
    )
    assert isinstance(rt.components["state_store"], FakeState)
    stage = rt.pipeline[0]
    assert isinstance(stage, FakeStage) and stage.state_store is rt.components["state_store"]


def test_build_runtime_rejects_unknown_role() -> None:
    """A typo in runtime.yaml is an error, not a silent skip."""
    with pytest.raises(ValueError, match="unknown component roles"):
        build_runtime({"components": {"audit_stor": {"type": "x"}}})


def test_every_role_has_an_abstract_class_with_condition_docstring() -> None:
    """Constitution 14: each extension point documents its Condition."""
    for base in [*ROLES.values(), PipelineStage]:
        assert (base.__doc__ or "").startswith("Condition:"), base.__name__
    assert AuditStore in ROLES.values()


def test_load_config_requires_mapping(tmp_path: Any) -> None:
    """runtime.yaml parses to a mapping; anything else is rejected."""
    good = tmp_path / "ok.yaml"
    good.write_text("pipeline: [a]\n")
    assert load_config(good) == {"pipeline": ["a"]}
    bad = tmp_path / "bad.yaml"
    bad.write_text("- 1\n")
    with pytest.raises(ValueError, match="mapping"):
        load_config(bad)
