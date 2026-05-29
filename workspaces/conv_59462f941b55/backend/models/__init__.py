from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .user import User
from .friend import Friend
from .group import Group, GroupMember
from .message import Message
from .file import File
