"""Tiny path extraction for gateway mappings (a documented subset of JSONPath).

Paths are dotted: ``arguments.account``, ``body.items.0.id``, ``path.account``. Integers index
lists. No wildcards, filters, or recursion: mappings stay auditable by reading them.
"""

import re
from typing import Any

_MISSING = object()
_TEMPLATE = re.compile(r"\{([^{}]+)\}")


def get_path(document: Any, path: str) -> Any:
    """Return the value at ``path``; raise ``KeyError`` if absent."""
    current = document
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise KeyError(path)
    return current


def render(template: str, document: Any) -> str:
    """Replace ``{path}`` placeholders with scalar values from ``document``."""

    def sub(match: re.Match[str]) -> str:
        value = get_path(document, match.group(1))
        if isinstance(value, dict | list) or value is None:
            raise KeyError(match.group(1))
        return str(value)

    return _TEMPLATE.sub(sub, template)
