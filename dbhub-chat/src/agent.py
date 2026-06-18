"""智能体核心 —— 支持分步执行的 tool-use 循环，适配 Streamlit 请求-响应模式。

每一步是一个独立的 async 调用，状态通过 messages 列表在 session_state 中传递。
危险 SQL 会被拦截并返回 ConfirmationNeeded，等待用户确认后继续。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto

from src.config import DEEPSEEK_MODEL
from src.llm import LLMClient, SYSTEM_PROMPT
from src.mcp_client import MCPClient
from src.safety import classify_sql, ConfirmationRequest, needs_confirmation

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 12
MAX_CONSECUTIVE_ERRORS = 3


# ── Step 结果类型 ───────────────────────────────────────


class StepKind(Enum):
    DONE = auto()          # 对话完成，content=最终回复
    TOOL_CALLS = auto()    # 需要执行工具调用（安全）
    NEED_CONFIRM = auto()  # 遇到危险 SQL，需要用户确认
    ERROR = auto()         # 出错


@dataclass
class StepResult:
    kind: StepKind
    messages: list[dict]           # 当前完整消息历史
    content: str = ""              # DONE 时的文本回复；ERROR 时的错误信息
    tool_calls: list[dict] = field(default_factory=list)  # TOOL_CALLS 时的调用列表
    confirmation: ConfirmationRequest | None = None        # NEED_CONFIRM 时


# ── Agent ───────────────────────────────────────────────


@dataclass
class Agent:
    """数据库对话智能体。"""

    mcp: MCPClient = field(default_factory=MCPClient)
    llm: LLMClient = field(default_factory=LLMClient)
    _tools_openai: list[dict] = field(default_factory=list)
    _round: int = field(default=0, init=False)

    async def start(self) -> None:
        """初始化：连接 MCP，发现工具。"""
        await self.mcp.initialize()
        tools = await self.mcp.list_tools()
        self._tools_openai = self.llm.tools_to_openai(tools)
        logger.info("Agent 就绪，注册 %d 个工具", len(tools))

    # ── 开始新一轮对话 ──────────────────────────────

    async def begin_turn(
        self, user_message: str, history: list[dict]
    ) -> StepResult:
        """开启新一轮对话：添加用户消息，调用 LLM。

        Returns:
            StepResult，可能是 DONE / TOOL_CALLS / NEED_CONFIRM
        """
        self._round = 0
        # 过滤掉历史中的 system 消息（Qwen 要求 system 必须在最前面且只能有一条）
        clean_history = [m for m in history if m.get("role") != "system"]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *clean_history]
        messages.append({"role": "user", "content": user_message})
        return await self._llm_step(messages)

    # ── 继续执行（确认后 / 工具结果后）──────────────

    async def continue_after_tools(
        self, messages: list[dict], tool_results: list[dict]
    ) -> StepResult:
        """将工具执行结果反馈给 LLM，继续循环。

        Args:
            messages: 之前的状态（含 assistant 的 tool_calls 消息）
            tool_results: [{"tool_call_id":..., "result":...}, ...]
        """
        for tr in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "content": str(tr["result"]),
            })
        self._round += 1
        return await self._llm_step(messages)

    # ── 内部 ────────────────────────────────────────

    async def _llm_step(self, messages: list[dict]) -> StepResult:
        """调用 LLM 并解析结果。"""
        if self._round >= MAX_TOOL_ROUNDS:
            return StepResult(
                kind=StepKind.DONE,
                messages=messages,
                content="⚠️ 处理轮次已达上限。如遇到数据库报错，请确认表结构和字段后重试；或者简化您的问题。",
            )

        response = await self.llm.chat(messages, self._tools_openai)

        # 纯文本 → 完成
        if not response.get("tool_calls"):
            messages.append(response)
            content = response.get("content", "")
            # Qwen 可能把 token 全用于 reasoning，content 为空时给提示
            if not content and response.get("reasoning_content"):
                content = "（模型思考过程过长，请简化问题后重试）"
            return StepResult(
                kind=StepKind.DONE,
                messages=messages,
                content=content,
            )

        # 有 tool_calls → 检查安全性
        messages.append(response)
        dangerous: list[dict] = []
        safe: list[dict] = []

        for tc in response["tool_calls"]:
            tool_name = tc["function"]["name"]
            tool_args = json.loads(tc["function"]["arguments"])

            # 提取 SQL 做安全检查
            sql = tool_args.get("sql", "")
            if sql and tool_name == "execute_sql" and needs_confirmation(sql):
                dangerous.append(tc)
            else:
                safe.append(tc)

        # 有危险操作 → 暂停等待确认
        if dangerous:
            tc = dangerous[0]
            raw_args = json.loads(tc["function"]["arguments"])
            return StepResult(
                kind=StepKind.NEED_CONFIRM,
                messages=messages,
                tool_calls=[tc],
                confirmation=ConfirmationRequest(
                    sql=raw_args.get("sql", ""),
                    operation_type=classify_sql(raw_args.get("sql", "")),
                    tool_name=tc["function"]["name"],
                    tool_args=raw_args,
                ),
            )

        # 全部安全 → 返回让 UI 执行
        return StepResult(
            kind=StepKind.TOOL_CALLS,
            messages=messages,
            tool_calls=safe,
        )
