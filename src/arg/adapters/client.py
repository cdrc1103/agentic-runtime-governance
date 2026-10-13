"""Governance clients: how an agent process reaches the decision core (INT-01, T-800).

``EmbeddedClient`` calls the core in-process (no network hop); ``HttpClient`` calls the
Decision API. Both return the same ``DecisionResponse``; callers (adapters) never need to
know which one they hold. Any failure raises ``GovernanceUnavailable``, and adapters treat
that as Deny (INT-05).
"""

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from typing import Any

from arg.core.decision.service import DecisionService
from arg.core.models import DecisionResponse
from arg.core.registry import register

# (url, headers, body, timeout_s) -> (status, body); injectable for tests and custom stacks.
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class GovernanceUnavailable(Exception):  # noqa: N818 - domain term
    """The decision core could not be reached or answered with a non-decision."""


class GovernanceClient(ABC):
    """Condition: an envelope is submitted and a decision is returned before the agent acts.

    Requirements: INT-01.
    """

    @abstractmethod
    def decide(self, envelope: Mapping[str, Any]) -> DecisionResponse:
        """Submit an envelope (JSON object); raise ``GovernanceUnavailable`` on failure."""


@register(GovernanceClient, "embedded")
class EmbeddedClient(GovernanceClient):
    """In-process mode: the agent process hosts the core."""

    def __init__(self, decision_service: DecisionService) -> None:
        """Bind to a ``DecisionService`` (built by ``arg.runtime.build_runtime``)."""
        self.service = decision_service

    def decide(self, envelope: Mapping[str, Any]) -> DecisionResponse:
        """Call the service directly."""
        try:
            return self.service.decide(envelope)
        except Exception as exc:  # noqa: BLE001 - the service already fails closed; belt and braces
            raise GovernanceUnavailable(str(exc)) from exc


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout_s: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@register(GovernanceClient, "http")
class HttpClient(GovernanceClient):
    """HTTP mode: calls ``POST /v1/decisions`` with a ``submit``-role bearer token."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_s: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        """``transport`` replaces the stdlib ``urllib`` call (tests, proxies, mTLS stacks)."""
        self.url = base_url.rstrip("/") + "/v1/decisions"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.timeout_s = timeout_s
        self.transport = transport or _urllib_transport

    def decide(self, envelope: Mapping[str, Any]) -> DecisionResponse:
        """POST the envelope; anything but a 200 decision is ``GovernanceUnavailable``."""
        try:
            status, body = self.transport(
                self.url, self.headers, json.dumps(envelope).encode(), self.timeout_s
            )
            if status != 200:
                raise GovernanceUnavailable(f"HTTP {status}")
            return DecisionResponse.model_validate_json(body)
        except GovernanceUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - network, TLS, JSON, schema: all fail closed
            raise GovernanceUnavailable(str(exc)) from exc
