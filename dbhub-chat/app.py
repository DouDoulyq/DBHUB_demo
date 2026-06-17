"""DBHub Chat — Streamlit 主入口。

基于 DeepSeek + DBHub MCP 的数据库对话智能体。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 确保 src 可导入
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from src.agent import Agent, StepKind, StepResult
from src.config import APP_TITLE
from src.formatter import format_sql_result, format_search_result
from src.mcp_client import MCPClient
from src.safety import ConfirmationRequest
from src.ui import (
    render_assistant_message,
    render_confirmation_card,
    render_conversation_list,
    render_schema_browser,
    render_skill_list,
    render_status_bar,
    render_tool_message,
    render_user_message,
)

# ── 日志 ────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("app")

# ── 页面配置 ────────────────────────────────────────────

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title(APP_TITLE)
st.caption("通过自然语言对话完成数据库查询、分析和操作。")

# ── 初始化 session state ────────────────────────────────


def _make_conv_id() -> str:
    """生成对话 ID。"""
    return uuid.uuid4().hex[:12]


def _default_conversation() -> dict:
    """创建一个空对话。"""
    return {"id": _make_conv_id(), "title": "新对话", "messages": [], "created_at": datetime.now().isoformat()}


def _sync_messages_to_conv() -> None:
    """将当前 messages 写回当前对话。"""
    cid = st.session_state.get("current_conv_id")
    if cid is None:
        return
    for c in st.session_state["conversations"]:
        if c["id"] == cid:
            c["messages"] = st.session_state["messages"]
            return


def _load_conv_messages(cid: str) -> None:
    """从指定对话加载 messages 到 session_state。"""
    for c in st.session_state["conversations"]:
        if c["id"] == cid:
            st.session_state["messages"] = c["messages"]
            return
    st.session_state["messages"] = []


def _set_current_conv_title(title: str) -> None:
    """设置当前对话的标题。"""
    cid = st.session_state.get("current_conv_id")
    if cid is None:
        return
    for c in st.session_state["conversations"]:
        if c["id"] == cid:
            c["title"] = title
            return


def init_session() -> None:
    """初始化 session_state 中的持久变量。"""
    defaults = {
        "agent": None,              # Agent 实例
        "messages": [],             # 当前对话的 OpenAI 格式消息历史
        "mcp_ready": False,         # MCP 是否已连接
        "tools_count": 0,           # 可用工具数
        "schema_tables": None,      # Schema 缓存
        # 多对话支持
        "conversations": [],        # [{"id","title","messages","created_at"}, ...]
        "current_conv_id": None,    # 当前活跃对话 ID
        # 确认流程状态
        "pending_confirm": None,      # ConfirmationRequest | None
        "pending_messages": None,     # 暂停时的 messages
        "_confirm_result": None,      # "approved" | "rejected" | None
        "_refresh_schema": False,     # 触发刷新
        "_last_export_raw": None,     # 最近一次查询结果原文本
        "_switch_to_conv": None,      # 待切换的对话 ID
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # 首次加载：创建默认对话
    if not st.session_state["conversations"]:
        conv = _default_conversation()
        st.session_state["conversations"] = [conv]
        st.session_state["current_conv_id"] = conv["id"]
        st.session_state["messages"] = conv["messages"]


init_session()


# ── 初始化 Agent（缓存） ─────────────────────────────────


async def _init_agent() -> Agent:
    """创建并初始化 Agent，自动发现 MCP 工具。"""
    agent = Agent()
    await agent.start()
    st.session_state["tools_count"] = len(agent.mcp.tools)
    st.session_state["mcp_ready"] = True
    logger.info("Agent 初始化完成")
    return agent


_ASYNC_TIMEOUT = 120  # 完整交互链（LLM + MCP 多轮）超时上限


def _run_async(coro):
    """跨平台安全的 async 执行器，兼容 Streamlit 的事件循环模型。

    超时后会抛出 TimeoutError，由调用方展示友好错误信息。
    """
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环 → 用 asyncio.run() 包裹，设超时防止无限卡死
        return asyncio.run(asyncio.wait_for(coro, timeout=_ASYNC_TIMEOUT))
    # 已有运行中的事件循环（如部分 Streamlit 版本）→ 在新线程中执行
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, asyncio.wait_for(coro, timeout=_ASYNC_TIMEOUT)
        ).result(timeout=_ASYNC_TIMEOUT + 5)


def get_agent() -> Agent | None:
    """获取或创建 Agent（同步封装），页面加载时自动初始化。"""
    if st.session_state["agent"] is not None:
        return st.session_state["agent"]

    # 还没初始化 → 尝试连接
    try:
        agent = _run_async(_init_agent())
        st.session_state["agent"] = agent
    except Exception as e:
        logger.error("Agent 初始化失败: %s", e)
        st.session_state["mcp_ready"] = False
        return None
    return st.session_state["agent"]


# ── 加载 Schema ─────────────────────────────────────────


async def _load_schema(agent: Agent, detail: str = "summary") -> list[dict]:
    """从 DBHub 拉取所有表的 Schema 信息。"""
    # 获取所有表名
    raw = await agent.mcp.search_objects("table", "%", "public", "names")
    # DBHub 返回可能是 JSON 或文本，尝试解析
    try:
        tables = json.loads(raw)
        if not isinstance(tables, list):
            return []
    except (json.JSONDecodeError, TypeError):
        logger.warning("Schema 解析失败: %s", raw[:200])
        return []

    # 为每个表获取详细信息
    result = []
    for t in tables:
        name = t.get("name", t.get("table_name", ""))
        if not name:
            continue
        try:
            col_raw = await agent.mcp.search_objects("column", "%", "public", "full", table=name)
            cols = _parse_column_info(col_raw)
        except Exception:
            cols = []
        result.append({"name": name, "columns": cols})
    return result


def _parse_column_info(raw: str) -> list[dict]:
    """解析列信息为列表。"""
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ── 主流程 ──────────────────────────────────────────────


async def handle_user_input(user_msg: str) -> None:
    """处理用户输入，执行完整的 agent 对话轮次。

    使用 st.status 显示进度，处理 DONE / TOOL_CALLS / NEED_CONFIRM 三种结果。
    """
    agent = get_agent()
    if agent is None:
        return

    # 首条用户消息 → 自动设置对话标题
    messages = st.session_state["messages"]
    if not messages:
        title = user_msg[:20] + ("..." if len(user_msg) > 20 else "")
        _set_current_conv_title(title)

    with st.status("🤔 思考中...", expanded=True) as status:
        # Step 1: LLM 首轮响应
        status.update(label="🤔 分析问题...")
        result = await agent.begin_turn(user_msg, messages)
        messages = result.messages

        # 循环处理 tool calls（非危险的）
        while result.kind == StepKind.TOOL_CALLS:
            status.update(label=f"🔧 执行工具调用 ({len(result.tool_calls)} 个)...")
            tool_results = []
            for tc in result.tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"]["arguments"])
                exec_result = await agent.mcp.call_tool(tool_name, tool_args)

                # dbhub-format: 格式化查询结果
                display_result = exec_result  # 默认原样
                if tool_name == "execute_sql" and exec_result:
                    sql = tool_args.get("sql", "")
                    try:
                        display_result = format_sql_result(sql, exec_result)
                    except Exception:
                        pass  # 格式化失败则保留原样
                elif tool_name == "search_objects" and exec_result:
                    try:
                        display_result = format_search_result(exec_result)
                    except Exception:
                        pass

                tool_results.append({
                    "tool_call_id": tc["id"],
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": display_result,       # 格式化后 → 给 LLM
                    "result_raw": exec_result,      # 原始 JSON → 给渲染和导出
                })

            # 渲染已执行的工具调用（用原始 JSON 保证 DataFrame 解析正常）
            for tr in tool_results:
                render_tool_message(tr["tool_name"], tr["tool_args"],
                                    tr.get("result_raw", tr["result"]))
                # 保存原始结果供导出
                if tr.get("result_raw") and tr["tool_name"] == "execute_sql":
                    st.session_state["_last_export_raw"] = tr["result_raw"]

            # 继续 LLM（给 LLM 格式化后的 Markdown）
            status.update(label="🤔 分析结果...")
            result = await agent.continue_after_tools(
                messages,
                [{"tool_call_id": tr["tool_call_id"], "result": tr["result"]} for tr in tool_results],
            )
            messages = result.messages

        # 处理结果
        if result.kind == StepKind.DONE:
            status.update(label="✅ 完成", state="complete")
            render_assistant_message(
                result.content,
                raw_result=st.session_state.get("_last_export_raw"),
            )
            st.session_state["messages"] = messages
            _sync_messages_to_conv()

        elif result.kind == StepKind.NEED_CONFIRM:
            status.update(label="⚠️ 需要确认", state="complete")
            # 保存暂停状态
            st.session_state["pending_confirm"] = result.confirmation
            st.session_state["pending_messages"] = messages
            _sync_messages_to_conv()
            # 渲染确认前的 SQL
            if result.tool_calls:
                tc = result.tool_calls[0]
                args = json.loads(tc["function"]["arguments"])
                render_tool_message(tc["function"]["name"], args, pending=True)
            st.rerun()

        elif result.kind == StepKind.ERROR:
            status.update(label="❌ 出错", state="error")
            st.error(result.content)


async def handle_confirmation(approved: bool) -> None:
    """处理用户确认结果。"""
    agent = get_agent()
    if agent is None:
        return

    pending = st.session_state["pending_confirm"]
    messages = st.session_state["pending_messages"]

    if approved and pending:
        # 执行危险操作
        with st.status("🔧 执行中...", expanded=True) as status:
            result_text = await agent.mcp.call_tool(pending.tool_name, pending.tool_args)
            status.update(label="✅ 执行完成", state="complete")

            # 格式化结果（给 LLM）
            llm_result = result_text
            if pending.tool_name == "execute_sql" and result_text:
                try:
                    llm_result = format_sql_result(pending.tool_args.get("sql", ""), result_text)
                except Exception:
                    pass

            # 渲染执行结果（用原始 JSON）
            render_tool_message(pending.tool_name, pending.tool_args, result_text)

            # 继续 LLM（给格式化后的结果）
            last_msg = messages[-1]
            tool_call_id = ""
            if last_msg.get("tool_calls"):
                tool_call_id = last_msg["tool_calls"][0]["id"]

            result = await agent.continue_after_tools(
                messages,
                [{"tool_call_id": tool_call_id, "result": llm_result}],
            )
            messages = result.messages

            if result.kind == StepKind.DONE:
                render_assistant_message(result.content)
            else:
                render_assistant_message("操作已完成。")

            st.session_state["messages"] = messages
            _sync_messages_to_conv()
    else:
        # 用户取消
        st.info("操作已取消。")
        # 添加取消消息到历史
        messages.append({"role": "user", "content": "（用户取消了该操作）"})
        st.session_state["messages"] = messages
        _sync_messages_to_conv()

    # 清除确认状态
    st.session_state["pending_confirm"] = None
    st.session_state["pending_messages"] = None


# ── 渲染 UI ─────────────────────────────────────────────


def render_chat_history() -> None:
    """渲染已有的对话历史。"""
    messages = st.session_state["messages"]
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            render_user_message(content)
        elif role == "assistant":
            if content:
                render_assistant_message(content)
            # tool_calls 不单独渲染（在执行时已渲染）
        # tool 角色的消息不直接渲染


# ── 侧边栏 ──────────────────────────────────────────────

def render_sidebar() -> None:
    """渲染侧边栏：对话列表 + Schema 浏览器 + 状态信息。"""
    # 页面首次加载时触发 Agent 初始化
    if st.session_state.get("agent") is None and st.session_state.get("mcp_ready") is False:
        with st.sidebar.status("🔌 正在连接 DBHub...", expanded=False):
            get_agent()

    agent = st.session_state.get("agent")
    mcp_ready = st.session_state.get("mcp_ready", False)
    tools_count = st.session_state.get("tools_count", 0)

    # ── 对话列表 ──
    conversations = st.session_state.get("conversations", [])
    current_conv_id = st.session_state.get("current_conv_id")

    switched_to = render_conversation_list(conversations, current_conv_id)
    if switched_to and switched_to != current_conv_id:
        # 先保存当前消息
        _sync_messages_to_conv()
        # 切换到目标对话
        st.session_state["_switch_to_conv"] = switched_to
        st.rerun()

    # 新建对话按钮
    if st.sidebar.button("➕ 新建对话", use_container_width=True):
        _sync_messages_to_conv()
        conv = _default_conversation()
        st.session_state["conversations"].insert(0, conv)
        st.session_state["current_conv_id"] = conv["id"]
        st.session_state["messages"] = conv["messages"]
        st.session_state["pending_confirm"] = None
        st.session_state["pending_messages"] = None
        st.rerun()

    st.sidebar.divider()

    # ── Skills ──
    render_skill_list()

    st.sidebar.divider()

    # ── Schema 浏览器 ──
    # Schema 刷新
    if st.session_state.get("_refresh_schema") and agent:
        with st.spinner("加载 Schema..."):
            try:
                tables = _run_async(_load_schema(agent))
                st.session_state["schema_tables"] = tables
            except Exception as e:
                st.sidebar.error(f"加载失败: {e}")
        st.session_state["_refresh_schema"] = False

    render_schema_browser(st.session_state.get("schema_tables"))
    render_status_bar(mcp_ready, tools_count)


# ── Main ────────────────────────────────────────────────


def main() -> None:
    """Streamlit 主循环。"""
    render_sidebar()

    # ── 处理对话切换 ──
    switch_to = st.session_state.pop("_switch_to_conv", None)
    if switch_to:
        _load_conv_messages(switch_to)
        st.session_state["current_conv_id"] = switch_to
        st.session_state["pending_confirm"] = None
        st.session_state["pending_messages"] = None
        st.rerun()

    # ── 处理确认结果 ──
    confirm_result = st.session_state.get("_confirm_result")
    if confirm_result:
        try:
            if confirm_result == "approved":
                logger.info("用户确认执行危险操作")
                _run_async(handle_confirmation(True))
            else:
                logger.info("用户取消危险操作")
                _run_async(handle_confirmation(False))
        except (TimeoutError, asyncio.TimeoutError):
            st.error("⏱️ 操作超时（%d 秒）。数据库可能响应较慢，请重试。" % _ASYNC_TIMEOUT)
        except Exception as e:
            st.error(f"❌ 操作失败: {e}")
        st.session_state["_confirm_result"] = None
        st.rerun()

    # ── 渲染确认卡片 ──
    pending = st.session_state.get("pending_confirm")
    if pending:
        render_confirmation_card(pending.sql, pending.operation_type)
        # 不渲染输入框，等待确认
        return

    # ── 渲染历史 ──
    render_chat_history()

    # ── 聊天输入 ──
    if prompt := st.chat_input("输入您的问题，例如「查询所有商品表」「goods_info 表有哪些字段」..."):
        render_user_message(prompt)
        try:
            _run_async(handle_user_input(prompt))
        except (TimeoutError, asyncio.TimeoutError):
            st.error(f"⏱️ 请求超时（{_ASYNC_TIMEOUT} 秒）。数据库或 API 可能响应较慢，请简化问题后重试。")
        except Exception as e:
            st.error(f"❌ 处理失败: {e}")
        st.rerun()


if __name__ == "__main__":
    main()
