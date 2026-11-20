"""The web demos must replay what the real engine decides (DOC-01..DOC-06)."""

import json
import re
from functools import lru_cache
from typing import Any

import pytest

from demo.web.internal_agents import record as internal
from demo.web.overview.record import PAGE, build_data

ROOT = PAGE.parents[3]
DATA_RE = re.compile(r"const DATA = (\{.*?\});\n/\*DATA_END\*/", re.S)
CHECKED = ("identity", "controls", "decide", "evidence")


@lru_cache(maxsize=1)
def fresh_internal() -> dict[str, Any]:
    """One fresh recording of the internal-agents scenarios, shared by the tests."""
    return internal.build_data()


def embedded_internal() -> dict[str, Any]:
    """The data block embedded in the published internal-agents page."""
    m = DATA_RE.search(internal.PAGE.read_text())
    assert m, "data block missing; run `uv run python -m scripts.gen_demos`"
    data: dict[str, Any] = json.loads(m.group(1))
    return data


@pytest.mark.req("DOC-01")
@pytest.mark.req("DOC-06")
def test_overview_page_data_matches_engine() -> None:
    """Embedded overview scenario data equals a fresh run of the engine (no drift)."""
    m = DATA_RE.search(PAGE.read_text())
    assert m, "data block missing; run `uv run python -m scripts.gen_demos`"
    assert json.loads(m.group(1)) == build_data()


@pytest.mark.req("DOC-06")
def test_internal_agents_decisions_match_engine() -> None:
    """Outcomes, reasons, rule results and step statuses equal a fresh engine run."""
    fresh = {s["id"]: s["fingerprint"] for s in fresh_internal()["scenarios"]}
    page = {s["id"]: s["fingerprint"] for s in embedded_internal()["scenarios"]}
    assert page == fresh


@pytest.mark.req("DOC-01")
@pytest.mark.req("DOC-02")
def test_pages_have_no_network_dependencies() -> None:
    """Every page is self-contained: no external scripts, styles, or fetches."""
    for page in (PAGE, internal.PAGE, ROOT / "docs" / "demo" / "index.html"):
        text = page.read_text()
        assert not re.search(r"""(src|href)=["']https?://""", text), page
        assert "fetch(" not in text, page


@pytest.mark.req("DOC-02")
def test_hub_links_every_web_demo() -> None:
    """The hub links the overview and the internal-agents page, and both exist."""
    hub = (ROOT / "docs" / "demo" / "index.html").read_text()
    for target in ("overview/", "internal-agents/"):
        assert f'href="{target}"' in hub
        assert (ROOT / "docs" / "demo" / target / "index.html").exists()


@pytest.mark.req("DOC-03")
def test_internal_agents_cover_finance_domains_and_all_dispositions() -> None:
    """P2P, O2C and R2R are covered, with all four dispositions and fictional naming only."""
    data = embedded_internal()["scenarios"]
    assert {s["domain"] for s in data} >= {"P2P", "O2C", "R2R"}
    outcomes = {o for s in data for o in s["outcomes"]}
    assert outcomes == {"deny", "escalate", "auto_execute", "observe"}
    assert "Example Bank" not in internal.PAGE.read_text()


@pytest.mark.req("DOC-04")
def test_internal_agents_page_steps_manually() -> None:
    """Back and forward controls and arrow keys exist; autoplay starts unchecked; four core."""
    scenarios = embedded_internal()["scenarios"]
    assert sum(s["core"] for s in scenarios) == 4
    text = internal.PAGE.read_text()
    for needle in ('id="prev"', 'id="next"', "ArrowRight", "ArrowLeft", "location.hash"):
        assert needle in text
    assert 'id="auto">' in text and 'id="auto" checked' not in text


@pytest.mark.req("DOC-05")
def test_every_step_names_its_technology_and_live_component() -> None:
    """Each step has one tool badge; the reference detail names live ports and implementations."""
    stack = {c["role"]: c for c in embedded_internal()["stack"]}
    assert stack["audit_store"]["impl"] == "SqliteAuditStore"
    for s in embedded_internal()["scenarios"]:
        for b in s["beats"]:
            assert b["tool"], (s["id"], b["id"])
            if b["id"] in CHECKED:
                comps = [c for item in b["ref"] for c in item["components"]]
                assert comps, (s["id"], b["id"])
                assert all(c["port"] and c["impl"] for c in comps)
                assert all(item["stack"] for item in b["ref"])
