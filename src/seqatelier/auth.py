"""Bearer protection for a single workspace; not OAuth or multi-tenant auth."""

from __future__ import annotations

import hmac
import json
import os
from urllib.parse import urlsplit

from seqatelier.workspace import WorkspaceError


class AccessControl:
    def __init__(self, app, token: str | None = None):
        self.app = app
        self.token = os.environ.get("SEQATELIER_TOKEN", "") if token is None else token
        if self.token and len(self.token) < 32:
            raise WorkspaceError("SEQATELIER_TOKEN must contain at least 32 characters.")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1").lower()
        origin = headers.get(b"origin", b"").decode("latin-1")
        if origin and urlsplit(origin).netloc.lower() != host:
            return await self._deny(send, 403, "Cross-origin requests are not allowed.")
        if not self.token:
            hostname = urlsplit("http://" + host).hostname
            if hostname not in {"localhost", "127.0.0.1", "::1"}:
                return await self._deny(send, 403, "Remote access requires SEQATELIER_TOKEN.")
        protected = scope["path"].startswith(("/api/", "/mcp"))
        if protected and self.token:
            supplied = headers.get(b"authorization", b"")
            if not hmac.compare_digest(supplied, ("Bearer " + self.token).encode()):
                return await self._deny(send, 401, "A valid access token is required.")
        return await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, status: int, message: str):
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": json.dumps({"detail": message}).encode()})
