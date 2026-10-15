"""The interactive demo page must replay what the real engine decides."""

import json
import re

import pytest

from scripts.gen_demo_page import PAGE, build_data


@pytest.mark.req("DOC-01")
def test_demo_page_data_matches_engine() -> None:
    """Embedded scenario data equals a fresh run of the engine (no drift)."""
    text = PAGE.read_text()
    m = re.search(r"const DATA = (\{.*?\});\n/\*DATA_END\*/", text, re.S)
    assert m, "data block missing; run `uv run python -m scripts.gen_demo_page`"
    assert json.loads(m.group(1)) == build_data()


@pytest.mark.req("DOC-01")
def test_demo_page_has_no_network_dependencies() -> None:
    """The page is self-contained: no external scripts, styles, or fetches."""
    text = PAGE.read_text()
    assert not re.search(r"""(src|href)=["']https?://""", text)
    assert "fetch(" not in text
