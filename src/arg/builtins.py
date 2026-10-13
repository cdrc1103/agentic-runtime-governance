"""Imports every reference implementation so its ``@register`` decorator runs.

Only the composition root (``arg.runtime``) and test scaffolding import this module.
"""

import arg.core.identity  # noqa: F401
