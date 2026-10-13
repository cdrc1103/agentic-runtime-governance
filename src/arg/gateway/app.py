"""ASGI reverse proxy around a ``GatewayAdapter`` (T-902, T-904).

Stateless: configuration comes from the adapter; nothing is kept between requests. The
upstream client is injectable so tests run against an in-process upstream with no network.
"""

import anyio.to_thread
import httpx2
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from arg.gateway.base import Forward, GatewayAdapter, GatewayRequest

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
# Agent credentials and governance plumbing stay at the gateway (never forwarded upstream).
_STRIP_UPSTREAM = {"authorization", "x-arg-decision-token"}


def create_gateway_app(
    adapter: GatewayAdapter,
    upstream_url: str,
    *,
    upstream_headers: dict[str, str] | None = None,
    client: httpx2.AsyncClient | None = None,
) -> Starlette:
    """Build the proxy app. Allowed requests are forwarded with their original body bytes."""
    http = client or httpx2.AsyncClient(timeout=30.0)
    base = upstream_url.rstrip("/")

    async def proxy(request: Request) -> Response:
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        req = GatewayRequest(
            method=request.method,
            path=request.url.path,
            headers=headers,
            body=body,
            query=dict(request.query_params),
        )
        outcome = await anyio.to_thread.run_sync(adapter.handle, req)
        if not isinstance(outcome, Forward):
            return Response(outcome.body, outcome.status, outcome.headers)
        forwarded = {
            k: v for k, v in headers.items() if k not in _HOP_BY_HOP and k not in _STRIP_UPSTREAM
        }
        forwarded.update(upstream_headers or {})
        url = base + request.url.path
        upstream_req = http.build_request(
            request.method, url, params=request.query_params, headers=forwarded, content=body
        )
        try:
            upstream = await http.send(upstream_req, stream=True)
        except httpx2.HTTPError:
            return Response(
                b'{"error":"upstream_unreachable"}', 502, {"content-type": "application/json"}
            )
        out_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _HOP_BY_HOP and k.lower() != "content-encoding"
        }
        return StreamingResponse(
            upstream.aiter_raw(),
            upstream.status_code,
            out_headers,
            background=BackgroundTask(upstream.aclose),
        )

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    return Starlette(routes=[Route("/{path:path}", proxy, methods=methods)])
