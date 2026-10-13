"""Gateway entry point: ``uvicorn arg.gateway.main:create_app_from_env --factory``.

Environment: ``ARG_GATEWAY_CONFIG`` (yaml), ``ARG_CORE_URL``, ``ARG_CORE_SUBMIT_TOKEN``
(standalone), ``ARG_CORE_CONSUME_TOKEN`` (hybrid). The gateway is stateless: everything it
needs is in these inputs.
"""

import os
from pathlib import Path

from starlette.applications import Starlette

from arg.adapters.client import HttpClient
from arg.gateway.app import create_gateway_app
from arg.gateway.backend import HttpRedeemer
from arg.gateway.base import GatewayAdapter
from arg.gateway.config import load_gateway_config
from arg.gateway.core import GatewayEngine
from arg.gateway.http_egress import HttpEgressGateway
from arg.gateway.identity import StaticBearerIdentityResolver
from arg.gateway.mcp import McpGateway


def create_app_from_env() -> Starlette:
    """Build the gateway from configuration and environment."""
    cfg = load_gateway_config(Path(os.environ["ARG_GATEWAY_CONFIG"]))
    core = os.environ["ARG_CORE_URL"]
    engine = GatewayEngine(
        cfg.gateway_id,
        cfg.mode,
        client=HttpClient(core, os.environ["ARG_CORE_SUBMIT_TOKEN"])
        if cfg.mode == "standalone"
        else None,
        redeemer=HttpRedeemer(core, os.environ["ARG_CORE_CONSUME_TOKEN"])
        if cfg.mode == "hybrid"
        else None,
    )
    identity = StaticBearerIdentityResolver(cfg.credentials)
    adapter: GatewayAdapter
    if cfg.protocol == "mcp":
        adapter = McpGateway(engine, identity, cfg.tools, cfg.passthrough_tools)
    else:
        adapter = HttpEgressGateway(engine, identity, cfg.routes)
    return create_gateway_app(adapter, cfg.upstream)
