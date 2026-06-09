#!/bin/bash
# 彻底停止并清理 Codex Team
# 用法: ./stop_team.sh [--clean]

CLEAN="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "⏳ 停止 Codex Team..."

# 停止 Router
if [ -f ~/.codex_team/router.pid ]; then
    ROUTER_PID=$(cat ~/.codex_team/router.pid)
    if kill -0 "$ROUTER_PID" 2>/dev/null; then
        kill "$ROUTER_PID"
        echo "✓ Router 已停止 (PID: $ROUTER_PID)"
    else
        echo "  Router 进程不存在"
    fi
    rm -f ~/.codex_team/router.pid
else
    # 尝试用 pkill 停止
    pkill -f "python3.*api/server.py" 2>/dev/null && echo "✓ Router 已停止" || echo "  未找到 Router 进程"
fi

# 如果指定 --clean，则清理所有数据
if [ "$CLEAN" = "--clean" ] || [ "$CLEAN" = "-c" ]; then
    echo ""
    echo "🧹 清理数据..."
    
    # 清理 workspace 下的 session 数据（这是主要的数据目录）
    if [ -d "$ROOT_DIR/.codex_team" ]; then
        rm -rf "$ROOT_DIR/.codex_team"
        echo "✓ 已清理 workspace 数据"
    fi
    
    # 清理用户目录下的临时文件
    rm -rf ~/.codex_team 2>/dev/null
    mkdir -p ~/.codex_team
    echo "✓ 已清理用户临时文件"
fi

echo ""
echo "✅ Codex Team 已停止"
if [ "$CLEAN" != "--clean" ] && [ "$CLEAN" != "-c" ]; then
    echo "💡 如需清理所有历史数据，请运行: ./scripts/stop_team.sh --clean"
fi
echo "💡 注意: 请手动关闭 Codex 终端窗口"

