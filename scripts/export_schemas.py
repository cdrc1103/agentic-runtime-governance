"""Export JSON Schemas of the data contracts to ``schemas/`` (T-102).

``--check`` exits non-zero when committed files differ (drift gate, also run as a test).
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from arg.core.models import Control, Envelope, Mandate

OUT = Path(__file__).parent.parent / "schemas"
MODELS: dict[str, type[BaseModel]] = {"envelope": Envelope, "control": Control, "mandate": Mandate}


def render() -> dict[str, str]:
    """Return ``{filename: json text}`` for every exported schema."""
    return {
        f"{name}.schema.json": json.dumps(model.model_json_schema(), indent=2, sort_keys=True)
        + "\n"
        for name, model in MODELS.items()
    }


def main(argv: list[str]) -> int:
    """Write schemas, or with ``--check`` report drift."""
    rendered = render()
    if "--check" in argv:
        drift = [
            n for n, t in rendered.items() if not (OUT / n).exists() or (OUT / n).read_text() != t
        ]
        for n in drift:
            print(f"schema drift: {n}")
        return 1 if drift else 0
    OUT.mkdir(exist_ok=True)
    for name, text in rendered.items():
        (OUT / name).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
