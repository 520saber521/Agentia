from flask import request
from flask_socketio import emit
from ..models import db, File, User
from . import socketio
import os
from werkzeug.utils import secure_filename
from ..config import Config

@socketio.on('upload_file')
def handle_file_upload(data):
    """通过 WebSocket 上传文件（分片）"""
    # 简化处理，实际应使用分片上传
    emit('error', {'message': '文件上传暂未实现 WebSocket 方式，请使用 REST API'})
