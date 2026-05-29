from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Group, GroupMember, Message
from ..utils.response import success, error, paginated_response
from . import main_bp

@main_bp.route('/api/groups', methods=['POST'])
@jwt_required()
def create_group():
    """创建群组"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name or len(name) > 64:
        return error('群名称不能为空且不超过64字符')
    
    group = Group(name=name, owner_id=current_user_id)
    db.session.add(group)
    db.session.flush()  # 获取 id
    
    # 添加创建者为群主
    member = GroupMember(group_id=group.id, user_id=current_user_id, role='owner')
    db.session.add(member)
    db.session.commit()
    
    return success(group.to_dict(), '群组创建成功')

@main_bp.route('/api/groups', methods=['GET'])
@jwt_required()
def get_my_groups():
    """获取我的群组列表"""
    current_user_id = int(get_jwt_identity())
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    
    query = Group.query.join(GroupMember).filter(
        GroupMember.user_id == current_user_id
    )
    total = query.count()
    groups = query.offset((page - 1) * size).limit(size).all()
    
    return paginated_response(
        [g.to_dict() for g in groups],
        page, size, total
    )

@main_bp.route('/api/groups/<int:group_id>', methods=['GET'])
@jwt_required()
def get_group_detail(group_id):
    """获取群组详情"""
    group = Group.query.get(group_id)
    if not group:
        return error('群组不存在', http_status=404)
    return success(group.to_dict())

@main_bp.route('/api/groups/<int:group_id>/members', methods=['GET'])
@jwt_required()
def get_group_members(group_id):
    """获取群成员列表"""
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    
    group = Group.query.get(group_id)
    if not group:
        return error('群组不存在', http_status=404)
    
    query = GroupMember.query.filter_by(group_id=group_id)
    total = query.count()
    members = query.offset((page - 1) * size).limit(size).all()
    
    result = []
    for m in members:
        user = User.query.get(m.user_id)
        if user:
            item = {
                'user': user.to_dict(),
                'role': m.role,
                'joined_at': m.joined_at.isoformat()
            }
            result.append(item)
    
    return paginated_response(result, page, size, total)

@main_bp.route('/api/groups/<int:group_id>/join', methods=['POST'])
@jwt_required()
def join_group(group_id):
    """加入群组（需要群主/管理员审核，这里简化直接加入）"""
    current_user_id = int(get_jwt_identity())
    
    group = Group.query.get(group_id)
    if not group:
        return error('群组不存在', http_status=404)
    
    existing = GroupMember.query.filter_by(group_id=group_id, user_id=current_user_id).first()
    if existing:
        return error('你已在群中')
    
    member = GroupMember(group_id=group_id, user_id=current_user_id, role='member')
    db.session.add(member)
    db.session.commit()
    return success(member.to_dict(), '加入成功')

@main_bp.route('/api/groups/<int:group_id>/quit', methods=['POST'])
@jwt_required()
def quit_group(group_id):
    """退出群组"""
    current_user_id = int(get_jwt_identity())
    
    member = GroupMember.query.filter_by(group_id=group_id, user_id=current_user_id).first()
    if not member:
        return error('你不是该群成员', http_status=404)
    
    if member.role == 'owner':
        return error('群主不能退出，请先转让群组')
    
    db.session.delete(member)
    db.session.commit()
    return success(message='已退出群组')
