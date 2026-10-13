"""Fail on claims the constitution forbids (rule 5): compliance, certification, official
status, or "MAS requires". Lines that negate or quote the rule are allowed.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = [
    re.compile(r"\bcompliant\b", re.I),
    re.compile(r"\bcertified\b", re.I),
    re.compile(r"(?<!un)\bofficial\b(?! (documentation|docs|release|site|repository))", re.I),
    re.compile(r"\bMAS requires\b", re.I),
]
# A line is allowed if it negates the claim or is describing the rule itself.
NEGATIONS = re.compile(
    r"\b(not|never|no|isn't|aren't|nor|unofficial|without|forbid\w*|wording|lint|"
    r"rule|disclaimer)\b|n't",
    re.I,
)
SKIP = {"docs/spec/open-decisions.md"}  # quotes the paper's title/section names verbatim


def files() -> list[Path]:
    """Documentation files subject to the wording rule."""
    out = [
        ROOT / n
        for n in ("README.md", "LIMITATIONS.md", "SECURITY.md", "CONTRIBUTING.md", "CLAUDE.md")
    ]
    out += sorted((ROOT / "docs").rglob("*.md")) + sorted((ROOT / "conformance").glob("*.md"))
    return [p for p in out if p.exists() and p.relative_to(ROOT).as_posix() not in SKIP]


def violations() -> list[str]:
    """Return ``path:line: text`` for each forbidden phrase not in a negated line."""
    found: list[str] = []
    for path in files():
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if any(rx.search(line) for rx in FORBIDDEN) and not NEGATIONS.search(line):
                found.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    return found


def main() -> int:
    """CLI entry point."""
    bad = violations()
    for b in bad:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
