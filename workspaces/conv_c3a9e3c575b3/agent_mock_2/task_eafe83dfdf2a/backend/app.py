from flask import Flask
from models import db
from routes import api
import os

def create_app():
    app = Flask(__name__)
    # 配置
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///railway12306.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # 初始化数据库
    db.init_app(app)
    
    # 注册蓝图
    app.register_blueprint(api, url_prefix='/api')
    
    # 创建数据库表（开发环境中使用）
    with app.app_context():
        db.create_all()
        # 可插入初始数据
        from seed_data import seed
        seed(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
