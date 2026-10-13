"""Traceability checker: unknown IDs always fail; untested [PAPER] IDs fail in strict mode."""

from scripts.check_traceability import check, requirements

TABLE = "| ENV-01 | PAPER | x | y |\n| ENV-05 | DESIGN | x | n/a |\n"


def test_requirements_parses_ids_and_tags() -> None:
    """Rows of the requirement tables yield ``{id: tag}``."""
    assert requirements(TABLE) == {"ENV-01": "PAPER", "ENV-05": "DESIGN"}


def test_check_flags_unknown_and_missing() -> None:
    """Unknown IDs fail always; missing [PAPER] coverage only in strict mode."""
    reqs = requirements(TABLE)
    assert check(reqs, {"ENV-99": ["t"]}, strict=False) == [
        "test references unknown requirement ENV-99"
    ]
    assert check(reqs, {}, strict=False) == []
    assert check(reqs, {}, strict=True) == ["[PAPER] requirement ENV-01 has no test"]
    assert check(reqs, {"ENV-01": ["t"]}, strict=True) == []
