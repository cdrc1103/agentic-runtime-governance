"""ASGI entry point: ``uvicorn arg.service.main:create_app_from_env --factory``.

Reads ``ARG_CONFIG`` (path to runtime.yaml). The ``authenticator`` component is required.
"""

import os
from pathlib import Path

from fastapi import FastAPI

from arg.runtime import build_runtime, load_config
from arg.service.app import create_app
from arg.service.telemetry import OtelObserver


def create_app_from_env() -> FastAPI:
    """Build the app from ``ARG_CONFIG``; telemetry uses the global OTel providers."""
    runtime = build_runtime(load_config(Path(os.environ["ARG_CONFIG"])))
    authenticator = runtime.components.get("authenticator")
    if authenticator is None:
        raise RuntimeError("runtime.yaml must configure an 'authenticator' component")
    if runtime.decision_service is not None:
        runtime.decision_service.observer = OtelObserver()
    return create_app(runtime, authenticator)
