"""dbhub-format —— DBHub 查询结果格式化器。

规则：
- 自动 LIMIT 50（未指定时）
- 类型感知格式化（日期/金额/NULL/布尔/JSON）
- Markdown 表格输出
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


# ── 类型感知格式化 ──────────────────────────────────────

# 日期/时间类型关键字
_DATE_TYPES = {"date", "timestamp", "timestamptz", "timestamp without time zone", "timestamp with time zone"}
# 金额类字段名关键字
_PRICE_KEYWORDS = {"price", "amount", "cost", "fee", "money", "baseprice", "discount"}
# 布尔类型关键字
_BOOL_TYPES = {"bool", "boolean"}


def _is_date_type(col_name: str, col_type: str | None) -> bool:
    """判断字段是否为日期/时间类型。"""
    if col_type and any(dt in (col_type or "").lower() for dt in _DATE_TYPES):
        return True
    return False


def _is_price_field(col_name: str) -> bool:
    """判断字段名是否暗示为金额。"""
    return any(kw in col_name.lower() for kw in _PRICE_KEYWORDS)


def _is_bool_type(col_type: str | None) -> bool:
    """判断字段是否为布尔类型。"""
    if col_type and any(bt in (col_type or "").lower() for bt in _BOOL_TYPES):
        return True
    return False


def _is_json_type(col_type: str | None) -> bool:
    """判断字段是否为 JSON 类型。"""
    if col_type and any(jt in (col_type or "").lower() for jt in ("json", "jsonb")):
        return True
    return False


def _format_value(value: Any, col_name: str = "", col_type: str | None = None) -> str:
    """根据字段名和类型智能格式化单个值。"""
    if value is None:
        return "-"

    # 日期/时间
    if _is_date_type(col_name, col_type):
        if isinstance(value, (datetime, date)):
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            return value.isoformat()
        # 尝试解析字符串日期
        if isinstance(value, str):
            # 已经是合理格式就直接返回
            if re.match(r"\d{4}-\d{2}-\d{2}", value):
                return value
        return str(value)

    # JSON 类型 → 美化
    if _is_json_type(col_type):
        return _format_json(value)

    # 金额
    if _is_price_field(col_name) and isinstance(value, (int, float, Decimal)):
        return f"¥{value:,.2f}"

    # 布尔
    if _is_bool_type(col_type):
        if value is True:
            return "✅"
        if value is False:
            return "❌"
        return str(value)

    # 长文本截断
    s = str(value)
    if len(s) > 100:
        return s[:100] + "..."

    return s


def _format_json(value: Any) -> str:
    """格式化 JSON 值，最多展开 2 层。"""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
        value = parsed

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _infer_column_types(columns: list[str], rows: list[dict]) -> dict[str, str | None]:
    """从数据中推断列的类型信息（DBHub 可能不返类型元数据）。"""
    types: dict[str, str | None] = {}
    for col in columns:
        # 从第一行非空值推断
        for row in rows:
            val = row.get(col)
            if val is not None:
                if isinstance(val, bool):
                    types[col] = "boolean"
                elif isinstance(val, int):
                    types[col] = "integer"
                elif isinstance(val, float):
                    types[col] = "float"
                elif isinstance(val, (datetime, date)):
                    types[col] = "timestamp"
                elif isinstance(val, str):
                    # 检测 JSON 字符串
                    if val.strip().startswith("{") or val.strip().startswith("["):
                        try:
                            json.loads(val)
                            types[col] = "jsonb"
                        except (json.JSONDecodeError, TypeError):
                            types[col] = "text"
                    else:
                        types[col] = "text"
                break
        if col not in types:
            types[col] = None
    return types


# ── Markdown 表格生成 ───────────────────────────────────


def _build_markdown_table(
    columns: list[str],
    rows: list[dict],
    col_types: dict[str, str | None],
) -> str:
    """构建格式化的 Markdown 表格。"""
    if not columns:
        return "*(空结果)*"

    # 表头
    header = "| " + " | ".join(f"**{c}**" for c in columns) + " |"
    separator = "|" + "|".join("------" for _ in columns) + "|"

    # 数据行
    data_lines = []
    for row in rows:
        cells = []
        for col in columns:
            val = row.get(col)
            cells.append(_format_value(val, col_name=col, col_type=col_types.get(col)))
        data_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *data_lines])


# ── SQL LIMIT 自动追加 ─────────────────────────────────


def _has_limit_clause(sql: str) -> bool:
    """检查 SQL 是否已包含 LIMIT 子句。"""
    # 简单检测 — 避免误匹配字符串中的 LIMIT
    # 移除字符串常量后检查
    cleaned = re.sub(r"'[^']*'", "", sql)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    return bool(re.search(r"\bLIMIT\s+\d+", cleaned, re.IGNORECASE))


def auto_append_limit(sql: str, default_limit: int = 50, max_limit: int = 500) -> tuple[str, str | None]:
    """为 SELECT 查询自动追加 LIMIT。

    Returns:
        (modified_sql, warning_message | None)
    """
    # 只处理 SELECT 语句
    if not re.match(r"\s*SELECT\b", sql.strip(), re.IGNORECASE):
        return sql, None

    # 已有的 LIMIT
    limit_match = re.search(r"\bLIMIT\s+(\d+)", sql, re.IGNORECASE)
    if limit_match:
        limit_val = int(limit_match.group(1))
        if limit_val > max_limit:
            return sql, f"⚠️ LIMIT {limit_val} 超过推荐上限 {max_limit}，可能影响性能。"
        return sql, None

    # 未指定 LIMIT → 自动追加
    return sql.rstrip(";").rstrip() + f" LIMIT {default_limit}", None


# ── 主入口 ──────────────────────────────────────────────


def format_sql_result(sql: str, raw_result: str, elapsed_ms: float = 0) -> str:
    """格式化 execute_sql 的返回结果为 Markdown。

    Args:
        sql: 原始 SQL 语句
        raw_result: DBHub 返回的原始 JSON 字符串
        elapsed_ms: 执行耗时（毫秒）

    Returns:
        格式化后的 Markdown 字符串
    """
    # 解析 DBHub 返回
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return raw_result  # 无法解析，原样返回

    # DBHub 格式: {"success": true, "data": {"rows": [...], "count": N}}
    if isinstance(data, dict) and data.get("success") and "data" in data:
        inner = data["data"]
        rows = inner.get("rows", [])
        count = inner.get("count", 0)
    elif isinstance(data, list):
        rows = data
        count = len(rows)
    else:
        return raw_result

    if not rows:
        return f"**查询：** `{sql}`\n\n*(无结果)*"

    columns = list(rows[0].keys()) if rows else []
    col_types = _infer_column_types(columns, rows)

    # 列数提示
    column_hint = ""
    if len(columns) > 8:
        column_hint = f"\n> ⚠️ 返回 {len(columns)} 列，是否需要仅展示关键列？"

    # 构建输出
    table = _build_markdown_table(columns, rows, col_types)
    elapsed_str = f" · {elapsed_ms:.0f}ms" if elapsed_ms else ""

    output_parts = [
        f"**查询：** `{sql}`",
        f"**返回：** {count} 行{elapsed_str}",
        "",
        table,
    ]
    if column_hint:
        output_parts.append(column_hint)

    return "\n".join(output_parts)


def format_search_result(raw_result: str) -> str:
    """格式化 search_objects 的返回结果为 Markdown。

    Args:
        raw_result: DBHub 返回的原始 JSON 字符串

    Returns:
        格式化后的 Markdown 字符串
    """
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return raw_result

    if isinstance(data, list):
        if not data:
            return "*(未找到对象)*"
        columns = list(data[0].keys())
        rows = data
    elif isinstance(data, dict):
        # 单个对象
        return json.dumps(data, ensure_ascii=False, indent=2)
    else:
        return raw_result

    return _build_markdown_table(columns, rows, {})
