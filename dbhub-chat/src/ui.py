"""Streamlit UI 组件 —— 可复用的消息渲染、SQL 展示、Schema 树等。"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from src.export import parse_to_df, to_csv_bytes, to_excel_bytes
from src.safety import classify_sql


# ── 消息渲染 ────────────────────────────────────────────


def render_user_message(content: str) -> None:
    """渲染用户消息气泡。"""
    with st.chat_message("user"):
        st.markdown(content)


def render_assistant_message(content: str, raw_result: str | None = None) -> None:
    """渲染助手消息气泡，可选附带导出按钮。"""
    with st.chat_message("assistant"):
        st.markdown(content)
        if raw_result:
            _render_export_buttons(raw_result)


def render_tool_message(
    tool_name: str,
    tool_args: dict,
    result: str | None = None,
    pending: bool = False,
) -> None:
    """渲染工具调用消息（折叠卡片）。"""
    with st.chat_message("assistant"):
        sql = tool_args.get("sql", "")
        op_label = classify_sql(sql) if sql else "工具调用"

        if pending:
            status = "⏳ 等待确认..."
        elif result:
            status = "✅ 已执行"
        else:
            status = "🔧 执行中"

        with st.expander(f"{status} {op_label} — {tool_name}", expanded=pending):
            if sql:
                st.code(sql, language="sql")
            else:
                st.json(tool_args)
            if result:
                st.caption("执行结果：")
                try:
                    df = parse_to_df(result)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    # 保存到 session_state 供导出
                    st.session_state["_last_export_raw"] = result
                except Exception:
                    st.text(result)
            elif not pending:
                st.info("执行中...")


# ── 导出按钮 ────────────────────────────────────────────


def _render_export_buttons(raw_result: str) -> None:
    """在消息下方渲染 CSV / Excel 下载按钮。"""
    try:
        df = parse_to_df(raw_result)
    except Exception:
        return

    col1, col2, _ = st.columns([1, 1, 4])
    csv_data = to_csv_bytes(df)
    xlsx_data = to_excel_bytes(df)

    col1.download_button(
        label="📥 CSV",
        data=csv_data,
        file_name="query_result.csv",
        mime="text/csv",
        key=f"csv_{hash(raw_result)}",
    )
    col2.download_button(
        label="📥 Excel",
        data=xlsx_data,
        file_name="query_result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"xlsx_{hash(raw_result)}",
    )


# ── 确认卡片 ────────────────────────────────────────────


def render_confirmation_card(sql: str, op_type: str) -> bool:
    """渲染危险操作确认卡片，返回 True=确认, False=取消。

    返回 True 后会清空确认状态。
    """
    with st.container(border=True):
        st.warning(f"⚠️ 危险操作：{op_type}")
        st.markdown("**即将执行的 SQL：**")
        st.code(sql, language="sql")
        st.markdown("请确认是否执行此操作？")

        col1, col2 = st.columns(2)
        confirmed = col1.button("✅ 确认执行", type="primary", use_container_width=True)
        cancelled = col2.button("❌ 取消", use_container_width=True)

        if confirmed:
            st.session_state["_confirm_result"] = "approved"
            st.rerun()
        if cancelled:
            st.session_state["_confirm_result"] = "rejected"
            st.rerun()

    return False  # 本次渲染期间未确认


# ── Schema 浏览器（侧边栏） ─────────────────────────────


def render_schema_browser(tables: list[dict] | None = None) -> None:
    """在侧边栏渲染数据库 Schema 浏览器。

    Args:
        tables: 从 search_objects 获取的表列表
                [{"name":"table1","columns":[{"name":"col1","type":"varchar"},...]}, ...]
    """
    st.sidebar.subheader("📊 数据库 Schema")

    if not tables:
        st.sidebar.caption("点击「刷新 Schema」加载表结构")
        if st.sidebar.button("🔄 刷新 Schema"):
            st.session_state["_refresh_schema"] = True
            st.rerun()
        return

    for table in tables:
        table_name = table.get("name", table.get("table_name", "?"))
        columns = table.get("columns", [])
        with st.sidebar.expander(f"📋 {table_name} ({len(columns)} 列)"):
            if columns:
                # 小表格展示列信息
                col_df = pd.DataFrame(columns)
                st.dataframe(
                    col_df,
                    use_container_width=True,
                    hide_index=True,
                    height=min(35 * len(columns) + 38, 300),
                )
            else:
                st.caption("无列信息")

    if st.sidebar.button("🔄 刷新 Schema"):
        st.session_state["_refresh_schema"] = True
        st.rerun()


# ── 对话列表（侧边栏） ─────────────────────────────────


def render_conversation_list(
    conversations: list[dict],
    current_conv_id: str | None,
) -> str | None:
    """在侧边栏渲染对话历史列表 + 新建按钮。

    Args:
        conversations: [{"id","title","messages","created_at"}, ...]
        current_conv_id: 当前活跃对话 ID

    Returns:
        用户点击切换到的对话 ID；None 表示无切换。
    """
    st.sidebar.subheader("💬 对话列表")

    switched_to: str | None = None

    for i, conv in enumerate(conversations):
        cid = conv["id"]
        title = conv.get("title", "未命名")
        msg_count = len(conv.get("messages", []))

        # 活跃对话高亮
        is_active = cid == current_conv_id
        prefix = "🔹" if is_active else "  "

        # 行内：标题 + 消息数 + 点击切换
        col1, col2 = st.sidebar.columns([5, 1])
        label = f"{prefix} {title}"
        if col1.button(
            label,
            key=f"conv_{cid}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            switched_to = cid

        col2.caption(f"{msg_count//2}")

    return switched_to


# ── Skills 列表（侧边栏） ─────────────────────────────


def render_skill_list() -> None:
    """在侧边栏渲染已集成的 Skill 列表及其描述。"""
    st.sidebar.subheader("🧩 可用 Skills")

    skills = [
        {
            "name": "dbhub-format",
            "icon": "📊",
            "desc": "查询结果自动格式化：Markdown 表格 + 类型感知（日期/金额/NULL/布尔/JSON）+ LIMIT 50",
            "status": "active",
        },
        {
            "name": "mall-price-crud",
            "icon": "🏷️",
            "desc": "商城价格管理：新增物料 / 改价 / 会员组价，goodsindex schema 专用",
            "status": "active",
        },
    ]

    for s in skills:
        tag = "🟢" if s["status"] == "active" else "⚪"
        with st.sidebar.expander(f"{tag} {s['icon']} {s['name']}"):
            st.caption(s["desc"])


# ── 状态栏 ──────────────────────────────────────────────


def render_status_bar(mcp_connected: bool, tools_count: int, db_name: str = "goodslib") -> None:
    """侧边栏底部状态信息。"""
    st.sidebar.divider()
    st.sidebar.caption(
        f"{'🟢' if mcp_connected else '🔴'} DBHub: "
        f"{'已连接' if mcp_connected else '未连接'}"
    )
    st.sidebar.caption(f"🔧 工具数: {tools_count}")
    st.sidebar.caption(f"🗄️ 数据库: {db_name}")
