"""Bearer-token gate in front of the MCP app.

Deliberately SDK-free plain ASGI: when a real OAuth layer replaces the
static token one day, only this middleware is swapped out — the MCP app
behind it stays untouched.
"""

from __future__ import annotations

import hmac
from collections.abc import MutableMapping
from typing import Any

_UNAUTHORIZED_BODY = b'{"error": "unauthorized"}'


class BearerAuthMiddleware:
    """Reject every HTTP request without the expected bearer token.

    Paths in `exempt` (the health probe) pass through, as does anything
    that is not an HTTP request — the lifespan protocol must reach the
    inner app or its session manager never starts.
    """

    def __init__(self, app: Any, token: str, exempt: tuple[str, ...] = ("/api/health",)) -> None:
        self._app = app
        self._token = token.encode()
        self._exempt = exempt

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] in self._exempt:
            await self._app(scope, receive, send)
            return
        if self._authorized(scope):
            await self._app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})

    def _authorized(self, scope: MutableMapping[str, Any]) -> bool:
        header = b""
        for name, value in scope.get("headers") or ():
            if name == b"authorization":
                header = value
                break
        scheme, _, credentials = header.partition(b" ")
        if scheme.lower() != b"bearer":
            return False
        return hmac.compare_digest(credentials.strip(), self._token)
