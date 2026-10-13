"""Gateway configuration file loader (``config/gateway.yaml``)."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GatewayConfig(BaseModel):
    """Parsed gateway configuration."""

    model_config = ConfigDict(extra="forbid")

    gateway_id: str
    mode: Literal["standalone", "hybrid"] = "standalone"
    protocol: Literal["mcp", "http-egress"] = "mcp"
    upstream: str
    credentials: dict[str, dict[str, Any]]
    tools: dict[str, dict[str, Any]] = Field(default_factory=dict)
    passthrough_tools: list[str] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)


def load_gateway_config(path: Path) -> GatewayConfig:
    """Read and validate a gateway configuration file."""
    return GatewayConfig.model_validate(yaml.safe_load(path.read_text()))
