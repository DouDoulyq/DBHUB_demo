"""DBHub Chat — Streamlit 主入口。

基于 LLM + DBHub MCP 的数据库对话智能体。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 确保 src 可导入
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from src.agent import Agent, StepKind, StepResult, MAX_CONSECUTIVE_ERRORS
from src.config import APP_TITLE
from src.formatter import format_sql_result, format_search_result
from src.mcp_client import MCPClient
from src.safety import ConfirmationRequest


# ── Skill 检测 ────────────────────────────────────────────


def _detect_skills_used(tool_name: str, tool_args: dict, formatted: bool) -> list[str]:
    """根据工具调用内容检测使用了哪些 Skill。

    Args:
        tool_name: MCP 工具名 (execute_sql / search_objects)
        tool_args: 工具参数字典
        formatted: 是否成功执行了格式化（即 dbhub-format 是否生效）

    Returns:
        使用的 Skill 名称列表
    """
    skills: list[str] = []

    # dbhub-format: 每次格式化成功都算
    if formatted:
        skills.append("dbhub-format")

    # mall-price-crud: 涉及 goodsindex schema 的操作
    sql = tool_args.get("sql", "")
    pattern = tool_args.get("pattern", "")
    if "goodsindex" in sql.lower() or "goodsindex" in str(pattern).lower():
        skills.append("mall-price-crud")

    return skills


# ── 操作日志 ──────────────────────────────────────────────

# 匹配 INSERT/UPDATE/DELETE 的表名
_WRITE_TABLE_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([\w.]+)",
    re.IGNORECASE,
)


def _parse_write_sql(sql: str) -> tuple[str, str, str] | None:
    """解析写 SQL，返回 (操作类型, 表名, schema名)。

    Returns:
        (operation_type, table_name, schema_name) 或 None
    """
    m = _WRITE_TABLE_RE.search(sql)
    if not m:
        return None

    full_name = m.group(1)
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name

    # 清理表名（去掉引号）
    table = table.strip('"')
    schema = schema.strip('"')

    sql_upper = sql.strip().upper()
    if sql_upper.startswith("INSERT"):
        op = "INSERT"
    elif sql_upper.startswith("UPDATE"):
        op = "UPDATE"
    elif sql_upper.startswith("DELETE"):
        op = "DELETE"
    else:
        return None

    return op, table, schema


async def _log_operation(agent, tool_name: str, tool_args: dict, exec_result: str) -> None:
    """将写操作记录到 interaction_history 表。

    Args:
        agent: Agent 实例（用于调用 MCP）
        tool_name: 工具名（必为 execute_sql）
        tool_args: 工具参数字典（含 sql）
        exec_result: MCP 返回的原始结果文本
    """
    if tool_name != "execute_sql":
        return

    sql = tool_args.get("sql", "")
    parsed = _parse_write_sql(sql)
    if not parsed:
        return

    op_type, table_name, schema_name = parsed

    # 尝试从 exec_result 提取 affected_rows
    affected_rows = 0
    try:
        result_data = json.loads(exec_result)
        if isinstance(result_data, dict):
            affected_rows = result_data.get("count", result_data.get("affected_rows", 0))
    except (json.JSONDecodeError, TypeError):
        pass

    # 转义 SQL 中的单引号
    sql_escaped = sql.replace("'", "''")
    table_escaped = table_name.replace("'", "''")
    schema_escaped = schema_name.replace("'", "''")

    log_sql = (
        f"INSERT INTO interaction_history "
        f"(table_name, schema_name, operation_type, sql_executed, affected_rows) "
        f"VALUES ('{table_escaped}', '{schema_escaped}', '{op_type}', "
        f"'{sql_escaped[:2000]}', {affected_rows})"
    )

    try:
        await agent.mcp.call_tool("execute_sql", {"sql": log_sql})
        logger.info("已记录操作历史: %s %s.%s", op_type, schema_name, table_name)
    except Exception as e:
        logger.warning("记录操作历史失败: %s", e)
# ── 思考过程渲染 ──────────────────────────────────────────


def _render_thinking_process(steps: list[dict]) -> None:
    """在对话面板中渲染可折叠的完整思考过程。

    Args:
        steps: [{
            "icon": "🤔", "label": "分析问题", "detail": "...",
            "sql": "SELECT ...",       # 可选：执行的 SQL
            "tool": "execute_sql",     # 可选：工具名
            "skills": ["dbhub-format"],# 可选：使用的 skill
            "result_summary": "...",   # 可选：结果摘要
        }, ...]
    """
    if not steps:
        return
    with st.expander("🧠 查看完整思考过程", expanded=False):
        for i, step in enumerate(steps):
            icon = step.get("icon", "•")
            label = step.get("label", "")
            detail = step.get("detail", "")
            sql = step.get("sql", "")
            tool = step.get("tool", "")
            skills = step.get("skills", [])
            result_summary = step.get("result_summary", "")

            # 步骤标题
            skill_tags = ""
            if skills:
                icons = {"dbhub-format": "📊", "mall-price-crud": "🏷️"}
                tags = [f"{icons.get(s, '🧩')} {s}" for s in skills]
                skill_tags = "  `" + "` `".join(tags) + "`"
            st.markdown(f"{icon} **{label}**{skill_tags}")

            if detail:
                st.caption(detail)
            if sql:
                st.code(sql, language="sql")
            elif tool:
                st.caption(f"工具: `{tool}`")
            if result_summary:
                st.caption(f"📋 {result_summary}")

            # 步骤间分隔（非最后一步）
            if i < len(steps) - 1:
                st.divider()


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
        "_show_history": False,       # 是否显示交互历史记录视图
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
    """跨平台安全的 async 执行器。

    使用 nest_asyncio 支持在 Streamlit 已有事件循环中嵌套运行 async。
    """
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass
    return asyncio.run(asyncio.wait_for(coro, timeout=_ASYNC_TIMEOUT))


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

    注意：此函数可能在线程池中运行，st.session_state 访问需谨慎。
    agent 已在主线程中初始化并缓存。
    """
    agent = get_agent()
    if agent is None:
        return

    all_msgs = st.session_state["messages"]
    messages = [m for m in all_msgs if m.get("role") != "__thinking__"]
    if not messages:
        _set_current_conv_title(user_msg[:20] + ("..." if len(user_msg) > 20 else ""))

    thinking_steps: list[dict] = []  # 收集思考过程
    _error_count = 0                 # 连续错误计数

    with st.status("🤔 思考中...", expanded=True) as status:
        # Step 1: LLM 首轮响应
        status.update(label="🤔 分析问题...")
        result = await agent.begin_turn(user_msg, messages)
        messages = result.messages

        # 记录首轮 LLM 决策
        tc_names = [tc["function"]["name"] for tc in result.tool_calls] if result.tool_calls else []
        if tc_names:
            tc_details = []
            for tc in result.tool_calls:
                args = json.loads(tc["function"]["arguments"])
                sql = args.get("sql", "")
                if sql:
                    tc_details.append(f"`{tc['function']['name']}` → {sql.strip()[:120]}…")
                else:
                    tc_details.append(f"`{tc['function']['name']}` → {json.dumps(args, ensure_ascii=False)[:120]}")
            detail = "\n".join(tc_details)
        else:
            detail = "无需调用工具，直接回答"
        thinking_steps.append({
            "icon": "🤔",
            "label": "分析问题",
            "detail": detail,
        })

        # 循环处理 tool calls（非危险的）
        round_num = 0
        while result.kind == StepKind.TOOL_CALLS:
            round_num += 1
            status.update(label=f"🔧 执行工具调用 ({len(result.tool_calls)} 个)...")
            tool_results = []
            for tc in result.tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"]["arguments"])
                exec_result = await agent.mcp.call_tool(tool_name, tool_args)

                # 检测 SQL 执行错误
                _is_error = False
                if tool_name == "execute_sql":
                    result_lower = str(exec_result).lower()
                    _is_error = any(kw in result_lower for kw in [
                        "error", "violation", "constraint", "cannot",
                        "does not exist", "syntax error", "permission denied",
                    ])
                if _is_error:
                    _error_count += 1
                else:
                    _error_count = 0

                # 记录写操作到历史表
                await _log_operation(agent, tool_name, tool_args, exec_result)

                # dbhub-format: 格式化查询结果
                display_result = exec_result  # 默认原样
                formatted = False
                if tool_name == "execute_sql" and exec_result:
                    sql = tool_args.get("sql", "")
                    try:
                        display_result = format_sql_result(sql, exec_result)
                        formatted = True
                    except Exception:
                        pass  # 格式化失败则保留原样
                elif tool_name == "search_objects" and exec_result:
                    try:
                        display_result = format_search_result(exec_result)
                        formatted = True
                    except Exception:
                        pass

                # 检测使用的 skills
                skills_used = _detect_skills_used(tool_name, tool_args, formatted)

                tool_results.append({
                    "tool_call_id": tc["id"],
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": display_result,       # 格式化后 → 给 LLM
                    "result_raw": exec_result,      # 原始 JSON → 给渲染和导出
                    "skills_used": skills_used,     # 使用的 skill 列表
                })

            # 记录本轮每个工具调用的详细步骤
            for tr in tool_results:
                t_name = tr["tool_name"]
                t_args = tr["tool_args"]
                t_skills = tr.get("skills_used", [])
                t_result_raw = tr.get("result_raw", "")
                sql = t_args.get("sql", "")

                # 构建工具调用描述
                if t_name == "execute_sql" and sql:
                    # 截取 SQL 前 200 字符作为描述
                    sql_short = sql.strip()[:200] + "…" if len(sql.strip()) > 200 else sql.strip()
                    detail = sql_short
                elif t_name == "search_objects":
                    obj_type = t_args.get("object_type", "")
                    pattern = t_args.get("pattern", "%")
                    table = t_args.get("table", "")
                    parts = [f"搜索 {obj_type}"]
                    if table:
                        parts.append(f"表 {table}")
                    parts.append(f"模式 {pattern}")
                    detail = "，".join(parts)
                else:
                    detail = json.dumps(t_args, ensure_ascii=False)[:200]

                # 结果摘要
                result_summary = ""
                if t_result_raw:
                    try:
                        data = json.loads(t_result_raw)
                        if isinstance(data, list):
                            result_summary = f"返回 {len(data)} 条记录"
                        elif isinstance(data, dict):
                            result_summary = f"返回 {len(data)} 个字段"
                        else:
                            text = str(t_result_raw)
                            result_summary = f"返回 {len(text)} 字符"
                    except (json.JSONDecodeError, TypeError):
                        text = str(t_result_raw)
                        lines = text.strip().split("\n")
                        result_summary = f"返回 {len(lines)} 行文本"

                thinking_steps.append({
                    "icon": "🔧",
                    "label": f"第 {round_num} 轮 · {t_name}",
                    "detail": detail,
                    "sql": sql if t_name == "execute_sql" else "",
                    "tool": t_name,
                    "skills": t_skills,
                    "result_summary": result_summary,
                })

            # 渲染已执行的工具调用（用原始 JSON 保证 DataFrame 解析正常）
            for tr in tool_results:
                render_tool_message(tr["tool_name"], tr["tool_args"],
                                    tr.get("result_raw", tr["result"]),
                                    skills_used=tr.get("skills_used"))
                # 保存原始结果供导出
                if tr.get("result_raw") and tr["tool_name"] == "execute_sql":
                    st.session_state["_last_export_raw"] = tr["result_raw"]

            # 连续错误次数过多 → 强制停止，避免死循环
            if _error_count >= MAX_CONSECUTIVE_ERRORS:
                status.update(label="⚠️ 连续错误过多", state="error")
                # 构造 DONE 结果以跳出循环
                class _FakeResult:
                    kind = StepKind.DONE
                    messages_val = messages
                    content = (
                        f"⚠️ 连续 {_error_count} 次 SQL 执行报错，已自动停止。\n\n"
                        f"最后一次错误信息：{str(exec_result)[:500]}\n\n"
                        f"请检查表结构和 SQL 语法后重新尝试。"
                    )
                    tool_calls = []

                result = _FakeResult()
                render_tool_message(tool_name, tool_args, exec_result)
                break

            # 继续 LLM（给 LLM 格式化后的 Markdown）
            status.update(label="🤔 分析结果...")
            result = await agent.continue_after_tools(
                messages,
                [{"tool_call_id": tr["tool_call_id"], "result": tr["result"]} for tr in tool_results],
            )
            messages = result.messages

            # 记录本轮 LLM 继续决策
            tc_names = [tc["function"]["name"] for tc in result.tool_calls] if result.tool_calls else []
            if tc_names:
                tc_details = []
                for tc in result.tool_calls:
                    args = json.loads(tc["function"]["arguments"])
                    sql = args.get("sql", "")
                    if sql:
                        tc_details.append(f"`{tc['function']['name']}` → {sql.strip()[:120]}…")
                    else:
                        tc_details.append(f"`{tc['function']['name']}` → {json.dumps(args, ensure_ascii=False)[:120]}")
                detail = "\n".join(tc_details)
                thinking_steps.append({
                    "icon": "🤔",
                    "label": "分析结果",
                    "detail": detail,
                })

        # 处理结果
        if result.kind == StepKind.DONE:
            status.update(label="✅ 完成", state="complete")
            thinking_steps.append({
                "icon": "✅",
                "label": "生成回复",
                "detail": "LLM 生成最终回答",
            })
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
            # 保存当前已收集的思考步骤（确认后继续追加）
            st.session_state["_pending_thinking"] = thinking_steps
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

    # ── 状态块结束后：将思考过程插入消息列表（紧跟在用户消息之后）──
    if thinking_steps:
        # 找到最后一条 user 消息的位置，在其后插入 __thinking__ 消息
        insert_idx = len(st.session_state["messages"]) - 1
        for i in range(len(st.session_state["messages"]) - 1, -1, -1):
            if st.session_state["messages"][i].get("role") == "user":
                insert_idx = i + 1
                break
        st.session_state["messages"].insert(insert_idx, {
            "role": "__thinking__",
            "steps": thinking_steps,
        })


async def handle_confirmation(approved: bool) -> None:
    """处理用户确认结果。"""
    agent = get_agent()
    if agent is None:
        return

    pending = st.session_state["pending_confirm"]
    messages = st.session_state["pending_messages"]
    thinking_steps = st.session_state.pop("_pending_thinking", [])

    if approved and pending:
        # 执行危险操作
        with st.status("🔧 执行中...", expanded=True) as status:
            result_text = await agent.mcp.call_tool(pending.tool_name, pending.tool_args)

            # 记录写操作到历史表
            await _log_operation(agent, pending.tool_name, pending.tool_args, result_text)

            # 记录确认执行的步骤
            sql_short = pending.tool_args.get("sql", "")[:200]
            skills = _detect_skills_used(pending.tool_name, pending.tool_args,
                                         formatted=bool(pending.tool_name == "execute_sql"))
            thinking_steps.append({
                "icon": "🔧",
                "label": f"执行确认操作 · {pending.tool_name}",
                "detail": sql_short,
                "sql": pending.tool_args.get("sql", ""),
                "tool": pending.tool_name,
                "skills": skills,
                "result_summary": "已执行",
            })

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
                thinking_steps.append({
                    "icon": "✅",
                    "label": "生成回复",
                    "detail": "LLM 生成最终回答",
                })
                render_assistant_message(result.content)
            else:
                render_assistant_message("操作已完成。")

            st.session_state["messages"] = messages
            _sync_messages_to_conv()

            # 将思考过程插入消息列表
            if thinking_steps:
                insert_idx = len(st.session_state["messages"]) - 1
                for i in range(len(st.session_state["messages"]) - 1, -1, -1):
                    if st.session_state["messages"][i].get("role") == "user":
                        insert_idx = i + 1
                        break
                st.session_state["messages"].insert(insert_idx, {
                    "role": "__thinking__",
                    "steps": thinking_steps,
                })
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
        elif role == "__thinking__":
            _render_thinking_process(msg.get("steps", []))
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

    # ── 交互历史记录 ──
    if st.sidebar.button("📋 交互历史记录", use_container_width=True):
        st.session_state["_show_history"] = True
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


# ── 交互历史记录视图 ─────────────────────────────────────


async def _fetch_history(agent) -> list[dict]:
    """从 interaction_history 表查询最近 200 条记录。"""
    try:
        raw = await agent.mcp.call_tool("execute_sql", {
            "sql": "SELECT id, created_at, username, schema_name, table_name, "
                   "operation_type, sql_executed, affected_rows "
                   "FROM interaction_history "
                   "ORDER BY created_at DESC LIMIT 200"
        })
        # 解析 MCP 返回的 JSON
        data = json.loads(raw)
        if isinstance(data, dict):
            rows = data.get("rows", data.get("data", {}).get("rows", []))
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        return rows
    except Exception:
        return []


def _render_history_view() -> None:
    """渲染交互历史记录全屏视图。"""
    st.title("📋 交互历史记录")
    st.caption("记录所有 INSERT / UPDATE / DELETE 操作明细（最近 200 条）")

    # 返回按钮
    if st.button("⬅ 返回对话", key="back_to_chat"):
        st.session_state["_show_history"] = False
        st.rerun()

    st.divider()

    # 初始化 Agent 以查询数据库
    agent = get_agent()
    if agent is None:
        st.warning("⏳ 正在连接数据库...")
        return

    # 加载数据
    with st.spinner("加载历史记录..."):
        rows = _run_async(_fetch_history(agent))

    if not rows:
        st.info("暂无操作记录。执行 INSERT / UPDATE / DELETE 后会自动记录于此。")
        # 刷新按钮
        if st.button("🔄 刷新"):
            st.rerun()
        return

    # 构建表格
    import pandas as pd
    df = pd.DataFrame(rows)

    # 重命名列
    col_map = {
        "created_at": "操作时间",
        "username": "用户",
        "schema_name": "Schema",
        "table_name": "表名",
        "operation_type": "操作类型",
        "sql_executed": "SQL",
        "affected_rows": "影响行数",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 操作类型上色
    def _op_color(op: str) -> str:
        colors = {
            "INSERT": "background-color: #d4edda;",  # 绿
            "UPDATE": "background-color: #fff3cd;",  # 黄
            "DELETE": "background-color: #f8d7da;",  # 红
        }
        return colors.get(op, "")

    # 使用 st.dataframe 展示
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "操作时间": st.column_config.DatetimeColumn("操作时间", format="YYYY-MM-DD HH:mm:ss"),
            "SQL": st.column_config.TextColumn("SQL", width="large"),
        },
    )

    # 统计
    if "操作类型" in df.columns:
        col1, col2, col3 = st.columns(3)
        counts = df["操作类型"].value_counts()
        col1.metric("INSERT", counts.get("INSERT", 0))
        col2.metric("UPDATE", counts.get("UPDATE", 0))
        col3.metric("DELETE", counts.get("DELETE", 0))

    # 刷新按钮
    if st.button("🔄 刷新记录"):
        st.rerun()


# ── Main ────────────────────────────────────────────────


def main() -> None:
    """Streamlit 主循环。"""

    # ── 交互历史记录视图 ──
    if st.session_state.get("_show_history"):
        _render_history_view()
        return

    # ── 修复鼠标滚轮向上滚动卡顿的 bug ──
    # Streamlit 在 st.rerun() 后会自动滚到底部，与用户手动向上滚动冲突。
    # 注入 JS 跟踪用户滚动位置：如果用户已向上滚动，阻止自动滚到底部。
    st.markdown("""
        <script>
        (function() {
            var _userScrolledUp = false;
            var _lastY = 0;
            window.addEventListener('scroll', function() {
                _lastY = window.scrollY;
                var atBottom = (window.innerHeight + window.scrollY) >= document.body.scrollHeight - 120;
                _userScrolledUp = !atBottom;
            }, {passive: true});
            var _orig = window.scrollTo;
            window.scrollTo = function(x, y) {
                if (_userScrolledUp && (typeof y === 'number') && y > _lastY + 50) {
                    return;
                }
                _orig.call(window, x, y);
            };
        })();
        </script>
    """, unsafe_allow_html=True)

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
            logger.exception("请求超时")
            st.error(f"⏱️ 请求超时（{_ASYNC_TIMEOUT} 秒）。数据库或 API 可能响应较慢，请简化问题后重试。")
        except Exception as e:
            logger.exception("handle_user_input 异常")
            st.error(f"❌ 处理失败: {e}")
        st.rerun()


if __name__ == "__main__":
    main()
