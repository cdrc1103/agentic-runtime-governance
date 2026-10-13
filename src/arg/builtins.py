"""Imports every reference implementation so its ``@register`` decorator runs.

Only the composition root (``arg.runtime``) and test scaffolding import this module.
"""

import arg.core.audit.anchor  # noqa: F401
import arg.core.audit.memory  # noqa: F401
import arg.core.audit.sqlite  # noqa: F401
import arg.core.controls  # noqa: F401
import arg.core.decision.stages  # noqa: F401
import arg.core.engine  # noqa: F401
import arg.core.engine.rego  # noqa: F401
import arg.core.escalation.queue  # noqa: F401
import arg.core.identity  # noqa: F401
import arg.core.state.memory  # noqa: F401
import arg.core.state.sqlite  # noqa: F401
import arg.core.tokens.service  # noqa: F401
