from flask_socketio import emit
from ..models import db, User
from . import socketio
from datetime import datetime

@socketio.on('update_presence')
def handle_presence(data):
    """更新在线状态（客户端定时发送心跳）"""
    # 实际应验证 token 获取 user_id，这里简化处理
    # 假设客户端在连接时已绑定用户
    pass

# 注意：在线状态需要更完善的 session 管理，此处仅示例
