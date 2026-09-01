"""App assembly: health endpoint → bearer auth → MCP streamable HTTP.

The layers wrap each other as plain ASGI callables instead of injecting
routes into the SDK's Starlette app, so nothing here depends on SDK
internals beyond the documented `streamable_http_app()`.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__, tools
from .auth import BearerAuthMiddleware
from .config import Settings

HEALTH_PATH = "/api/health"


class _HealthEndpoint:
    """Answer the deployment's liveness probe before auth; everything else
    (including the lifespan protocol) passes to the inner app."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope["path"] == HEALTH_PATH
            and scope.get("method", "GET") == "GET"
        ):
            body = json.dumps(
                {"status": "ok", "server": "postfach-mcp", "version": __version__}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)


def build_app(settings: Settings) -> Any:
    if not settings.token:
        raise ValueError("build_app needs settings with a token (load with require_token=True)")

    mcp = MCPServer("postfach-mcp")
    tools.register(mcp, settings)

    # Every allowed host is also allowed with any port: the Host header a
    # proxy forwards usually carries one.
    allowed_hosts: list[str] = []
    for host in settings.allowed_hosts:
        allowed_hosts.extend([host, f"{host}:*"])

    inner = mcp.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=[],
        ),
    )
    return _HealthEndpoint(BearerAuthMiddleware(inner, (settings.token, *settings.extra_tokens)))
