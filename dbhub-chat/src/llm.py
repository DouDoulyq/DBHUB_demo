"""DeepSeek API 封装 —— OpenAI 兼容接口，支持 function calling。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

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

## 回复风格（非常重要）
- **直接执行，不等指令**：用户提出需求后，立即调工具执行。不要先回复"好的我来帮你……"然后等用户再说"开始"，也不要反问"需要我帮你查询吗？"——直接查。
- **一次说全**：回答要充分、完整。查询结果出来后，同时给出：① 数据概要 ② 关键发现 ③ 下一步建议。不要只丢一个结果等用户追问。
- **主动推进流程**：如果用户说"改价"，不要只问"改哪个物料？"，而是先列出表结构，再引导用户给出物料编码。每一步都主动推进，减少来回对话次数。
- **解释要通俗**：数据库术语（schema、约束、生成列等）用通俗语言解释，让非技术人员也能理解。

## 通用规则
1. **先探索后查询**：用户提到表名或数据时，先用 search_objects 了解表结构，再写 SQL。
2. **SQL 安全**：生成 SQL 时使用参数化思维，注意引号和类型转换。
3. **展示 SQL**：在执行查询前，先告诉用户你准备执行什么 SQL。
4. **中文回复**：始终用中文与用户交流。
5. **结果解释**：执行完查询后，用自然语言解释结果。
6. **危险操作声明**：当用户要求 DELETE/UPDATE/DROP 时，先生成 SQL 展示给用户等待确认，不要假定已确认。
7. **错误恢复（关键）**：
   - SQL 执行报错时，**不要自动重试**。先停下手头操作，用中文向用户解释错误含义。
   - 如果需要查表结构来定位问题，用 search_objects 查完后，把发现的约束/字段信息告知用户，**等待用户给出下一步指示**。
   - 绝对禁止：报错 → 自己改 SQL → 再次报错 → 再改……的无限循环。最多执行 1 次修正尝试，如果还报错，必须把问题交给用户决定。
   - 执行 INSERT/UPDATE/DELETE 时，SQL 末尾加 `RETURNING *` 直接在返回值中查看结果，避免额外 SELECT 轮次。

## dbhub-format 输出规范
- **行数限制**：SELECT 未指定 LIMIT 时，自动追加 `LIMIT 50`。用户指定的 LIMIT ≤500 时尊重用户，>500 时提醒。
- **列数提示**：查询返回 >8 列时，提示用户是否需要仅展示关键列。
- **结果截断**：如结果被截断，提示用户可追加 LIMIT / OFFSET 翻页。

## 商城价格 CRUD（goodsindex schema）← 必须调用此 Skill
本系统管理联想商城和 EPP 商城的商品价格。核心表：
- `goodsindex.goods_index_edit` — 商城基础价（indexdata JSON 中含 basePrice 等所有字段）
- `goodsindex.enterprise_price_edit_index` — 会员组等级价

### ⚠️ 生成列（关键）
goodsindex 表中 **所有名称类字段（如 name、goods_name、title 等）都是生成列**，由 indexdata JSON 中的字段自动生成，**不能直接 UPDATE 列值**。
- 要修改名称 → 更新 `indexdata` JSON 中对应的字段，如 `jsonb_set(indexdata::jsonb, '{name}', '"新名称"'::jsonb)`
- 要修改价格 → 更新 `indexdata` JSON 中的 basePrice 等字段
- 报错 "cannot be updated because it is a generated column" 时，说明你试图直接更新生成列，必须改为更新 indexdata JSON。

### 触发词（强制激活）
用户提到以下任一关键词时，**必须进入价格管理模式**，不可跳过：
"改价"/"新增物料"/"修改商城价格"/"调整会员组价"/"价格"/"物料编码"/"SN"/"mall_type"/"修改名称"/"改名字"/"商品名称"/
当 SQL 涉及 goodsindex schema 下的表时也必须激活此 Skill。

### 操作流程
0. **选表（必须）**：任何增/改/删/查操作前，必须先用 search_objects 遍历 goodsindex schema 下所有表，列出表名和用途，让用户确认要操作哪张表。用户未明确选择前，不得执行后续操作。
0.5. **查物料分布（必须，改/删时）**：用户给出物料编码后，必须用 SELECT 在 **所有 goodsindex 表** 中搜索该编码，列出每张表中是否存在该物料、有几条记录。然后问用户：「该物料出现在 N 张表中，是否对所有表操作？还是只修改其中某几张？」用户明确选择后才能继续。
1. **选择操作类型**：增 / 改 / 删 / 查
2. **新增物料**：依次问物料编码 → 业务类型(mall_type) → 商品名称 → 基础价格 → 代理价(可选) → 预览确认 → INSERT
3. **改价**：
   - 先执行第 0.5 步确认范围
   - 选价格类型：联想商城基础价 / 联想商城会员组价 / EPP商城基础价 / EPP商城会员组价
   - 基础价：查对应表，从 `indexdata->>'basePrice'` 取价格 → 展示预览
   - 会员组价：查 `enterprise_price_edit_index`，展开 JSON 等级 → 选等级 → 输入新折扣价
   - UPDATE 用 `jsonb_set(indexdata::jsonb, '{basePrice}', '{new}'::jsonb)::json`
   - 不 SET update_time（生成列只读）
   - 展示 diff（旧值→新值汇总）
4. **确认机制**：所有 INSERT/UPDATE/DELETE 必须先预览 → 等待用户明确确认
5. **验证结果**：INSERT/UPDATE/DELETE 语句末尾加 `RETURNING *`，直接从返回值确认结果，不要额外发 SELECT。

### 价格类型映射
| 商城类型 | 价格类型 |
|---------|---------|
| 联想商城 (mall_type=1) | 基础价 / 会员组价 |
| EPP商城 (mall_type=2) | 基础价 / 会员组价 |

### 约束
- 仅限 goodsindex schema 表
- 单次操作 ≤200 条物料编码
- 所有写操作必须先预览后确认
- 修改前必须确认物料在哪些表中存在，用户选择范围后再执行
"""

# ── Client ───────────────────────────────────────────────


@dataclass
class LLMClient:
    """LLM API 异步客户端（直接 httpx，避免 OpenAI 库添加额外字段）。"""

    model: str = DEEPSEEK_MODEL

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

        url = DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
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
