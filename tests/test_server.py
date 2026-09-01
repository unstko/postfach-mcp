"""End-to-end over the ASGI app: health, auth gate, and one real MCP
round-trip (initialize + tools/list) as a regression guard against SDK
drift — if an SDK update changes the transport, these fail first."""

import pytest
from starlette.testclient import TestClient

from postfach_mcp import config, server

TOKEN = "t" * 32

EXPECTED_TOOLS = {
    "list_folders",
    "folder_status",
    "list_messages",
    "search_messages",
    "get_message",
    "create_draft",
    "mark_read",
    "mark_flagged",
    "move_messages",
}


def make_settings(account, allowed_hosts=("testserver",)) -> config.Settings:
    return config.Settings(
        host="127.0.0.1",
        port=8000,
        token=TOKEN,
        allowed_hosts=allowed_hosts,
        account=account,
    )


@pytest.fixture
def client(account):
    # The context manager runs the lifespan; without it the MCP session
    # manager never starts.
    with TestClient(server.build_app(make_settings(account))) as c:
        yield c


def rpc(client: TestClient, method: str, params: dict, id_: int = 1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )


def initialize_params() -> dict:
    return {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }


def test_health_without_token(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["server"] == "postfach-mcp"


def test_mcp_requires_token(client):
    response = client.post("/mcp", json={})
    assert response.status_code == 401


def test_initialize_roundtrip(client):
    response = rpc(client, "initialize", initialize_params())
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["serverInfo"]["name"] == "postfach-mcp"


def test_tools_list_is_exactly_the_nine(client):
    rpc(client, "initialize", initialize_params())
    response = rpc(client, "tools/list", {}, id_=2)
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == EXPECTED_TOOLS
    assert not any(n.startswith(("send", "delete")) for n in names)


def test_extra_token_accepted_end_to_end(account):
    extra = "e" * 32
    settings = config.Settings(
        host="127.0.0.1",
        port=8000,
        token=TOKEN,
        allowed_hosts=("testserver",),
        account=account,
        extra_tokens=(extra,),
    )
    with TestClient(server.build_app(settings)) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": initialize_params()},
            headers={
                "Authorization": f"Bearer {extra}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200


def test_foreign_host_header_rejected(account):
    # DNS-rebinding protection: a Host name outside allowed_hosts must not
    # reach the MCP app. This is the documented 421 trap behind a proxy.
    app = server.build_app(make_settings(account, allowed_hosts=("mail.example.org",)))
    with TestClient(app) as client:
        response = rpc(client, "initialize", initialize_params())
        assert response.status_code == 421


def test_build_app_requires_token(account):
    settings = config.Settings(
        host="127.0.0.1", port=8000, token=None, allowed_hosts=(), account=account
    )
    with pytest.raises(ValueError, match="token"):
        server.build_app(settings)
