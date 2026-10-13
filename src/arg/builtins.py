"""Imports every reference implementation so its ``@register`` decorator runs.

Only the composition root (``arg.runtime``) and test scaffolding import this module.
"""

import arg.core.controls  # noqa: F401
import arg.core.engine  # noqa: F401
import arg.core.engine.rego  # noqa: F401
import arg.core.identity  # noqa: F401
