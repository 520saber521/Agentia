from flask import request
from flask_jwt_extended import create_access_token, create_refresh_token
from ..models import db, User
from ..utils.response import success, error
from . import main_bp
import bcrypt

@main_bp.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    if not data:
        return error('请求数据无效')
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    nickname = data.get('nickname', '').strip() or username
    
    if not username or not password:
        return error('用户名和密码不能为空')
    
    if len(username) < 3 or len(username) > 32:
        return error('用户名长度需在3-32字符之间')
    
    if len(password) < 6:
        return error('密码长度至少6个字符')
    
    existing = User.query.filter_by(username=username).first()
    if existing:
        return error('用户名已存在')
    
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user = User(username=username, password_hash=password_hash, nickname=nickname)
    db.session.add(user)
    db.session.commit()
    
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    
    return success({
        'user': user.to_dict(),
        'access_token': access_token,
        'refresh_token': refresh_token
    }, '注册成功')

@main_bp.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    if not data:
        return error('请求数据无效')
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return error('用户名和密码不能为空')
    
    user = User.query.filter_by(username=username).first()
    if not user:
        return error('用户不存在')
    
    if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        return error('密码错误')
    
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    
    user.is_online = True
    db.session.commit()
    
    return success({
        'user': user.to_dict(),
        'access_token': access_token,
        'refresh_token': refresh_token
    }, '登录成功')

@main_bp.route('/api/auth/refresh', methods=['POST'])
def refresh():
    """刷新 token"""
    from flask_jwt_extended import get_jwt_identity, jwt_required
    
    @jwt_required(refresh=True)
    def wrapper():
        current_user_id = get_jwt_identity()
        access_token = create_access_token(identity=current_user_id)
        return success({'access_token': access_token}, '刷新成功')
    
    return wrapper()
