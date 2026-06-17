#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# DBHub Chat — 一键启动脚本
# 1. 检查 .env 和依赖
# 2. 后台启动 DBHub HTTP MCP Server（端口 8080）
# 3. 启动 Streamlit 应用（端口 8501）
# ─────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 颜色 ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  DBHub Chat — 数据库对话智能体${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── 1. 检查 .env ─────────────────────────────────────
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ 未找到 .env 文件，从 .env.example 复制...${NC}"
    cp .env.example .env
    echo -e "${RED}请编辑 .env 填入 DEEPSEEK_API_KEY 后重新运行${NC}"
    exit 1
fi

# 读取配置
source .env 2>/dev/null || true
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
DBHUB_PORT="${DBHUB_PORT:-8080}"
APP_PORT="${APP_PORT:-8501}"

if [ -z "$DEEPSEEK_API_KEY" ] || [ "$DEEPSEEK_API_KEY" = "sk-your-api-key-here" ]; then
    echo -e "${RED}❌ 请在 .env 中设置有效的 DEEPSEEK_API_KEY${NC}"
    exit 1
fi

# ── 2. 检查依赖 ──────────────────────────────────────
echo -e "${YELLOW}📦 检查 Python 依赖...${NC}"
if [ ! -d "venv" ]; then
    echo "   创建虚拟环境..."
    python3.11 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
echo -e "${GREEN}   ✅ 依赖就绪${NC}"

# ── 3. 检查 Node.js ──────────────────────────────────
if ! command -v npx &>/dev/null; then
    echo -e "${RED}❌ 需要 Node.js (npx) 来运行 DBHub MCP Server${NC}"
    exit 1
fi

# ── 4. 启动 DBHub HTTP MCP Server ────────────────────
echo -e "${YELLOW}🔌 启动 DBHub MCP Server (端口 $DBHUB_PORT)...${NC}"

# 检查端口是否已被占用
if lsof -ti:$DBHUB_PORT &>/dev/null; then
    echo "   端口 $DBHUB_PORT 已被占用，跳过启动"
else
    npx -y @bytebase/dbhub@latest \
        --transport http \
        --port "$DBHUB_PORT" \
        --dsn "postgresql://dev_goods:lenovo2019@10.196.176.91:5432/goodslib?sslmode=disable" &
    DBHUB_PID=$!
    echo "   DBHub PID: $DBHUB_PID"

    # 等待 DBHub 就绪
    echo "   等待 DBHub 就绪..."
    for i in $(seq 1 15); do
        if curl -s "http://localhost:$DBHUB_PORT/health" &>/dev/null; then
            echo -e "${GREEN}   ✅ DBHub 已就绪${NC}"
            break
        fi
        sleep 1
    done
fi

# ── 5. 启动 Streamlit ────────────────────────────────
echo -e "${GREEN}🚀 启动 Streamlit (端口 $APP_PORT)...${NC}"
echo ""
echo -e "  访问地址: ${GREEN}http://localhost:$APP_PORT${NC}"
echo ""
streamlit run app.py --server.port "$APP_PORT" --server.address 0.0.0.0
