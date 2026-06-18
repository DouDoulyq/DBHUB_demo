# DBHub Chat — 数据库对话智能体

基于 **DeepSeek / Qwen** 大模型 + **Streamlit** 前端 + **DBHub MCP** 的智能数据库对话系统。通过自然语言对话即可完成 PostgreSQL 数据库的查询、分析和操作。

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
| 🧩 Skills 系统 | 可插拔的能力模块（格式化、价格管理等） |
| 🏷️ 商城价格管理 | 联想商城 / EPP 商城物料价格增删改查 |
| 📊 智能格式化 | 日期/金额/NULL/布尔/JSON 类型感知，自动 LIMIT |
| 📋 交互历史记录 | 所有写操作自动记录到数据库，支持回溯 |
| 💬 多对话管理 | 侧边栏切换多个独立对话，互不干扰 |

## 架构

```
用户浏览器 → Streamlit (:8501) → DeepSeek / Qwen API (function calling)
                    ↓
            DBHub HTTP MCP (:8080) → PostgreSQL
```

## Skills（能力模块）

系统内置两个 Skill，按触发条件自动激活：

### 📊 dbhub-format
查询结果自动格式化，每次 `execute_sql` / `search_objects` 调用都会触发：
- 自动追加 `LIMIT 50`（未指定时）
- 类型感知格式化：日期 → `YYYY-MM-DD`、金额 → `¥1,234.00`、NULL → `-`、布尔 → `✅/❌`
- Markdown 表格输出，>8 列时提示精简

### 🏷️ mall-price-crud
商城价格管理，当操作涉及 `goodsindex` schema 时自动激活：
- 支持联想商城 (mall_type=1) 和 EPP 商城 (mall_type=2)
- 价格类型：基础价 / 会员组等级价
- 新增物料 → 改价 → 修改名称，完整 CRUD 流程
- 所有写操作预览后二次确认，SQL 末尾 `RETURNING *` 即时验证

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+（运行 DBHub MCP Server）
- LLM API Key（[获取 DeepSeek](https://platform.deepseek.com) 或使用内部 Qwen 等兼容 OpenAI 接口的 Key）

### 1. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY
```

### 2. 安装依赖

```bash
python3.11 -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows
pip install -r requirements.txt
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
    ├── mcp_client.py       # MCP HTTP 客户端（JSON-RPC 2.0）
    ├── llm.py              # LLM API 封装（DeepSeek / Qwen 兼容）
    ├── agent.py            # 智能体核心（tool-use 循环 + 确认拦截）
    ├── safety.py           # SQL 安全拦截（DELETE/UPDATE/DROP/TRUNCATE/ALTER）
    ├── formatter.py        # dbhub-format：类型感知 + Markdown 表格格式化
    ├── export.py           # 数据导出（CSV / Excel）
    └── ui.py               # Streamlit UI 组件（消息/确认卡/Schema/对话列表）
```

## 使用示例

**通用查询：**
- 「goods_info 表有哪些字段？」
- 「查询 goods_info 表中价格大于 100 的商品」
- 「帮我统计每个分类的商品数量」

**商城价格管理（自动激活 mall-price-crud）：**
- 「新增物料：编码 SN12345，联想商城，名称"测试商品"，基础价 99.9」
- 「把 SN12345 的联想商城基础价改为 150」
- 「查看 SN12345 在 EPP 商城的会员组等级价」

**数据修改：**
- 「插入一条新商品记录：名称=测试商品，价格=99.9」
- 「把 id=3 的商品价格改为 150」

## 环境变量

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `LLM_API_KEY` | ✅ | LLM API Key（DeepSeek / Qwen 等） | — |
| `LLM_BASE_URL` | — | API 地址（OpenAI 兼容端点） | `https://api.deepseek.com` |
| `LLM_MODEL` | — | 模型名（deepseek-chat / Qwen3.5_27B 等） | `deepseek-chat` |
| `DBHUB_MCP_URL` | — | DBHub MCP 地址 | `http://localhost:8080` |
| `APP_PORT` | — | Streamlit 端口 | `8501` |
| `APP_TITLE` | — | 页面标题 | `演示demo` |
| `DBHUB_PORT` | — | DBHub MCP Server 端口（start.sh 使用） | `8080` |
