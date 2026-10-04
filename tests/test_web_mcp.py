import asyncio
import sys

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from seqatelier.demo import initialize_demo
from seqatelier.mcp_server import create_http_app, create_server
from seqatelier.web import create_app
from seqatelier.workspace import Workspace

TOKEN = "synthetic-test-token-" * 3


@pytest.fixture
def workspace(tmp_path):
    ws = Workspace(tmp_path / "data")
    initialize_demo(ws)
    return ws


def test_web_auth_remote_host_origin_and_restart(workspace):
    with TestClient(create_app(workspace, token=TOKEN), base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/plasmids").status_code == 401
        client.headers["Authorization"] = "Bearer " + TOKEN
        assert client.get("/api/plasmids").status_code == 200
        assert client.get("/api/plasmids", headers={"Origin": "https://unrelated.example"}).status_code == 403
        original = client.get("/api/plasmid/demo-vector").json()
        mutation = {
            "plasmid_id": original["id"],
            "expected_revision": original["revision"],
            "position": 0,
            "new_codon": "AAA",
        }
        edited = client.post("/api/mutate", json=mutation)
        assert edited.status_code == 200 and edited.json()["dirty"]
        assert client.post("/api/mutate", json=mutation).status_code == 409
        assert client.post("/api/save", json={"plasmid_id": original["id"]}).status_code == 422
    with TestClient(
        create_app(Workspace(workspace.path), token=""), base_url="http://localhost"
    ) as restarted:
        current = restarted.get("/api/plasmid/demo-vector").json()
        assert current == edited.json()
        assert restarted.get("/api/plasmids", headers={"Host": "attacker.example"}).status_code == 403
        payload = {"plasmid_id": current["id"], "expected_revision": current["revision"]}
        assert restarted.post("/api/save", json=payload).status_code == 200
        text = restarted.get("/api/plasmid/demo-vector/genbank").text
        assert "LOCUS" in text
        imported = restarted.post("/api/import", json={"genbank": text})
        assert imported.status_code == 200 and imported.json()["id"] != current["id"]


def test_web_annotation_qualifiers_and_validation(workspace):
    with TestClient(create_app(workspace, token=""), base_url="http://localhost") as client:
        data = client.get("/api/plasmid/demo-vector").json()
        feature = data["features"][0]
        payload = {
            "plasmid_id": data["id"],
            "expected_revision": data["revision"],
            "action": "update",
            "index": 0,
            "feature": {k: feature[k] for k in ("type", "label", "start", "end", "strand")},
        }
        payload["feature"]["label"] = "Renamed CDS"
        response = client.post("/api/annotate", json=payload)
        assert response.status_code == 200
        assert response.json()["features"][0]["label"] == "Renamed CDS"
        assert client.post("/api/annotate", json=payload).status_code == 409
        assert client.post("/api/translate", json={"sequence": "NOT DNA"}).status_code == 422
        assert (
            client.post("/api/tm", json={"sequence": "ATGCGCATGC", "primer_conc_nm": -1}).status_code == 422
        )


def test_mcp_readonly_and_write_tools(workspace):
    async def check():
        async with Client(create_server(workspace)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "preview" in names and "save_design_result" not in names and "import_genbank" not in names
            result = await client.call_tool(
                "get_sequence", {"record_id": "demo-vector", "start_bp": 301, "end_bp": 303}
            )
            assert result.structured_content["sequence"] == "ATG"
            invalid = await client.call_tool(
                "get_sequence", {"record_id": "demo-vector", "start_bp": 0, "end_bp": 3}
            )
            assert invalid.is_error
        async with Client(create_server(workspace, allow_writes=True)) as client:
            params = {
                "template_id": "demo-vector",
                "cds_feature_label": "demo_CDS",
                "residue_number": 2,
                "new_amino_acid": "R",
            }
            preview = await client.call_tool("preview", {"method": "point_mutation", "parameters": params})
            assert not preview.is_error
            saved = await client.call_tool(
                "save_design_result",
                {
                    "method": "point_mutation",
                    "parameters": params,
                    "expected_revisions": preview.structured_content["source_revisions"],
                },
            )
            assert not saved.is_error
            assert workspace.get_design(saved.structured_content["id"])["method"] == "point_mutation"

    asyncio.run(check())


def test_mcp_stdio_real_process(workspace):
    async def check():
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "seqatelier", "--workspace", str(workspace.path), "mcp"]
        )
        async with Client(server) as client:
            response = await client.call_tool("list_records", {"query": "demo"})
            assert not response.is_error and len(response.structured_content["records"]) == 2

    asyncio.run(check())


def test_mcp_streamable_http_handshake_and_tool_call(workspace):
    app = create_http_app(workspace, token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Accept"] = "application/json, text/event-stream"
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "1"},
            },
        }
        assert client.post("/mcp", json=request).status_code == 401
        client.headers["Authorization"] = "Bearer " + TOKEN
        response = client.post("/mcp", json=request)
        assert response.status_code == 200, response.text
        assert "serverInfo" in response.json()["result"]
        client.headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
        result = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_records", "arguments": {}},
            },
        )
        assert result.status_code == 200, result.text
        assert len(result.json()["result"]["structuredContent"]["records"]) == 2
