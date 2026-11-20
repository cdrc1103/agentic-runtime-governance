"""Run decisions on the real runtime and capture what each pipeline stage produced.

The recorder only watches: each stage's ``run`` is wrapped to copy its output state, so the
page shows the engine's own intermediate results. No decision logic lives here.
"""

import base64
import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel

from arg.core.models import AuditEntry
from arg.runtime import ROLES
from demo.web.internal_agents.world import BUNDLE, World, envelope, hdr


def jsonable(obj: Any) -> Any:
    """Plain JSON structure for pydantic models, dataclasses, enums and containers."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [jsonable(v) for v in obj]
    return obj


@dataclass
class Decision:
    """One decision: the submitted envelope, the response, the audit entry and stage states."""

    raw: dict[str, Any]
    body: dict[str, Any]
    entry: AuditEntry
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed_stage: str | None = None


class Session:
    """Wraps the pipeline stages of one world and submits decisions through the API."""

    def __init__(self, world: World) -> None:
        """Install a recording wrapper on every stage."""
        self.world = world
        self._states: dict[str, dict[str, Any]] = {}
        self._failed: str | None = None
        for stage in world.runtime.pipeline:
            self._wrap(stage, type(stage).__name__.removesuffix("Stage").lower())

    def _wrap(self, stage: Any, name: str) -> None:
        original = stage.run

        def run(state: dict[str, Any]) -> dict[str, Any]:
            try:
                out: dict[str, Any] = original(state)
            except Exception:
                self._failed = name
                raise
            self._states[name] = out
            return out

        stage.run = run

    def decide(self, raw: dict[str, Any]) -> Decision:
        """Submit ``raw`` as the platform and return the decision with captured states."""
        self._states, self._failed = {}, None
        r = self.world.api.post("/v1/decisions", json=raw, headers=hdr("orch"))
        entry = self.world.runtime.components["audit_store"].head(raw["context"]["agent_id"])
        assert entry is not None
        return Decision(raw, r.json(), entry, dict(self._states), self._failed)

    def propose(
        self, agent: str, action_type: str, parameters: dict[str, Any], **kw: Any
    ) -> Decision:
        """Build a signed envelope for ``agent`` and decide it."""
        return self.decide(envelope(self.world, agent, action_type, parameters, **kw))


def token_claims(token: str) -> dict[str, Any]:
    """Decode the payload segment of a compact JWS (display only; verification is the rail's)."""
    payload = token.split(".")[1]
    claims: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return claims


def short(value: str, n: int = 16) -> str:
    """Abbreviate a long hex or base64 value for display."""
    return value if len(value) <= n else f"{value[:n]}…"


def clean_paths(obj: Any, world: World) -> Any:
    """Replace this run's temporary paths with stable ones so the page shows plain config."""
    text = json.dumps(jsonable(obj))
    text = text.replace(str(world.tmp), "var").replace(str(BUNDLE), "config/bundle")
    text = text.replace(str(BUNDLE.parent), "config")
    return json.loads(text)


def component(world: World, role: str) -> dict[str, Any]:
    """Port, implementation and configuration of a live component, read from the runtime."""
    rt = world.runtime
    if role == "evaluators":
        impls = ", ".join(type(e).__name__ for e in rt.evaluators.values())
        cfg: Any = world.config["evaluators"]
        return {"role": role, "port": "ControlEvaluator", "impl": impls, "config": cfg}
    if role.startswith("stage:"):
        name = role.split(":")[1]
        stage = next(s for s in rt.pipeline if type(s).__name__.lower() == f"{name}stage")
        return {
            "role": role,
            "port": "PipelineStage",
            "impl": type(stage).__name__,
            "config": {"pipeline": name},
        }
    obj = rt.components[role]
    return {
        "role": role,
        "port": ROLES[role].__name__,
        "impl": type(obj).__name__,
        "config": clean_paths(world.config["components"][role], world),
    }
