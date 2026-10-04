"""OAuth resource-server checks; the identity provider owns login and token issuance."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from seqatelier.workspace import WorkspaceError

ACCESS_SCOPE = "workspace:access"


@dataclass(frozen=True)
class OAuthSettings:
    issuer: str
    resource: str
    client_id: str
    allowed_subjects: tuple[str, ...]

    def __post_init__(self):
        for label, url in (("issuer", self.issuer), ("resource", self.resource)):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise WorkspaceError(f"OAuth {label} must be an HTTPS origin without a path or credentials.")
        if not self.issuer.endswith("/") or self.resource.endswith("/"):
            raise WorkspaceError("OAuth issuer must end with /; resource must not end with /.")
        if not self.client_id or not self.allowed_subjects or not all(self.allowed_subjects):
            raise WorkspaceError("OAuth requires a browser client ID and an explicit subject allowlist.")

    @classmethod
    def from_env(cls) -> OAuthSettings | None:
        issuer = os.environ.get("SEQATELIER_AUTH_ISSUER", "")
        client_id = os.environ.get("SEQATELIER_AUTH_CLIENT_ID", "")
        subjects = os.environ.get("SEQATELIER_AUTH_SUBJECTS", "")
        if not any((issuer, client_id, subjects)):
            return None
        resource = os.environ.get("SEQATELIER_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
        return cls(
            issuer=issuer.rstrip("/") + "/",
            resource=resource.rstrip("/"),
            client_id=client_id,
            allowed_subjects=tuple(value.strip() for value in subjects.split(",") if value.strip()),
        )

    def public_config(self) -> dict:
        return {
            "mode": "oauth",
            "issuer": self.issuer,
            "client_id": self.client_id,
            "audience": self.resource,
            "scope": ACCESS_SCOPE,
        }

    def metadata(self) -> dict:
        return {
            "resource": self.resource,
            "authorization_servers": [self.issuer],
            "scopes_supported": [ACCESS_SCOPE],
            "bearer_methods_supported": ["header"],
        }


class AccessDeniedError(Exception):
    def __init__(self, status: int, error: str):
        self.status, self.error = status, error


class JWTVerifier:
    def __init__(self, settings: OAuthSettings):
        import jwt

        self.settings = settings
        self.keys = jwt.PyJWKClient(settings.issuer + ".well-known/jwks.json", timeout=5)

    def verify(self, token: str) -> dict:
        import jwt

        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise AccessDeniedError(401, "invalid_token")
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.settings.resource,
                issuer=self.settings.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=15,
            )
        except jwt.PyJWTError as exc:
            raise AccessDeniedError(401, "invalid_token") from exc
        if claims["sub"] not in self.settings.allowed_subjects:
            raise AccessDeniedError(403, "access_denied")
        scope = claims.get("scope", "")
        if not isinstance(scope, str) or ACCESS_SCOPE not in scope.split():
            raise AccessDeniedError(403, "insufficient_scope")
        return claims


class OAuthAccessControl:
    """Protect API and MCP with issuer, audience, expiry, scope and owner checks."""

    def __init__(self, app, settings: OAuthSettings, verifier: JWTVerifier | None = None):
        self.app = app
        self.settings = settings
        self.verifier = verifier or JWTVerifier(settings)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1").lower()
        origin = headers.get(b"origin", b"").decode("latin-1")
        # Hosting health probes may use an internal Host. They disclose no workspace data.
        if scope["path"] != "/health" and host != urlsplit(self.settings.resource).netloc.lower():
            return await self._deny(send, 403, "invalid_host")
        if origin and origin != self.settings.resource:
            return await self._deny(send, 403, "invalid_origin")
        if scope["path"] in {
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        }:
            return await self._json(send, 200, self.settings.metadata())
        if scope["path"] == "/auth/config":
            return await self._json(send, 200, self.settings.public_config())
        if scope["path"].startswith(("/api/", "/mcp")):
            value = headers.get(b"authorization", b"").decode("latin-1")
            scheme, separator, token = value.partition(" ")
            if not separator or scheme.lower() != "bearer" or not token or len(token) > 16384:
                return await self._deny(send, 401, "invalid_token")
            try:
                claims = await asyncio.to_thread(self.verifier.verify, token)
            except AccessDeniedError as exc:
                return await self._deny(send, exc.status, exc.error)
            scope["seqatelier.user"] = claims["sub"]

        async def no_store(message):
            if message["type"] == "http.response.start" and scope["path"].startswith(("/api/", "/mcp")):
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        return await self.app(scope, receive, no_store)

    async def _deny(self, send, status: int, error: str):
        challenge = (
            f'Bearer resource_metadata="{self.settings.resource}/.well-known/oauth-protected-resource", '
            f'scope="{ACCESS_SCOPE}", error="{error}"'
        )
        await self._json(send, status, {"detail": error}, [(b"www-authenticate", challenge.encode())])

    @staticmethod
    async def _json(send, status: int, body: dict, extra_headers: list | None = None):
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        await send(
            {"type": "http.response.start", "status": status, "headers": headers + (extra_headers or [])}
        )
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})
