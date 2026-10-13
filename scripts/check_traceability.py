"""Fail if a test references an unknown requirement, or (``--strict``) a [PAPER] one is untested.

Reads ``docs/spec/requirements.md`` and ``conformance/matrix.yaml`` (``pytest --req-report``).
Strict mode is enabled in CI from Phase 10 (every [PAPER] ID covered).
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
ROW = re.compile(r"^\| ([A-Z]+-\d+) \| (PAPER|DESIGN) \|", re.MULTILINE)


def requirements(text: str) -> dict[str, str]:
    """Return ``{requirement_id: tag}`` parsed from the requirement tables."""
    return {m.group(1): m.group(2) for m in ROW.finditer(text)}


def check(reqs: dict[str, str], matrix: dict[str, list[str]], strict: bool) -> list[str]:
    """Return a list of problems."""
    problems = [f"test references unknown requirement {r}" for r in sorted(matrix) if r not in reqs]
    if strict:
        problems += [
            f"[PAPER] requirement {r} has no test"
            for r, tag in sorted(reqs.items())
            if tag == "PAPER" and not matrix.get(r)
        ]
    return problems


def main(argv: list[str]) -> int:
    """CLI entry point."""
    reqs = requirements((ROOT / "docs/spec/requirements.md").read_text())
    matrix_path = ROOT / "conformance/matrix.yaml"
    matrix = yaml.safe_load(matrix_path.read_text()) if matrix_path.exists() else {}
    problems = check(reqs, matrix or {}, strict="--strict" in argv)
    for p in problems:
        print(p)
    paper = [r for r, t in reqs.items() if t == "PAPER"]
    covered = [r for r in paper if matrix and matrix.get(r)]
    print(f"[PAPER] covered: {len(covered)}/{len(paper)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
