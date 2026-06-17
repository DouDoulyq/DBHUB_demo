"""MCP HTTP 客户端 —— 通过 Streamable HTTP 传输连接 DBHub MCP Server。

JSON-RPC 2.0 over HTTP，支持 initialize / tools/list / tools/call。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config import DBHUB_MCP_URL

logger = logging.getLogger(__name__)

# ── JSON-RPC helpers ────────────────────────────────────


def _rpc_request(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": req_id}


# ── Tool model ──────────────────────────────────────────


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the tool's input


# ── Client ──────────────────────────────────────────────


@dataclass
class MCPClient:
    """MCP HTTP 客户端 —— 封装 DBHub 的工具发现与调用。"""

    url: str = field(default_factory=lambda: DBHUB_MCP_URL)
    _tools: list[MCPTool] = field(default_factory=list, init=False)
    _req_id: int = field(default=0, init=False)
    _session_id: str | None = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)

    # ── session ─────────────────────────────────────

    async def initialize(self) -> dict:
        """发送 initialize 握手，保存 session id（如果服务端返回）。"""
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dbhub-chat", "version": "1.0.0"},
        }
        resp = await self._call("initialize", params)
        self._initialized = True
        return resp

    # ── tools ───────────────────────────────────────

    async def list_tools(self) -> list[MCPTool]:
        """获取 DBHub 提供的所有工具列表。"""
        resp = await self._call("tools/list")
        tools_raw: list[dict] = resp.get("tools", [])
        self._tools = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {}),
            )
            for t in tools_raw
        ]
        logger.info("发现 %d 个 MCP 工具: %s", len(self._tools), [t.name for t in self._tools])
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """调用指定工具，返回结果的 content 部分。"""
        resp = await self._call("tools/call", {"name": name, "arguments": arguments})
        # MCP tools/call 返回 { content: [{type:"text", text:"..."}] }
        content = resp.get("content", [])
        if content and isinstance(content, list):
            return "".join(c.get("text", "") for c in content if c.get("type") == "text")
        return resp

    # ── low-level ───────────────────────────────────

    @property
    def _endpoint(self) -> str:
        """DBHub MCP JSON-RPC 端点。"""
        return self.url.rstrip("/") + "/mcp"

    async def _call(self, method: str, params: dict | None = None) -> dict:
        """发送一条 JSON-RPC 请求，返回 result 或 raise。"""
        self._req_id += 1
        body = _rpc_request(method, params, self._req_id)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(self._endpoint, json=body, headers=headers)

        # 捕获 session id
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid

        if r.status_code != 200:
            raise RuntimeError(f"MCP 请求失败 ({r.status_code}): {r.text}")

        data: dict = r.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP 错误 [{err.get('code')}]: {err.get('message')}")

        return data.get("result", {})

    # ── convenience ─────────────────────────────────

    async def execute_sql(self, sql: str) -> str:
        """执行 SQL 语句（DBHub 的 execute_sql 工具）。"""
        return await self.call_tool("execute_sql", {"sql": sql})

    async def search_objects(
        self,
        object_type: str,
        pattern: str = "%",
        schema: str = "public",
        detail_level: str = "summary",
    ) -> str:
        """搜索数据库对象（表/视图/列等）。"""
        return await self.call_tool(
            "search_objects",
            {
                "object_type": object_type,
                "pattern": pattern,
                "schema": schema,
                "detail_level": detail_level,
            },
        )

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools
