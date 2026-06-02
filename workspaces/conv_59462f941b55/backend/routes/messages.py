from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Message
from ..utils.response import success, error, paginated_response
from . import main_bp

@main_bp.route('/api/messages', methods=['GET'])
@jwt_required()
def get_messages():
    """获取聊天历史（单聊或群聊）"""
    current_user_id = int(get_jwt_identity())
    receiver_type = request.args.get('receiver_type')  # 'user' or 'group'
    receiver_id = request.args.get('receiver_id', type=int)
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    
    if not receiver_type or not receiver_id:
        return error('请提供 receiver_type 和 receiver_id')
    
    if receiver_type not in ('user', 'group'):
        return error('receiver_type 必须为 user 或 group')
    
    if receiver_type == 'user':
        # 单聊：查询双方之间的消息
        query = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_type == 'user') & (Message.receiver_id == receiver_id)) |
            ((Message.sender_id == receiver_id) & (Message.receiver_type == 'user') & (Message.receiver_id == current_user_id))
        ).order_by(Message.created_at.desc())
    else:
        # 群聊：查询该群的所有消息
        query = Message.query.filter_by(
            receiver_type='group', receiver_id=receiver_id
        ).order_by(Message.created_at.desc())
    
    total = query.count()
    messages = query.offset((page - 1) * size).limit(size).all()
    
    # 按时间正序返回（最新消息在最后）
    messages.reverse()
    return paginated_response(
        [m.to_dict() for m in messages],
        page, size, total
    )

@main_bp.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    """发送消息（通过 REST 方式，实际实时聊天建议走 WebSocket）"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    
    receiver_type = data.get('receiver_type')
    receiver_id = data.get('receiver_id')
    content = data.get('content', '').strip()
    message_type = data.get('message_type', 'text')
    
    if not receiver_type or not receiver_id or not content:
        return error('缺少必要字段')
    
    if receiver_type not in ('user', 'group'):
        return error('receiver_type 必须为 user 或 group')
    
    message = Message(
        sender_id=current_user_id,
        receiver_type=receiver_type,
        receiver_id=receiver_id,
        content=content,
        message_type=message_type
    )
    db.session.add(message)
    db.session.commit()
    
    return success(message.to_dict(), '消息已发送')
