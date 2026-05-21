#!/bin/bash
# 监控 Codex Team 状态
# 用法: ./status_team.sh [--follow]

ROUTER_URL="${ROUTER_URL:-http://127.0.0.1:8765}"
FOLLOW="${1:-}"

show_status() {
    clear
    echo "============================================"
    echo "   📊 Codex Team 状态监控"
    echo "   $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================"
    echo ""
    
    # 检查 Router
    if ! curl -s "${ROUTER_URL}/health" > /dev/null 2>&1; then
        echo "❌ Router 未运行"
        return 1
    fi
    echo "✅ Router 运行中: ${ROUTER_URL}"
    echo ""
    
    # 获取状态
    STATUS=$(curl -s "${ROUTER_URL}/status?tasks=1")
    
    # 显示 session 信息
    SESSION=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session','N/A'))" 2>/dev/null)
    LAST_SEQ=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('last_seq','0'))" 2>/dev/null)
    echo "📝 Session: ${SESSION:0:20}..."
    echo "   消息序号: ${LAST_SEQ}"
    echo ""
    
    # 只显示在线 Agent
    echo "👥 在线 Agent:"
    PRESENCE=$(curl -s "${ROUTER_URL}/presence")
    echo "$PRESENCE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    agents = data.get('agents', {})
    online = [(n, i) for n, i in agents.items() if i.get('status') == 'online']
    if not online:
        print('   (无在线 Agent)')
    else:
        for name, info in online:
            role = info.get('meta', {}).get('role', '?')
            print(f'   🟢 {role} ({name})')
except:
    print('   解析失败')
" 2>/dev/null
    echo ""
    
    # 只显示有未处理消息的队列
    echo "📬 待处理消息:"
    echo "$STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    pending = data.get('pending_inbox', {})
    has_pending = False
    for agent, count in sorted(pending.items()):
        if count > 0:
            print(f'   📨 {agent}: {count} 条')
            has_pending = True
    if not has_pending:
        print('   ✅ 无待处理消息')
except:
    print('   解析失败')
" 2>/dev/null
    echo ""
    
    # 显示最近投递状态（只显示最近3条）
    echo "📤 最近消息投递:"
    echo "$STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    deliveries = data.get('deliveries', [])
    if not deliveries:
        print('   (无投递记录)')
    else:
        for d in deliveries[-3:]:
            status = '✅' if d.get('status') == 'accepted' else ('📤' if d.get('status') == 'delivered' else '❌')
            msg_id = d.get('message_id', '?')[-8:]
            agent = d.get('agent', '?').split('-')[0]  # 只显示角色名
            print(f'   {status} ...{msg_id} → {agent}')
except:
    print('   解析失败')
" 2>/dev/null
    echo ""
    echo "============================================"
    echo "按 Ctrl+C 退出"
}

if [ "$FOLLOW" = "--follow" ] || [ "$FOLLOW" = "-f" ]; then
    while true; do
        show_status
        sleep 2
    done
else
    show_status
fi

