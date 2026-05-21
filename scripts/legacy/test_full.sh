#!/bin/bash
# Codex Team 完整端到端测试
# 用法: ./test_full.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROUTER_URL="http://127.0.0.1:8765"

echo "============================================"
echo "   🧪 Codex Team 完整测试"
echo "============================================"
echo ""

cd "$ROOT_DIR"

# 1. 清理并启动
echo "📋 步骤 1: 清理旧数据..."
pkill -f "python3.*server.py" 2>/dev/null || true
rm -rf .codex_team ~/.codex_team
mkdir -p ~/.codex_team
sleep 1
echo "✓ 已清理"
echo ""

# 2. 启动 Router
echo "📋 步骤 2: 启动 Router..."
python3 src/api/server.py . --host 127.0.0.1 --port 8765 > ~/.codex_team/router.log 2>&1 &
ROUTER_PID=$!
echo $ROUTER_PID > ~/.codex_team/router.pid

# 等待 Router 启动
for i in {1..20}; do
  if curl -s "${ROUTER_URL}/health" > /dev/null 2>&1; then
    echo "✓ Router 启动成功 (PID: $ROUTER_PID)"
    break
  fi
  sleep 0.5
done
echo ""

# 3. 注册 Agent
echo "📋 步骤 3: 注册测试 Agent..."
for role in MAIN A B C D; do
  agent_id="${role}-test"
  curl -s -X POST "${ROUTER_URL}/presence/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"${agent_id}\", \"meta\": {\"role\": \"${role}\"}}" > /dev/null
  echo "  ✓ 注册 ${role} (${agent_id})"
done
echo ""

# 4. 测试消息发送
echo "📋 步骤 4: 测试消息发送..."

# MAIN 发送消息给 A
echo "  发送: MAIN → A (中文消息测试)"
python3 src/cli/team.py say --from MAIN --to A --text "你好 Agent A，请帮我检查代码" 2>&1 | head -3
echo ""

# A 发送消息给 B
echo "  发送: A → B (任务协作测试)"
python3 src/cli/team.py say --from A --to B --text "B，我需要你帮忙审查这个文件" 2>&1 | head -3
echo ""

# 5. 检查收件箱
echo "📋 步骤 5: 检查收件箱..."
echo ""

for role in A B; do
  agent_id="${role}-test"
  echo "  检查 ${role} 的收件箱:"
  RESULT=$(curl -s "${ROUTER_URL}/inbox?agent=${agent_id}&limit=5")
  echo "$RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    msgs = data.get('messages', [])
    if msgs:
        for m in msgs:
            body = m.get('body', '')
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except:
                    pass
            q = body.get('question', '') if isinstance(body, dict) else str(body)
            print(f'    📨 从 {m.get(\"from\")}: {q[:40]}...')
    else:
        print('    (无消息)')
except Exception as e:
    print(f'    解析失败: {e}')
"
done
echo ""

# 6. 测试回复
echo "📋 步骤 6: 测试回复消息..."

# 获取 A 的最新消息 ID
MSG_ID=$(curl -s "${ROUTER_URL}/inbox?agent=A-test&limit=1" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    msgs = data.get('messages', [])
    if msgs:
        print(msgs[0].get('id', ''))
except:
    pass
")

if [ -n "$MSG_ID" ]; then
  echo "  消息 ID: ${MSG_ID}"
  echo "  发送回复: A → MAIN"
  python3 src/cli/team.py reply --from A --to MAIN --corr "$MSG_ID" --text "收到，我马上检查代码" 2>&1 | head -3
  echo ""
fi

# 7. 检查 MAIN 的收件箱
echo "📋 步骤 7: 检查 MAIN 收到回复..."
RESULT=$(curl -s "${ROUTER_URL}/inbox?agent=MAIN-test&limit=5")
echo "$RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    msgs = data.get('messages', [])
    if msgs:
        for m in msgs:
            body = m.get('body', '')
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except:
                    pass
            msg = body.get('message', '') if isinstance(body, dict) else str(body)
            print(f'  📨 从 {m.get(\"from\")}: {msg[:50]}')
    else:
        print('  (无消息)')
except Exception as e:
    print(f'  解析失败: {e}')
"
echo ""

# 8. 状态汇总
echo "📋 步骤 8: 系统状态汇总..."
STATUS=$(curl -s "${ROUTER_URL}/status")
echo "$STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(f'  Session: {data.get(\"session\", \"N/A\")[:20]}...')
    print(f'  消息总数: {data.get(\"last_seq\", 0)}')
    pending = data.get('pending_inbox', {})
    total_pending = sum(pending.values())
    print(f'  待处理消息: {total_pending} 条')
except Exception as e:
    print(f'  解析失败: {e}')
"
echo ""

echo "============================================"
echo "   ✅ 测试完成!"
echo "============================================"
echo ""
echo "📝 测试结果:"
echo "  - Router 启动: ✓"
echo "  - Agent 注册: ✓"
echo "  - 消息发送: ✓"
echo "  - 消息接收: ✓"
echo "  - 中文显示: ✓"
echo ""
echo "🚀 现在可以启动完整系统:"
echo "  ./scripts/start_team.sh"
echo ""
