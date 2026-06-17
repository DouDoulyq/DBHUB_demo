"""数据导出模块 —— 将 SQL 查询结果导出为 CSV / Excel。

DBHub execute_sql 返回的结果可能是:
- JSON 数组: [{"col1":"val1",...}, ...]
- Markdown 表格
- 纯文本

解析策略: 优先 JSON，其次 Markdown 表格，最后 raw。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

# ── 解析 ────────────────────────────────────────────────


def parse_to_df(raw: str) -> pd.DataFrame:
    """尝试将 DBHub 返回的原始字符串解析为 DataFrame。"""
    raw = raw.strip()

    # 1) JSON 数组
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list) and len(data) > 0:
                return pd.DataFrame(data)
        except (json.JSONDecodeError, ValueError):
            pass

    # 2) Markdown 表格
    lines = raw.split("\n")
    md_lines = [l for l in lines if l.strip().startswith("|")]
    if len(md_lines) >= 2:
        try:
            return _parse_markdown_table(md_lines)
        except Exception:
            pass

    # 3) 兜底：返回单列
    logger.warning("无法结构化解析结果，返回原始文本列")
    return pd.DataFrame({"result": [raw]})


def _parse_markdown_table(lines: list[str]) -> pd.DataFrame:
    """解析 Markdown 表格行列表。"""
    # 第一行是 header，第二行是分隔符
    header = [c.strip() for c in lines[0].split("|")[1:-1]]
    # 跳过分隔符行
    data_rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(header):
            data_rows.append(cells)
    return pd.DataFrame(data_rows, columns=header)


# ── 导出 ────────────────────────────────────────────────


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame → CSV bytes (UTF-8 BOM for Excel 兼容)。"""
    buf = io.BytesIO()
    # BOM for Excel on Windows
    buf.write(b"\xef\xbb\xbf")
    text = df.to_csv(index=False, quoting=csv.QUOTE_ALL)
    buf.write(text.encode("utf-8"))
    buf.seek(0)
    return buf.read()


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "查询结果") -> bytes:
    """DataFrame → Excel bytes。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    buf.seek(0)
    return buf.read()


def export(raw_result: str, filename_base: str = "query_result") -> dict[str, tuple[str, bytes]]:
    """一站式导出：输入原始结果，返回 {'csv': (filename, bytes), 'xlsx': (filename, bytes)}。"""
    df = parse_to_df(raw_result)
    return {
        "csv": (f"{filename_base}.csv", to_csv_bytes(df)),
        "xlsx": (f"{filename_base}.xlsx", to_excel_bytes(df)),
    }
