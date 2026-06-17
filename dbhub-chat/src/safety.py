"""安全拦截模块 —— 检测危险 SQL 并生成确认信息。

规则:
- DANGEROUS: DELETE, UPDATE, DROP, TRUNCATE, ALTER, INSERT
- SAFE: SELECT, EXPLAIN, SHOW, DESCRIBE
- MALL-PRICE-CRUD: goodsindex schema 写操作额外确认
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── 危险操作正则 ────────────────────────────────────────

_DANGEROUS_RE = re.compile(
    r"\b(DELETE\s+FROM|UPDATE\s+\w|DROP\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)|"
    r"TRUNCATE|ALTER\s+(TABLE|DATABASE)|INSERT\s+INTO)\b",
    re.IGNORECASE,
)

# 更细粒度的分类
_DELETE_RE = re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)
_UPDATE_RE = re.compile(r"\bUPDATE\s+\w", re.IGNORECASE)
_DROP_RE = re.compile(r"\bDROP\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)\b", re.IGNORECASE)
_TRUNCATE_RE = re.compile(r"\bTRUNCATE\b", re.IGNORECASE)
_ALTER_RE = re.compile(r"\bALTER\s+(TABLE|DATABASE)\b", re.IGNORECASE)
_INSERT_RE = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)


# ── 检查器 ───────────────────────────────────────────────


def is_dangerous(sql: str) -> bool:
    """检查 SQL 是否包含危险操作（需要确认）。"""
    return bool(_DANGEROUS_RE.search(sql))


def classify_sql(sql: str) -> str:
    """对 SQL 进行分类，返回操作类型标签。"""
    checks = [
        (_DELETE_RE, "DELETE（删除数据）"),
        (_UPDATE_RE, "UPDATE（更新数据）"),
        (_DROP_RE, "DROP（删除对象）"),
        (_TRUNCATE_RE, "TRUNCATE（清空表）"),
        (_ALTER_RE, "ALTER（修改结构）"),
        (_INSERT_RE, "INSERT（插入数据）"),
    ]
    for pattern, label in checks:
        if pattern.search(sql):
            return label
    return "SELECT（查询）"


def needs_confirmation(sql: str) -> bool:
    """是否需要二次确认。INSERT 虽然归类为危险但不强制确认。"""
    checks = [
        _DELETE_RE,
        _UPDATE_RE,
        _DROP_RE,
        _TRUNCATE_RE,
        _ALTER_RE,
    ]
    return any(p.search(sql) for p in checks)


# ── 确认请求模型 ────────────────────────────────────────


@dataclass
class ConfirmationRequest:
    """需要用户确认的操作。"""

    sql: str
    operation_type: str  # classify_sql 的结果
    tool_name: str  # 哪个 MCP 工具
    tool_args: dict  # 工具参数
