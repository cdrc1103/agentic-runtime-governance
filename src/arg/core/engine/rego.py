"""Optional OPA/Rego control evaluator (D4, T-405).

Calls the ``opa`` binary once per evaluation (``opa eval``); no Wasm, no bundling, no policy
management. A control selects it with ``logic: {type: rego, policy: <file in bundle>,
query: data.<pkg>.result}``. The policy receives ``{envelope, identity, mandate, state,
signals, at, logic, effect}`` and returns ``{effect, reason_codes}``; an undefined result
means the control passes. Anything else (missing binary, error, bad shape) raises, which
dispatch turns into a Deny.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from arg.core.canonical import to_jsonable
from arg.core.models import Control, Effect, EvaluationContext, Finding
from arg.core.ports import ControlEvaluator
from arg.core.registry import register


@register(ControlEvaluator, "rego")
class RegoControlEvaluator(ControlEvaluator):
    """Evaluates a control's Rego policy through the OPA CLI."""

    def __init__(
        self, bundle_path: str | Path, opa_binary: str = "opa", timeout_s: int = 10
    ) -> None:
        """``bundle_path`` is the controls bundle root that ``logic.policy`` is relative to."""
        self.root = Path(bundle_path).resolve()
        self.opa_binary = opa_binary
        self.timeout_s = timeout_s

    def evaluate(self, control: Control, context: EvaluationContext) -> Sequence[Finding]:
        """Run the policy and map its result to a finding."""
        policy = (self.root / str(control.logic["policy"])).resolve()
        if not policy.is_relative_to(self.root):
            raise ValueError("rego policy path escapes the bundle")
        query = str(control.logic["query"])
        payload = {
            "envelope": to_jsonable(context.envelope),
            "identity": context.identity.model_dump(mode="json"),
            "mandate": context.mandate.model_dump(mode="json") if context.mandate else None,
            "state": dict(context.state),
            "signals": dict(context.signals),
            "at": context.at.isoformat(),
            "logic": control.logic,
            "effect": control.effect.value,
        }
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                self.opa_binary,
                "eval",
                "--data",
                str(policy),
                "--stdin-input",
                "--format",
                "json",
                query,
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            check=True,
        )
        results = json.loads(proc.stdout).get("result", [])
        if not results:
            return [Finding(control.control_id, control.version, "pass")]
        value = results[0]["expressions"][0]["value"]
        effect = Effect(value["effect"])
        codes = [str(c) for c in value["reason_codes"]]
        return [Finding(control.control_id, control.version, "fire", effect, ",".join(codes))]
