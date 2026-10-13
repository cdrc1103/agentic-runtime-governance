"""Pytest plugin: ``req`` marker bookkeeping and ``--req-report`` (T-004)."""

from collections import defaultdict
from pathlib import Path

import pytest
import yaml

MATRIX = Path(__file__).parent.parent / "conformance" / "matrix.yaml"
_covered: dict[str, list[str]] = defaultdict(list)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--req-report`` to write ``conformance/matrix.yaml``."""
    parser.addoption("--req-report", action="store_true", help="write conformance/matrix.yaml")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Record which tests carry which requirement IDs."""
    for item in items:
        for mark in item.iter_markers("req"):
            for req_id in mark.args:
                _covered[str(req_id)].append(item.nodeid)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Write the requirement -> tests matrix when ``--req-report`` is given."""
    if session.config.getoption("--req-report"):
        MATRIX.parent.mkdir(exist_ok=True)
        MATRIX.write_text(yaml.safe_dump({k: sorted(v) for k, v in sorted(_covered.items())}))
