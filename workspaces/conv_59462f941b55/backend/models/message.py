from datetime import datetime
from . import db

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    receiver_type = db.Column(db.String(16), nullable=False)  # 'user' 或 'group'
    receiver_id = db.Column(db.Integer, nullable=False, index=True)  # 对方用户ID或群ID
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(16), default='text')  # text, image, file, system
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(16), default='sent')  # sent, delivered, read
    
    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'receiver_type': self.receiver_type,
            'receiver_id': self.receiver_id,
            'content': self.content,
            'message_type': self.message_type,
            'created_at': self.created_at.isoformat(),
            'status': self.status
        }
