"""Constitution rule 5: no compliance/certification/official-status claims in docs."""

from scripts.check_wording import violations


def test_docs_make_no_forbidden_claims() -> None:
    """The wording lint is clean (it allows negated and rule-quoting lines)."""
    assert violations() == []
