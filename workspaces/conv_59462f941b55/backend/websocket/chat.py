from flask import request
from flask_jwt_extended import decode_token
from flask_socketio import emit, join_room, leave_room
from ..models import db, User, Message
from . import socketio
import jwt
from datetime import datetime

@socketio.on('connect')
def handle_connect():
    """WebSocket 连接时验证 JWT"""
    token = request.args.get('token')
    if not token:
        return False
    try:
        data = decode_token(token)
        user_id = int(data['sub'])
        # 标记用户在线
        user = User.query.get(user_id)
        if user:
            user.is_online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()
            # 将用户加入个人房间（用于单聊通知）
            join_room(f'user_{user_id}')
            # 广播在线状态
            emit('user_online', {'user_id': user_id, 'is_online': True}, broadcast=True)
        return True
    except Exception as e:
        return False

@socketio.on('disconnect')
def handle_disconnect():
    """处理断开连接"""
    # 由于无法从断开事件直接获取用户ID，这里简化处理
    # 实际场景应在连接时绑定 session 存储 user_id
    pass

@socketio.on('send_message')
def handle_send_message(data):
    """处理发送消息"""
    token = request.args.get('token')
    try:
        decoded = decode_token(token)
        sender_id = int(decoded['sub'])
    except:
        emit('error', {'message': '认证失败'})
        return
    
    receiver_type = data.get('receiver_type')
    receiver_id = data.get('receiver_id')
    content = data.get('content', '').strip()
    message_type = data.get('message_type', 'text')
    
    if not receiver_type or not receiver_id or not content:
        emit('error', {'message': '参数不完整'})
        return
    
    if receiver_type not in ('user', 'group'):
        emit('error', {'message': 'receiver_type 无效'})
        return
    
    message = Message(
        sender_id=sender_id,
        receiver_type=receiver_type,
        receiver_id=receiver_id,
        content=content,
        message_type=message_type
    )
    db.session.add(message)
    db.session.commit()
    
    msg_data = message.to_dict()
    msg_data['sender'] = User.query.get(sender_id).to_dict() if User.query.get(sender_id) else None
    
    if receiver_type == 'user':
        # 发送给接收者个人房间
        emit('new_message', msg_data, room=f'user_{receiver_id}')
        # 也发送给发送者自己（确认回显）
        emit('new_message', msg_data, room=f'user_{sender_id}')
    else:
        # 群聊：广播到群房间
        emit('new_message', msg_data, room=f'group_{receiver_id}', include_self=False)
        emit('new_message', msg_data, room=f'user_{sender_id}')  # 发送者回显

@socketio.on('join_group')
def handle_join_group(data):
    """加入群组房间"""
    group_id = data.get('group_id')
    if group_id:
        join_room(f'group_{group_id}')
        emit('joined', {'group_id': group_id})

@socketio.on('leave_group')
def handle_leave_group(data):
    """离开群组房间"""
    group_id = data.get('group_id')
    if group_id:
        leave_room(f'group_{group_id}')
