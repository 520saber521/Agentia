from flask import Blueprint

# 创建主蓝图
main_bp = Blueprint('main', __name__)

from . import auth, users, groups, messages
