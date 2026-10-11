"""
tests/test_mcp_bridge.py
────────────────────────
Comprehensive unit and integration tests for Model Context Protocol (MCP) Bridge
in web/mcp.py.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from web.mcp import MCPServer
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_mcp_server_initialize():
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }
    resp = server.handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "chanakya-trade"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_server_ping():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    resp = server.handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    assert resp["result"] == {}


def test_mcp_server_notifications_initialized():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = server.handle_jsonrpc(req)
    assert resp is None


def test_mcp_server_tools_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    resp = server.handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    tools = resp["result"]["tools"]
    assert isinstance(tools, list)
    assert len(tools) > 0

    tool_names = {t["name"] for t in tools}
    assert "simulate_order_book_sweep" in tool_names
    assert "get_quote" in tool_names

    # Check schema compliance
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        assert isinstance(t["inputSchema"], dict)


def test_mcp_server_tools_call():
    server = MCPServer()
    # Call simulate_order_book_sweep with mock
    mock_sweep = {
        "symbol": "RELIANCE",
        "ltp": 2950.0,
        "provenance": "LIVE",
        "sweep": {
            "side": "BUY",
            "requested_quantity": 50,
            "filled_quantity": 50,
            "sweep_vwap": 2951.2,
            "slippage_bps": 4.07,
            "fillable": True,
        },
    }
    with patch("market.order_book.analyze_symbol_order_book") as mock_analyze:
        mock_snap = MagicMock()
        mock_snap.symbol = "RELIANCE"
        mock_snap.ltp = 2950.0
        mock_snap.provenance = "LIVE"
        mock_snap.simulate_sweep.return_value = mock_sweep["sweep"]
        mock_analyze.return_value = mock_snap

        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "simulate_order_book_sweep",
                "arguments": {"symbol": "RELIANCE", "side": "BUY", "quantity": 50},
            },
        }
        resp = server.handle_jsonrpc(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 4
        assert not resp["result"]["isError"]
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        parsed = json.loads(content[0]["text"])
        assert parsed["symbol"] == "RELIANCE"
        assert parsed["sweep"]["slippage_bps"] == 4.07


def test_mcp_server_tools_call_error_handling():
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool_xyz",
            "arguments": {},
        },
    }
    resp = server.handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 5
    assert resp["result"]["isError"] is True
    assert "Unknown tool" in resp["result"]["content"][0]["text"]


def test_mcp_server_prompts_list_and_get():
    server = MCPServer()
    req_list = {"jsonrpc": "2.0", "id": 6, "method": "prompts/list"}
    resp_list = server.handle_jsonrpc(req_list)
    assert resp_list["id"] == 6
    prompts = resp_list["result"]["prompts"]
    p_names = {p["name"] for p in prompts}
    assert "market_morning_briefing" in p_names
    assert "simulate_order_book_sweep" in p_names

    req_get = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "prompts/get",
        "params": {
            "name": "simulate_order_book_sweep",
            "arguments": {"symbol": "INFY", "side": "SELL", "quantity": "200"},
        },
    }
    resp_get = server.handle_jsonrpc(req_get)
    assert resp_get["id"] == 7
    messages = resp_get["result"]["messages"]
    assert len(messages) == 1
    assert "INFY" in messages[0]["content"]["text"]
    assert "SELL" in messages[0]["content"]["text"]


def test_mcp_server_parse_and_method_errors():
    server = MCPServer()
    # Invalid JSON
    res = server.handle_message_str("NOT JSON {")
    assert "-32700" in res

    # Unknown method
    resp = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 8, "method": "unknown/method"})
    assert resp["error"]["code"] == -32601


def test_mcp_server_batch_processing():
    server = MCPServer()
    batch_str = json.dumps(
        [
            {"jsonrpc": "2.0", "id": 10, "method": "ping"},
            {"jsonrpc": "2.0", "id": 11, "method": "ping"},
        ]
    )
    out = server.handle_message_str(batch_str)
    parsed = json.loads(out)
    assert len(parsed) == 2
    assert parsed[0]["id"] == 10
    assert parsed[1]["id"] == 11


def test_fastapi_mcp_endpoints(client):
    # 1. Metadata endpoint
    r = client.get("/api/mcp")
    assert r.status_code == 200
    meta = r.json()
    assert meta["status"] == "online"
    assert meta["toolCount"] > 0
    assert meta["protocolVersion"] == "2024-11-05"

    # 2. POST /api/mcp JSON-RPC initialize
    r_rpc = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 101, "method": "initialize"},
    )
    assert r_rpc.status_code == 200
    res = r_rpc.json()
    assert res["id"] == 101
    assert res["result"]["protocolVersion"] == "2024-11-05"

    # 3. POST /api/mcp tools/list
    r_tools = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 102, "method": "tools/list"},
    )
    assert r_tools.status_code == 200
    res_tools = r_tools.json()
    assert "tools" in res_tools["result"]

    # 4. POST /api/mcp/messages without valid session -> 404
    r_msg = client.post(
        "/api/mcp/messages?session_id=invalid-session",
        json={"jsonrpc": "2.0", "id": 103, "method": "ping"},
    )
    assert r_msg.status_code == 404
