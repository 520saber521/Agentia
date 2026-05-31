from datetime import datetime
from . import db

class File(db.Model):
    __tablename__ = 'files'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(256), nullable=False)
    size = db.Column(db.Integer, nullable=False)  # 字节
    mime_type = db.Column(db.String(64), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    thumbnail_path = db.Column(db.String(512))  # 缩略图路径（图片）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'uploader_id': self.uploader_id,
            'filename': self.filename,
            'size': self.size,
            'mime_type': self.mime_type,
            'file_path': self.file_path,
            'thumbnail_path': self.thumbnail_path,
            'created_at': self.created_at.isoformat()
        }
