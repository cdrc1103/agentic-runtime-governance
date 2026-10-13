"""Contract-suite scaffolding (T-006).

A contract module sets ``BASE = <AbstractClass>`` and takes a ``component_cls`` argument;
the test is parametrised over every registered implementation. With none registered the
test is skipped, so suites can exist before implementations do.
"""

import importlib
from typing import Any

import pytest

from arg.core.registry import registry_for

# Modules whose import registers reference implementations; extended per phase.
IMPLEMENTATION_MODULES: list[str] = []


def _load_implementations() -> None:
    for mod in IMPLEMENTATION_MODULES:
        importlib.import_module(mod)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrise ``component_cls`` over the registered implementations of ``BASE``."""
    if "component_cls" not in metafunc.fixturenames:
        return
    _load_implementations()
    reg = registry_for(metafunc.module.BASE)
    names = reg.names()
    metafunc.parametrize(
        "component_cls",
        [reg.get(n) for n in names],
        ids=names,
    )


@pytest.fixture
def component_cls() -> Any:  # pragma: no cover - replaced by parametrisation
    """Placeholder so the fixture name resolves; real values come from the hook."""
    pytest.skip("no registered implementation")
