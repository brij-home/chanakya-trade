"""
web/mcp.py
──────────
Model Context Protocol (MCP) Bridge for ChanakyaTrade.
Compliant with MCP specification (JSON-RPC 2.0, protocol version 2024-11-05).

Provides native discovery and execution of ChanakyaTrade quantitative tools,
market models, order book sweep simulators, and prompts for external agents:
  - Claude Desktop / Claude Code
  - Cursor & Windsurf
  - Google Antigravity (AGY) Agents
  - Custom LLM / Multi-Agent Frameworks

Supports Dual Transport:
  1. Stdio Transport:
     CLI invocation: python -m web.mcp (reads stdin, writes stdout)
  2. HTTP & SSE Transport:
     FastAPI endpoints mounted at /api/mcp
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent.tools import ToolRegistry, build_registry
from web.routers.common import require_localhost

logger = logging.getLogger("chanakya.web.mcp")

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_INFO = {
    "name": "chanakya-trade",
    "version": "1.0.0",
}


# ── Curated Institutional MCP Prompts ─────────────────────────────────────────

PROMPTS_REGISTRY = {
    "market_morning_briefing": {
        "name": "market_morning_briefing",
        "description": (
            "Comprehensive morning quant market briefing on Indian benchmark indices "
            "(Nifty 50, Bank Nifty, Sensex), GIFT Nifty sentiment, and institutional FII/DII flows."
        ),
        "arguments": [],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "Generate a pre-market institutional briefing for Indian markets. "
                        "Query live benchmark quotes, GIFT Nifty premium/discount, institutional FII/DII "
                        "net flows, and sector rotation momentum. Formulate key support/resistance zones "
                        "and actionable trading blueprints."
                    ),
                },
            }
        ],
    },
    "simulate_order_book_sweep": {
        "name": "simulate_order_book_sweep",
        "description": (
            "Simulate aggressive market sweep through 50-depth L3 order book, calculating "
            "exact sweep VWAP, basis-point slippage, consumed levels, and market impact."
        ),
        "arguments": [
            {
                "name": "symbol",
                "description": "Stock or derivative ticker, e.g. RELIANCE, NIFTY",
                "required": True,
            },
            {
                "name": "side",
                "description": "BUY or SELL",
                "required": False,
            },
            {
                "name": "quantity",
                "description": "Quantity to sweep",
                "required": False,
            },
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "Audit order book depth up to 50 levels for {symbol}. "
                        "Simulate a {side} sweep of {quantity} units and determine whether "
                        "slippage exceeds institutional tolerance."
                    ),
                },
            }
        ],
    },
    "forensic_accounting_audit": {
        "name": "forensic_accounting_audit",
        "description": (
            "Deep forensic accounting and bankruptcy solvency audit using Beneish M-Score, "
            "Altman Z-Score, and Piotroski F-Score."
        ),
        "arguments": [
            {
                "name": "symbol",
                "description": "NSE listed stock ticker, e.g. TRENT, INFY",
                "required": True,
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "Execute an institutional forensic audit on {symbol}. Calculate Beneish M-Score "
                        "for earnings manipulation risk, Altman Z-Score for bankruptcy distress, and "
                        "Piotroski F-Score for financial health."
                    ),
                },
            }
        ],
    },
    "supercharge_strategy": {
        "name": "supercharge_strategy",
        "description": (
            "Multi-agent 12-seat specialist strategist council review of backtested strategy, "
            "evaluating Sharpe, Sortino, max drawdown, and applying anti-overfitting vetoes."
        ),
        "arguments": [
            {
                "name": "strategy_name",
                "description": "Strategy identifier or baseline name",
                "required": True,
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "Convene the 12-seat strategist council to analyze strategy '{strategy_name}'. "
                        "Evaluate performance, risk parameters, execution friction, and run the 4 binding "
                        "veto gates against ruin risk."
                    ),
                },
            }
        ],
    },
}


# ── Core MCP Server Engine ────────────────────────────────────────────────────


class MCPServer:
    """Institutional-grade Model Context Protocol (MCP) engine."""

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry or build_registry()
        self.protocol_version = MCP_PROTOCOL_VERSION
        self.server_info = MCP_SERVER_INFO
        self.sse_sessions: dict[str, asyncio.Queue] = {}

    def get_tools_list(self) -> list[dict[str, Any]]:
        """Return tools formatted to MCP specification."""
        tools = []
        for name, t in self.registry._tools.items():
            if t.get("permission") == "deny":
                continue
            tools.append(
                {
                    "name": name,
                    "description": t.get("description", ""),
                    "inputSchema": t.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return tools

    def get_prompts_list(self) -> list[dict[str, Any]]:
        """Return prompts formatted to MCP specification."""
        prompts = []
        for p in PROMPTS_REGISTRY.values():
            prompts.append(
                {
                    "name": p["name"],
                    "description": p["description"],
                    "arguments": p.get("arguments", []),
                }
            )
        return prompts

    def handle_jsonrpc(self, req: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Process a single JSON-RPC 2.0 message synchronously or offloaded.
        Returns a JSON-RPC response dict, or None for notifications.
        """
        if not isinstance(req, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request: expected JSON object"},
            }

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        # 1. Notifications without id require no response
        if method == "notifications/initialized":
            logger.info("[MCP] Client initialized notification received")
            return None

        if method is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"},
            }

        # 2. Handshake / Lifecycle
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": self.server_info,
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        # 3. Tools Discovery
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tools_list()},
            }

        # 4. Tools Execution
        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}

            if not tool_name or not isinstance(tool_name, str):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params: 'name' is required and must be a string",
                    },
                }

            try:
                res = self.registry.execute(tool_name, tool_args)
                is_err = False
                err_text = ""

                if isinstance(res, dict) and "error" in res:
                    is_err = True
                    err_text = str(res["error"])
                    if "trace" in res:
                        err_text += f"\nTraceback:\n{res['trace']}"
                    text_content = err_text
                else:
                    if isinstance(res, (dict, list)):
                        text_content = json.dumps(res, indent=2, default=str)
                    else:
                        text_content = str(res)

                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": text_content,
                            }
                        ],
                        "isError": is_err,
                    },
                }
            except Exception as exc:
                logger.error(
                    f"[MCP] Execution failure for tool '{tool_name}': {exc}", exc_info=True
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Tool execution exception: {str(exc)}",
                            }
                        ],
                        "isError": True,
                    },
                }

        # 5. Prompts Discovery
        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": self.get_prompts_list()},
            }

        if method == "prompts/get":
            prompt_name = params.get("name")
            prompt_def = PROMPTS_REGISTRY.get(prompt_name)
            if not prompt_def:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Prompt not found: {prompt_name}"},
                }

            prompt_args = params.get("arguments") or {}
            # Format arguments into messages
            formatted_messages = []
            for msg in prompt_def.get("messages", []):
                text = msg.get("content", {}).get("text", "")
                for k, v in prompt_args.items():
                    text = text.replace(f"{{{k}}}", str(v))
                formatted_messages.append(
                    {
                        "role": msg.get("role", "user"),
                        "content": {"type": "text", "text": text},
                    }
                )

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": prompt_def["description"],
                    "messages": formatted_messages,
                },
            }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def handle_message_str(self, line: str) -> Optional[str]:
        """Parse raw text line as JSON-RPC, process, and return serialized response."""
        line = line.strip()
        if not line:
            return None
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(exc)}"},
                }
            )

        if isinstance(req, list):
            # Batch request
            responses = []
            for item in req:
                resp = self.handle_jsonrpc(item)
                if resp is not None:
                    responses.append(resp)
            return json.dumps(responses) if responses else None

        resp = self.handle_jsonrpc(req)
        return json.dumps(resp) if resp is not None else None

    def run_stdio(self) -> None:
        """Run standard I/O loop for Claude Desktop / Cursor / CLI agents."""
        # Ensure utf-8 I/O
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")

        # Stderr logging to keep stdout strictly for JSON-RPC
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stderr,
        )
        logger.info("[MCP] Starting ChanakyaTrade MCP Server in stdio mode...")

        try:
            for line in sys.stdin:
                output = self.handle_message_str(line)
                if output:
                    sys.stdout.write(output + "\n")
                    sys.stdout.flush()
        except KeyboardInterrupt:
            logger.info("[MCP] Stdio loop terminated by user")
        except Exception as exc:
            logger.error(f"[MCP] Stdio loop encountered fatal error: {exc}", exc_info=True)


# ── Global Server Singleton & FastAPI Router ──────────────────────────────────

mcp_server = MCPServer()
mcp_router = APIRouter(prefix="/api/mcp", tags=["Model Context Protocol (MCP)"])


@mcp_router.get("", summary="MCP Server Capabilities & Metadata")
async def get_mcp_metadata(request: Request):
    """Inspect MCP protocol capabilities and tool counts."""
    require_localhost(request)
    return {
        "status": "online",
        "protocolVersion": mcp_server.protocol_version,
        "serverInfo": mcp_server.server_info,
        "toolCount": len(mcp_server.get_tools_list()),
        "promptCount": len(mcp_server.get_prompts_list()),
        "endpoints": {
            "jsonrpc_http": "/api/mcp",
            "sse_stream": "/api/mcp/sse",
            "messages": "/api/mcp/messages",
        },
    }


@mcp_router.post("", summary="MCP JSON-RPC HTTP Endpoint")
async def post_mcp_jsonrpc(request: Request):
    """Direct HTTP JSON-RPC 2.0 processor for single or batch requests."""
    require_localhost(request)
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(exc)}"},
            },
        )

    if isinstance(body, list):
        # Process batch concurrently / offloaded
        results = await asyncio.gather(
            *[asyncio.to_thread(mcp_server.handle_jsonrpc, req) for req in body]
        )
        responses = [r for r in results if r is not None]
        return JSONResponse(content=responses if responses else {})

    resp = await asyncio.to_thread(mcp_server.handle_jsonrpc, body)
    if resp is None:
        return JSONResponse(status_code=204, content=None)
    return JSONResponse(content=resp)


@mcp_router.get("/sse", summary="MCP Server-Sent Events Stream")
async def mcp_sse_endpoint(request: Request):
    """MCP SSE Transport connection establishing bidirectional session."""
    require_localhost(request)
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    mcp_server.sse_sessions[session_id] = queue
    logger.info(f"[MCP] SSE client connected (session_id={session_id})")

    async def event_generator():
        # First event informs client of the message dispatch URL
        endpoint_url = f"/api/mcp/messages?session_id={session_id}"
        yield f"event: endpoint\ndata: {endpoint_url}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            mcp_server.sse_sessions.pop(session_id, None)
            logger.info(f"[MCP] SSE client disconnected (session_id={session_id})")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@mcp_router.post("/messages", summary="MCP SSE Session Message Dispatcher")
async def mcp_post_message(
    request: Request,
    session_id: str = Query(..., description="Active MCP session ID from SSE"),
):
    """Dispatches a JSON-RPC request to an active SSE session."""
    require_localhost(request)
    session_queue = mcp_server.sse_sessions.get(session_id)
    if not session_queue:
        raise HTTPException(status_code=404, detail="Invalid or expired MCP session ID")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    resp = await asyncio.to_thread(mcp_server.handle_jsonrpc, body)
    if resp is not None:
        try:
            session_queue.put_nowait(resp)
        except asyncio.QueueFull:
            logger.warning(f"[MCP] Queue full for session {session_id}, dropping response")

    return JSONResponse(status_code=202, content={"status": "accepted"})


if __name__ == "__main__":
    mcp_server.run_stdio()
