from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Friend
from ..utils.response import success, error, paginated_response
from . import main_bp

@main_bp.route('/api/users/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """获取当前用户信息"""
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return error('用户不存在', http_status=404)
    return success(user.to_dict())

@main_bp.route('/api/users/me', methods=['PUT'])
@jwt_required()
def update_current_user():
    """更新当前用户信息"""
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return error('用户不存在', http_status=404)
    
    data = request.get_json()
    if 'nickname' in data:
        user.nickname = data['nickname']
    if 'signature' in data:
        user.signature = data['signature']
    db.session.commit()
    return success(user.to_dict(), '更新成功')

@main_bp.route('/api/users/search', methods=['GET'])
@jwt_required()
def search_users():
    """搜索用户（按用户名或昵称模糊匹配）"""
    keyword = request.args.get('keyword', '').strip()
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    
    if not keyword:
        return error('请输入搜索关键词')
    
    query = User.query.filter(
        (User.username.contains(keyword)) | (User.nickname.contains(keyword))
    ).order_by(User.id)
    
    total = query.count()
    users = query.offset((page - 1) * size).limit(size).all()
    
    return paginated_response(
        [user.to_dict() for user in users],
        page, size, total
    )

@main_bp.route('/api/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_profile(user_id):
    """获取指定用户公开信息"""
    user = User.query.get(user_id)
    if not user:
        return error('用户不存在', http_status=404)
    return success(user.to_dict())

# ---- 好友管理 ----

@main_bp.route('/api/friends/requests', methods=['POST'])
@jwt_required()
def send_friend_request():
    """发送好友请求"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    friend_id = data.get('friend_id')
    
    if not friend_id:
        return error('缺少 friend_id')
    
    if current_user_id == friend_id:
        return error('不能添加自己为好友')
    
    friend = User.query.get(friend_id)
    if not friend:
        return error('目标用户不存在', http_status=404)
    
    # 检查是否已经是好友
    existing = Friend.query.filter_by(
        user_id=current_user_id, friend_id=friend_id
    ).first()
    if existing:
        if existing.status == 'accepted':
            return error('已经是好友了')
        elif existing.status == 'pending':
            return error('已经发送过好友请求')
        elif existing.status == 'blocked':
            return error('无法向该用户发送请求')
    
    # 创建双向关系？因为好友是双向的，我们只创建一个记录，但查询时会查询两个方向
    friend_req = Friend(user_id=current_user_id, friend_id=friend_id, status='pending')
    db.session.add(friend_req)
    db.session.commit()
    
    return success(friend_req.to_dict(), '好友请求已发送')

@main_bp.route('/api/friends/requests', methods=['GET'])
@jwt_required()
def get_friend_requests():
    """获取收到的好友请求列表"""
    current_user_id = int(get_jwt_identity())
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    
    query = Friend.query.filter_by(friend_id=current_user_id, status='pending')
    total = query.count()
    requests = query.offset((page - 1) * size).limit(size).all()
    
    result = []
    for req in requests:
        item = req.to_dict()
        user = User.query.get(req.user_id)
        item['user'] = user.to_dict() if user else None
        result.append(item)
    
    return paginated_response(result, page, size, total)

@main_bp.route('/api/friends/requests/<int:request_id>', methods=['PUT'])
@jwt_required()
def handle_friend_request(request_id):
    """处理好友请求（同意/拒绝）"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    action = data.get('action')  # 'accept' 或 'reject'
    
    if action not in ('accept', 'reject'):
        return error('action 必须为 accept 或 reject')
    
    req = Friend.query.get(request_id)
    if not req or req.friend_id != current_user_id or req.status != 'pending':
        return error('好友请求不存在或已处理', http_status=404)
    
    if action == 'accept':
        req.status = 'accepted'
        # 创建反向关系（可选：使用双向记录简化查询）
        reverse = Friend.query.filter_by(
            user_id=req.friend_id, friend_id=req.user_id
        ).first()
        if not reverse:
            reverse = Friend(user_id=req.friend_id, friend_id=req.user_id, status='accepted')
            db.session.add(reverse)
        else:
            reverse.status = 'accepted'
        db.session.commit()
        return success(req.to_dict(), '已同意好友请求')
    else:
        req.status = 'rejected'
        db.session.commit()
        return success(req.to_dict(), '已拒绝好友请求')

@main_bp.route('/api/friends', methods=['GET'])
@jwt_required()
def get_friend_list():
    """获取好友列表"""
    current_user_id = int(get_jwt_identity())
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    
    # 查询所有 accepted 状态的好友（双向）
    query = Friend.query.filter(
        ((Friend.user_id == current_user_id) | (Friend.friend_id == current_user_id)) & 
        (Friend.status == 'accepted')
    )
    total = query.count()
    friendships = query.offset((page - 1) * size).limit(size).all()
    
    friend_list = []
    for f in friendships:
        other_id = f.friend_id if f.user_id == current_user_id else f.user_id
        user = User.query.get(other_id)
        if user:
            item = user.to_dict()
            item['remark'] = f.remark
            friend_list.append(item)
    
    return paginated_response(friend_list, page, size, total)

@main_bp.route('/api/friends/<int:friend_id>', methods=['DELETE'])
@jwt_required()
def delete_friend(friend_id):
    """删除好友"""
    current_user_id = int(get_jwt_identity())
    
    # 查找两个方向的好友记录
    Friendship = Friend.query.filter(
        ((Friend.user_id == current_user_id) & (Friend.friend_id == friend_id)) |
        ((Friend.user_id == friend_id) & (Friend.friend_id == current_user_id))
    ).all()
    
    if not Friendship:
        return error('好友关系不存在', http_status=404)
    
    for f in Friendship:
        db.session.delete(f)
    db.session.commit()
    return success(message='好友已删除')
