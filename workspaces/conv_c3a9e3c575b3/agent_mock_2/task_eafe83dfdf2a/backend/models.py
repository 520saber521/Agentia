from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, fields, validate, post_load
from datetime import datetime
import hashlib

db = SQLAlchemy()

# ---- 用户模型 ----
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(11))
    email = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

class UserSchema(Schema):
    id = fields.Int(dump_only=True)
    username = fields.Str(required=True, validate=validate.Length(min=2, max=20))
    password = fields.Str(load_only=True, required=True, validate=validate.Length(min=6))
    phone = fields.Str()
    email = fields.Email()
    created_at = fields.DateTime(dump_only=True)

    @post_load
    def make_user(self, data, **kwargs):
        user = User()
        user.username = data['username']
        user.set_password(data['password'])
        if 'phone' in data:
            user.phone = data['phone']
        if 'email' in data:
            user.email = data['email']
        return user

# ---- 车站 ----
class Station(db.Model):
    __tablename__ = 'stations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    city = db.Column(db.String(50))
    code = db.Column(db.String(5), unique=True)  # 拼音缩写

class StationSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str()
    city = fields.Str()
    code = fields.Str()

# ---- 车次 ----
class Train(db.Model):
    __tablename__ = 'trains'
    id = db.Column(db.Integer, primary_key=True)
    train_number = db.Column(db.String(10), unique=True, nullable=False)
    train_type = db.Column(db.String(10))  # G/D/K/Z
    start_station_id = db.Column(db.Integer, db.ForeignKey('stations.id'))
    end_station_id = db.Column(db.Integer, db.ForeignKey('stations.id'))
    departure_time = db.Column(db.Time, nullable=False)
    arrival_time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Interval)
    base_price = db.Column(db.Float, default=0.0)

    start_station = db.relationship('Station', foreign_keys=[start_station_id])
    end_station = db.relationship('Station', foreign_keys=[end_station_id])
    stops = db.relationship('TrainStop', order_by='TrainStop.stop_order', back_populates='train')
    carriages = db.relationship('Carriage', back_populates='train')

class TrainSchema(Schema):
    id = fields.Int(dump_only=True)
    train_number = fields.Str()
    train_type = fields.Str()
    start_station = fields.Nested(StationSchema)
    end_station = fields.Nested(StationSchema)
    departure_time = fields.Time()
    arrival_time = fields.Time()
    duration = fields.Time()  # 转为字符串显示
    base_price = fields.Float()

# ---- 经停站 ----
class TrainStop(db.Model):
    __tablename__ = 'train_stops'
    id = db.Column(db.Integer, primary_key=True)
    train_id = db.Column(db.Integer, db.ForeignKey('trains.id'))
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'))
    stop_order = db.Column(db.Integer)
    arrival_time = db.Column(db.Time)
    departure_time = db.Column(db.Time)
    stop_duration = db.Column(db.Integer)  # minutes

    train = db.relationship('Train', back_populates='stops')
    station = db.relationship('Station')

class TrainStopSchema(Schema):
    id = fields.Int(dump_only=True)
    stop_order = fields.Int()
    station = fields.Nested(StationSchema)
    arrival_time = fields.Time()
    departure_time = fields.Time()
    stop_duration = fields.Int()

# ---- 车厢和座位 ----
class Carriage(db.Model):
    __tablename__ = 'carriages'
    id = db.Column(db.Integer, primary_key=True)
    train_id = db.Column(db.Integer, db.ForeignKey('trains.id'))
    carriage_type = db.Column(db.String(10))  # 二等座/一等座/软卧/硬卧
    carriage_number = db.Column(db.String(5))
    total_seats = db.Column(db.Integer, default=0)

    train = db.relationship('Train', back_populates='carriages')
    seats = db.relationship('Seat', back_populates='carriage')

class Seat(db.Model):
    __tablename__ = 'seats'
    id = db.Column(db.Integer, primary_key=True)
    carriage_id = db.Column(db.Integer, db.ForeignKey('carriages.id'))
    seat_number = db.Column(db.String(5))
    seat_type = db.Column(db.String(10))  # 窗户/过道/中间

    carriage = db.relationship('Carriage', back_populates='seats')

# ---- 余票（实时计算或预生成表）----
# 简单起见，余票通过查询已售出座位与总座位之差来计算
# 但可以建立 TicketRemaining 视图或表
class TicketRemaining(db.Model):
    __tablename__ = 'ticket_remaining'
    id = db.Column(db.Integer, primary_key=True)
    train_id = db.Column(db.Integer, db.ForeignKey('trains.id'))
    start_stop_id = db.Column(db.Integer, db.ForeignKey('train_stops.id'))
    end_stop_id = db.Column(db.Integer, db.ForeignKey('train_stops.id'))
    seat_type = db.Column(db.String(10))  # '二等座','一等座','硬座'等
    remaining = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    date = db.Column(db.Date)  # 发车日期

# ---- 订单 ----
class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending/paid/cancelled
    total_price = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='orders')
    items = db.relationship('OrderItem', back_populates='order')

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))
    train_id = db.Column(db.Integer, db.ForeignKey('trains.id'))
    start_stop_id = db.Column(db.Integer, db.ForeignKey('train_stops.id'))
    end_stop_id = db.Column(db.Integer, db.ForeignKey('train_stops.id'))
    seat_id = db.Column(db.Integer, db.ForeignKey('seats.id'))
    carriage_id = db.Column(db.Integer, db.ForeignKey('carriages.id'))
    passenger_name = db.Column(db.String(20))
    passenger_id_card = db.Column(db.String(18))
    price = db.Column(db.Float)

    order = db.relationship('Order', back_populates='items')
    train = db.relationship('Train')
    start_stop = db.relationship('TrainStop', foreign_keys=[start_stop_id])
    end_stop = db.relationship('TrainStop', foreign_keys=[end_stop_id])

# 订单相关Schema略写，在routes中定义
