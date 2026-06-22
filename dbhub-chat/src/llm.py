"""LLM API 封装 —— OpenAI 兼容接口，支持 function calling（DeepSeek / Qwen 等）。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.mcp_client import MCPTool

logger = logging.getLogger(__name__)

# ── System prompt ───────────────────────────────────────

SYSTEM_PROMPT = """你是一个专业的数据库助手，连接着 PostgreSQL 数据库 `goodslib`（public schema + goodsindex schema）。

## 你的能力
- 查询数据库表结构、字段信息
- 执行 SELECT 查询，帮助用户分析数据
- 执行 INSERT / UPDATE / DELETE 操作（会先展示 SQL 让用户确认）
- 回答关于数据库和 SQL 的问题

## 回复风格（非常重要）
- **直接执行，不等指令**：用户提出需求后，立即调工具执行。不要先回复"好的我来帮你……"然后等用户再说"开始"，也不要反问"需要我帮你查询吗？"——直接查。
- **一次说全**：回答要充分、完整。查询结果出来后，同时给出：① 数据概要 ② 关键发现 ③ 下一步建议。不要只丢一个结果等用户追问。
- **主动推进流程**：每一步都主动推进，减少来回对话次数。
- **解释要通俗**：数据库术语用通俗语言解释，让非技术人员也能理解。

## 通用规则
1. **先探索后查询**：用户提到表名或数据时，先用 search_objects 了解表结构，再写 SQL。
2. **SQL 安全**：生成 SQL 时注意引号和类型转换。
3. **展示 SQL**：在执行查询前，先告诉用户你准备执行什么 SQL。
4. **中文回复**：始终用中文与用户交流。
5. **结果解释**：执行完查询后，用自然语言解释结果。
6. **危险操作声明**：当用户要求 DELETE/UPDATE/DROP 时，先生成 SQL 展示给用户等待确认。
7. **错误恢复**：SQL 报错时不要自动重试，先解释错误含义。最多 1 次修正，还报错就交给用户决定。
8. **写操作验证**：INSERT/UPDATE/DELETE 末尾加 `RETURNING *`，直接从返回值确认结果。
9. **自动 LIMIT**：SELECT 未指定 LIMIT 时自动追加 `LIMIT 50`；用户指定 ≤500 则尊重，>500 则提醒。
10. **Markdown 表格输出**：查询结果以 Markdown 表格呈现，含 SQL 和行数。NULL 显示 `-`，日期格式化为 `YYYY-MM-DD`，金额列加 `¥`。

---

## 可用 Skill（当系统消息中包含对应 Skill 时，严格遵守其规则）

| Skill | 触发条件 | 用途 |
|-------|---------|------|
| `dbhub-format` | 任何查询结果输出时 | 自动格式化：LIMIT 50、Markdown 表格、类型感知（日期/金额/NULL/JSON） |
| `mall-price-crud` | 提到改价/新增物料/SN/goodsindex 等 | 商城价格 CRUD：字段语义确认→全表搜索→预览确认→执行 |

当你收到的系统消息中包含了某个 Skill 的完整规则时，**必须严格遵守该 Skill 的操作流程，不得跳过任何步骤**。未包含的 Skill 无需关注。
"""

# ── Client ───────────────────────────────────────────────


@dataclass
class LLMClient:
    """LLM API 异步客户端（直接 httpx，避免 OpenAI 库添加额外字段）。"""

    model: str = LLM_MODEL

    # ── tool schema conversion ──────────────────────

    @staticmethod
    def tools_to_openai(tools: list[MCPTool]) -> list[dict]:
        """将 MCP 工具列表转为 OpenAI function-calling 格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    # ── chat ────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """发送聊天请求，返回完整的 message 对象。

        直接使用 httpx 而非 OpenAI 库，避免后者自动添加 Qwen 不支持的字段。
        """
        import httpx as _httpx

        url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        if tools:
            body["tools"] = tools

        # 每次请求创建新的 httpx 客户端，避免跨线程事件循环冲突
        async with _httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=body)

        if r.status_code != 200:
            raise RuntimeError(f"LLM API 错误 [{r.status_code}]: {r.text[:500]}")

        data = r.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})

        # ── Qwen 思考模型兼容 ──
        # Qwen3.5 先输出 reasoning_content（思考），再输出 content（回答）。
        if not msg.get("content") and msg.get("reasoning_content"):
            msg["content"] = msg["reasoning_content"]

        # 确保 content 字段始终存在
        if "content" not in msg:
            msg["content"] = None

        return msg
