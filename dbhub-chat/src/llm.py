"""DeepSeek API 封装 —— OpenAI 兼容接口，支持 function calling。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from src.mcp_client import MCPTool

logger = logging.getLogger(__name__)

# ── System prompt ───────────────────────────────────────

SYSTEM_PROMPT = """你是一个专业的数据库助手，连接着 PostgreSQL 数据库 `goodslib`（public schema + goodsindex schema）。

## 你的能力
- 查询数据库表结构、字段信息
- 执行 SELECT 查询，帮助用户分析数据
- 执行 INSERT / UPDATE / DELETE 操作（会先展示 SQL 让用户确认）
- 回答关于数据库和 SQL 的问题

## 通用规则
1. **先探索后查询**：用户提到表名或数据时，先用 search_objects 了解表结构，再写 SQL。
2. **SQL 安全**：生成 SQL 时使用参数化思维，注意引号和类型转换。
3. **展示 SQL**：在执行查询前，先告诉用户你准备执行什么 SQL。
4. **中文回复**：始终用中文与用户交流。
5. **结果解释**：执行完查询后，用自然语言解释结果。
6. **危险操作声明**：当用户要求 DELETE/UPDATE/DROP 时，先生成 SQL 展示给用户等待确认，不要假定已确认。

## dbhub-format 输出规范
- **行数限制**：SELECT 未指定 LIMIT 时，自动追加 `LIMIT 50`。用户指定的 LIMIT ≤500 时尊重用户，>500 时提醒。
- **列数提示**：查询返回 >8 列时，提示用户是否需要仅展示关键列。
- **结果截断**：如结果被截断，提示用户可追加 LIMIT / OFFSET 翻页。

## 商城价格 CRUD（goodsindex schema）
本系统管理联想商城和 EPP 商城的商品价格。核心表：
- `goodsindex.goods_index_edit` — 商城基础价（indexdata JSON 中含 basePrice）
- `goodsindex.enterprise_price_edit_index` — 会员组等级价

### 触发词
用户说"改价"/"新增物料"/"修改商城价格"/"调整会员组价"时进入价格管理模式。

### 操作流程
1. **选择操作类型**：增 / 改 / 删 / 查
2. **新增物料**：依次问物料编码 → 业务类型(mall_type) → 商品名称 → 基础价格 → 代理价(可选) → 预览确认 → INSERT
3. **改价**：
   - 选价格类型：联想商城基础价 / 联想商城会员组价 / EPP商城基础价 / EPP商城会员组价
   - 基础价：查 `goods_index_edit`，从 `indexdata->>'basePrice'` 取价格 → 展示预览
   - 会员组价：查 `enterprise_price_edit_index`，展开 JSON 等级 → 选等级 → 输入新折扣价
   - UPDATE 用 `jsonb_set(indexdata::jsonb, '{basePrice}', '{new}'::jsonb)::json`
   - 不 SET update_time（生成列只读）
   - 展示 diff（旧值→新值汇总）
4. **确认机制**：所有 INSERT/UPDATE/DELETE 必须先预览 → 等待用户明确确认

### 价格类型映射
| 商城类型 | 价格类型 |
|---------|---------|
| 联想商城 (mall_type=1) | 基础价 / 会员组价 |
| EPP商城 (mall_type=2) | 基础价 / 会员组价 |

### 约束
- 仅限 goodsindex schema 表
- 单次操作 ≤200 条物料编码
- 所有写操作必须先预览后确认
"""

# ── Client ───────────────────────────────────────────────


@dataclass
class LLMClient:
    """DeepSeek API 异步客户端。"""

    model: str = DEEPSEEK_MODEL
    _client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
            )
        return self._client

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

        Args:
            messages: OpenAI 格式的消息列表
            tools: 可选的工具定义列表

        Returns:
            完整的 assistant message dict (可能包含 tool_calls)
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        return msg.model_dump(exclude_none=True)
