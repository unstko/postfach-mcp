"""Bearer-token gate in front of the MCP app.

Deliberately SDK-free plain ASGI: when a real OAuth layer replaces the
static token one day, only this middleware is swapped out — the MCP app
behind it stays untouched.
"""

from __future__ import annotations

import hmac
from collections.abc import MutableMapping, Sequence
from typing import Any

_UNAUTHORIZED_BODY = b'{"error": "unauthorized"}'


class BearerAuthMiddleware:
    """Reject every HTTP request without one of the expected bearer tokens.

    Several tokens may be configured so each client gets its own,
    individually revocable credential.

    Paths in `exempt` (the health probe) pass through, as does anything
    that is not an HTTP request — the lifespan protocol must reach the
    inner app or its session manager never starts.
    """

    def __init__(
        self,
        app: Any,
        tokens: str | Sequence[str],
        exempt: tuple[str, ...] = ("/api/health",),
    ) -> None:
        # A bare string is one token, not a sequence of one-character ones.
        if isinstance(tokens, str):
            tokens = (tokens,)
        self._app = app
        self._tokens = tuple(token.encode() for token in tokens)
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
        presented = credentials.strip()
        # No early return: the comparison cost must not reveal which of the
        # configured tokens matched.
        matched = False
        for token in self._tokens:
            if hmac.compare_digest(presented, token):
                matched = True
        return matched
