"""Contract scaffolding self-test: parametrisation over registered implementations."""

from abc import ABC, abstractmethod
from typing import Any

from arg.core.registry import register

BASE: type = type("Probe", (ABC,), {"ping": abstractmethod(lambda self: "pong")})


@register(BASE, "impl-a")
class ImplA(BASE):  # type: ignore[misc]
    """First probe implementation."""

    def ping(self) -> str:
        """Answer."""
        return "pong"


@register(BASE, "impl-b")
class ImplB(BASE):  # type: ignore[misc]
    """Second probe implementation."""

    def ping(self) -> str:
        """Answer."""
        return "pong"


def test_contract_runs_against_every_registered_implementation(component_cls: Any) -> None:
    """The same contract assertion is exercised for each registered class."""
    assert component_cls().ping() == "pong"
