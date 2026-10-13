"""State-key scheme shared by evaluators (reading snapshots) and reservation (SG-04, T10)."""

from arg.core.models import Control, EvaluationContext


def counter_key(control: Control, context: EvaluationContext) -> str:
    """Counter key for an aggregate or rate control.

    ``logic.key_by`` is ``agent`` (default) or ``principal``; keying by principal defeats
    limit evasion through many agent identities (T10).
    """
    key_by = str(control.logic.get("key_by", "agent"))
    if key_by == "principal":
        subject = context.identity.principal
    elif key_by == "agent":
        subject = context.identity.agent_id
    else:
        raise ValueError(f"unknown key_by {key_by!r}")
    return f"{control.control_id}:{key_by}:{subject}"
