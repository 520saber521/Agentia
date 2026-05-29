from flask_socketio import SocketIO

socketio = SocketIO()

from . import chat, presence, file_upload
