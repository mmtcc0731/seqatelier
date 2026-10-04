import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from seqatelier.cli import main
from seqatelier.demo import initialize_demo
from seqatelier.mcp_server import create_http_app
from seqatelier.oauth import ACCESS_SCOPE, JWTVerifier, OAuthSettings
from seqatelier.web import create_app
from seqatelier.workspace import Workspace, WorkspaceError


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = OAuthSettings(
        issuer="https://login.example/",
        resource="https://sequences.example",
        client_id="synthetic-public-spa",
        allowed_subjects=("github|1234",),
    )
    monkeypatch.setattr(
        jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, token: SimpleNamespace(key=key.public_key())
    )
    ws = Workspace(tmp_path / "workspace")
    initialize_demo(ws)
    mcp_app = create_http_app(ws, oauth=settings, host="0.0.0.0", raw=True, allow_writes=True)
    app = create_app(ws, oauth=settings, mcp_app=mcp_app)

    def token(**changes):
        claims = {
            "iss": settings.issuer,
            "aud": settings.resource,
            "sub": "github|1234",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "scope": ACCESS_SCOPE,
        }
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic"})

    with TestClient(app, base_url=settings.resource) as client:
        yield client, token, ws


def test_discovery_and_private_data(cloud):
    client, token, _ = cloud
    assert client.get("/health").status_code == 200
    config = client.get("/auth/config").json()
    assert config["mode"] == "oauth" and "allowed_subjects" not in config
    assert (
        client.get("/.well-known/oauth-protected-resource").json()["resource"] == "https://sequences.example"
    )
    for path in ("/api/plasmids", "/api/session", "/mcp"):
        response = client.get(path)
        assert response.status_code == 401
        assert 'resource_metadata="https://sequences.example/' in response.headers["www-authenticate"]
    client.headers["Authorization"] = "Bearer " + token()
    result = client.get("/api/plasmids")
    assert result.status_code == 200 and len(result.json()) == 2
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/plasmids", headers={"Host": "attacker.example"}).status_code == 403
    assert client.get("/api/plasmids", headers={"Origin": "https://attacker.example"}).status_code == 403


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"aud": "another-service"}, 401),
        ({"iss": "https://other-issuer.example/"}, 401),
        ({"exp": 1}, 401),
        ({"iat": 9999999999}, 401),
        ({"sub": "github|9999"}, 403),
        ({"scope": "openid profile"}, 403),
        ({"scope": [ACCESS_SCOPE]}, 403),
    ],
)
def test_wrong_tokens_cannot_read_or_write(cloud, changes, status):
    client, token, ws = cloud
    client.headers["Authorization"] = "Bearer " + token(**changes)
    assert client.get("/api/plasmids").status_code == status
    assert (
        client.post("/api/import", json={"genbank": ws.export_genbank("demo-vector")}).status_code == status
    )
    assert len(ws.list_records()) == 2


def test_forged_signature_rejected(cloud):
    client, token, _ = cloud
    claims = jwt.decode(token(), options={"verify_signature": False})
    forged = jwt.encode(
        claims,
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        algorithm="RS256",
        headers={"kid": "synthetic"},
    )
    client.headers["Authorization"] = "Bearer " + forged
    assert client.get("/api/plasmids").status_code == 401
    client.headers["Authorization"] = "Bearer " + jwt.encode(
        claims, "a" * 64, algorithm="HS256", headers={"kid": "synthetic"}
    )
    assert client.get("/api/plasmids").status_code == 401


def test_one_server_web_and_mcp_share_state(cloud):
    client, token, _ = cloud
    client.headers.update(
        {"Authorization": "Bearer " + token(), "Accept": "application/json, text/event-stream"}
    )
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "oauth-test", "version": "1"},
            },
        },
    )
    assert response.status_code == 200, response.text
    client.headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"][
        "tools"
    ]
    assert len(tools) == 10
    assert all(tool["_meta"]["securitySchemes"][0]["scopes"] == [ACCESS_SCOPE] for tool in tools)
    original = client.get("/api/plasmid/demo-vector").json()
    edited = client.post(
        "/api/mutate",
        json={
            "plasmid_id": "demo-vector",
            "expected_revision": original["revision"],
            "position": 0,
            "new_codon": "AAA",
        },
    ).json()
    result = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_record", "arguments": {"record_id": "demo-vector"}},
        },
    ).json()["result"]["structuredContent"]
    assert result["revision"] == edited["revision"] and result["dirty"]


def test_host_requires_complete_auth_configuration(tmp_path, monkeypatch):
    for key in ("SEQATELIER_AUTH_ISSUER", "SEQATELIER_AUTH_CLIENT_ID", "SEQATELIER_AUTH_SUBJECTS"):
        monkeypatch.delenv(key, raising=False)
    assert main(["--workspace", str(tmp_path / "not-created"), "host"]) == 2
    assert not (tmp_path / "not-created").exists()
    monkeypatch.setenv("SEQATELIER_AUTH_ISSUER", "https://login.example")
    with pytest.raises(WorkspaceError):
        OAuthSettings.from_env()


def test_jwks_is_fixed_to_configured_issuer():
    verifier = JWTVerifier(
        OAuthSettings("https://login.example/", "https://sequences.example", "client", ("user",))
    )
    assert verifier.keys.uri == "https://login.example/.well-known/jwks.json"
