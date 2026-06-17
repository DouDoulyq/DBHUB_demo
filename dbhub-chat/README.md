# DBHub Chat — 数据库对话智能体

基于 **DeepSeek** 大模型 + **Streamlit** 前端 + **DBHub MCP** 的智能数据库对话系统。通过自然语言对话即可完成 PostgreSQL 数据库的查询、分析和操作。

## 功能

| 功能 | 说明 |
|------|------|
| 🤖 自然语言对话 | 用中文描述需求，智能体自动生成 SQL 并执行 |
| 📊 Schema 浏览 | 侧边栏实时展示数据库表结构 |
| 🔍 智能查询 | 自动探索表结构再生成查询，减少错误 |
| ⚠️ 安全确认 | DELETE/UPDATE/DROP 等危险操作弹出二次确认 |
| 📝 SQL 展示 | 每条操作都会折叠展示生成的 SQL |
| 📥 数据导出 | 查询结果一键导出 CSV / Excel |
| 💬 多轮对话 | 上下文记忆，支持连续追问 |

## 架构

```
用户浏览器 → Streamlit (:8501) → DeepSeek API (function calling)
                    ↓
            DBHub HTTP MCP (:8080) → PostgreSQL
```

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+（运行 DBHub MCP Server）
- DeepSeek API Key（[获取](https://platform.deepseek.com)）

### 1. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 2. 安装依赖

```bash
python3.11 -m venv venv
source venv/bin/activate

```

### 3. 启动

**方式 A：一键启动**
```bash
chmod +x start.sh
./start.sh
```

**方式 B：手动分步启动**

终端 1 — 启动 DBHub MCP Server：
```bash
npx -y @bytebase/dbhub@latest \
  --transport http \
  --port 8080 \
  --dsn "postgresql://dev_goods:lenovo2019@10.196.176.91:5432/goodslib?sslmode=disable"
```

终端 2 — 启动 Streamlit：
```bash
source venv/bin/activate
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### 4. 访问

打开浏览器访问 `http://localhost:8501`

## 项目结构

```
dbhub-chat/
├── app.py                  # Streamlit 主入口
├── start.sh                # 一键启动脚本
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板
└── src/
    ├── config.py           # 配置管理
    ├── mcp_client.py       # MCP HTTP 客户端
    ├── llm.py              # DeepSeek API 封装
    ├── agent.py            # 智能体核心（tool-use 循环）
    ├── safety.py           # SQL 安全拦截
    ├── export.py           # 数据导出（CSV/Excel）
    └── ui.py               # Streamlit UI 组件
```

## 使用示例

- 「goods_info 表有哪些字段？」
- 「查询 goods_info 表中价格大于 100 的商品」
- 「帮我统计每个分类的商品数量」
- 「插入一条新商品记录：名称=测试商品，价格=99.9」
- 「把 id=3 的商品价格改为 150」

## 环境变量

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API Key | — |
| `DEEPSEEK_BASE_URL` | — | API 地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | — | 模型名 | `deepseek-chat` |
| `DBHUB_MCP_URL` | — | DBHub 地址 | `http://localhost:8080/dbhub` |
| `APP_PORT` | — | Streamlit 端口 | `8501` |
