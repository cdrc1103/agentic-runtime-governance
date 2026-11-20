"""Regenerate the recorded data of every web demo from the real engine (DOC-02, DOC-06).

Run: ``uv run python -m scripts.gen_demos``. Not regulatory guidance; demo only.
"""

from demo.web.internal_agents import record as internal_agents
from demo.web.overview import record as overview


def main() -> None:
    """Rebuild each demo page in turn."""
    print("overview")
    overview.main()
    print("internal-agents")
    internal_agents.main()


if __name__ == "__main__":
    main()
