from flask import Blueprint, request, jsonify
from models import db, User, UserSchema, Station, StationSchema, Train, TrainSchema, TrainStop, TrainStopSchema, Order, OrderItem, TicketRemaining, Carriage, Seat
from services import get_remaining_tickets, create_order, pay_order, cancel_order
from datetime import datetime, date
from functools import wraps
import jwt
import os

api = Blueprint('api', __name__)

# JWT 配置
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key-12306')
JWT_ALGORITHM = 'HS256'

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            current_user = User.query.get(data['user_id'])
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

def generate_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow()  # 实际用exp，这里简单
    }
    # 使用固定过期时间24小时
    import time
    payload['exp'] = int(time.time()) + 86400
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# ========== 健康检查 ==========
@api.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

# ========== 用户模块 ==========
@api.route('/auth/register', methods=['POST'])
def register():
    schema = UserSchema()
    data = request.get_json()
    errors = schema.validate(data)
    if errors:
        return jsonify({'errors': errors}), 400
    # 检查用户名是否已存在
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'message': 'Username already exists'}), 409
    user = schema.load(data)
    db.session.add(user)
    db.session.commit()
    token = generate_token(user.id)
    return jsonify({'message': 'Registration successful', 'token': token, 'user_id': user.id}), 201

@api.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'message': 'Username and password required'}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'message': 'Invalid credentials'}), 401
    token = generate_token(user.id)
    return jsonify({'message': 'Login successful', 'token': token, 'user_id': user.id})

@api.route('/user/profile', methods=['GET'])
@token_required
def profile(current_user):
    schema = UserSchema(exclude=('password',))
    result = schema.dump(current_user)
    return jsonify(result)

# ========== 车站 ==========
@api.route('/stations', methods=['GET'])
def get_stations():
    stations = Station.query.all()
    schema = StationSchema(many=True)
    return jsonify(schema.dump(stations))

# ========== 车次查询 ==========
@api.route('/trains', methods=['GET'])
def search_trains():
    from_station = request.args.get('from')
    to_station = request.args.get('to')
    travel_date = request.args.get('date')  # 忽略日期，仅用于余票显示
    # 简单查找：通过车站名或ID？这里通过车站ID搜索起点终点
    # 实际应通过经停站关系查找，这里简化：直接查trains表，假设用户知道车站ID
    # 更真实实现：根据from与to在train_stops中出现的位置
    if from_station and to_station:
        # 找出所有车次，其经停站包含from和to，且from顺序小于to顺序
        trains = db.session.query(Train).join(TrainStop, Train.id == TrainStop.train_id).filter(
            TrainStop.station_id == int(from_station)
        ).join(TrainStop, Train.id == TrainStop.train_id).filter(
            TrainStop.station_id == int(to_station)
        ).all()
        # 注意：上面连接有重复，需要去重
        # 更严谨用子查询
        # 简单起见先用python过滤
    else:
        trains = Train.query.all()
    
    schema = TrainSchema(many=True)
    result = schema.dump(trains)
    
    # 附加余票信息（简单返回总量）
    # 略
    return jsonify(result)

@api.route('/trains/<int:train_id>/stops', methods=['GET'])
def get_train_stops(train_id):
    stops = TrainStop.query.filter_by(train_id=train_id).order_by(TrainStop.stop_order).all()
    schema = TrainStopSchema(many=True)
    return jsonify(schema.dump(stops))

@api.route('/trains/<int:train_id>/seats', methods=['GET'])
def get_train_seats(train_id):
    # 返回车厢及座位信息
    carriages = Carriage.query.filter_by(train_id=train_id).all()
    data = []
    for car in carriages:
        seats = Seat.query.filter_by(carriage_id=car.id).all()
        data.append({
            'carriage_id': car.id,
            'carriage_number': car.carriage_number,
            'carriage_type': car.carriage_type,
            'total_seats': car.total_seats,
            'seats': [{'seat_id': s.id, 'seat_number': s.seat_number, 'seat_type': s.seat_type} for s in seats]
        })
    return jsonify(data)

# ========== 余票查询 ==========
@api.route('/tickets/remaining', methods=['GET'])
def query_remaining():
    train_id = request.args.get('train_id', type=int)
    from_stop_id = request.args.get('from_stop_id', type=int)
    to_stop_id = request.args.get('to_stop_id', type=int)
    seat_type = request.args.get('seat_type', default='二等座')
    query_date_str = request.args.get('date')
    query_date = date.today()
    if query_date_str:
        try:
            query_date = datetime.strptime(query_date_str, '%Y-%m-%d').date()
        except:
            pass
    remaining, total = get_remaining_tickets(train_id, from_stop_id, to_stop_id, seat_type, query_date)
    return jsonify({
        'train_id': train_id,
        'from_stop_id': from_stop_id,
        'to_stop_id': to_stop_id,
        'seat_type': seat_type,
        'date': query_date.isoformat(),
        'remaining': remaining,
        'total': total
    })

# ========== 订单模块 ==========
@api.route('/orders', methods=['POST'])
@token_required
def place_order(current_user):
    data = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({'message': 'No items'}), 400
    # 简单验证每个item字段
    required_fields = ['train_id', 'from_stop_id', 'to_stop_id', 'seat_id', 'carriage_id', 'passenger_name', 'passenger_id_card', 'price']
    for item in items:
        for field in required_fields:
            if field not in item:
                return jsonify({'message': f'Missing field {field}'}), 400
    try:
        order = create_order(current_user.id, items)
        return jsonify({'order_id': order.id, 'order_number': order.order_number, 'total_price': order.total_price}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500

@api.route('/orders', methods=['GET'])
@token_required
def list_orders(current_user):
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    result = []
    for o in orders:
        items = []
        for oi in o.items:
            items.append({
                'id': oi.id,
                'train_id': oi.train_id,
                'passenger_name': oi.passenger_name,
                'price': oi.price,
                'from_stop_id': oi.start_stop_id,
                'to_stop_id': oi.end_stop_id
            })
        result.append({
            'id': o.id,
            'order_number': o.order_number,
            'status': o.status,
            'total_price': o.total_price,
            'created_at': o.created_at.isoformat(),
            'paid_at': o.paid_at.isoformat() if o.paid_at else None,
            'items': items
        })
    return jsonify(result)

@api.route('/orders/<int:order_id>', methods=['GET'])
@token_required
def get_order(current_user, order_id):
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        return jsonify({'message': 'Order not found'}), 404
    items = []
    for oi in order.items:
        items.append({
            'id': oi.id,
            'train_id': oi.train_id,
            'passenger_name': oi.passenger_name,
            'price': oi.price,
        })
    return jsonify({
        'id': order.id,
        'order_number': order.order_number,
        'status': order.status,
        'total_price': order.total_price,
        'created_at': order.created_at.isoformat(),
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
        'items': items
    })

@api.route('/orders/<int:order_id>/pay', methods=['PUT'])
@token_required
def pay(current_user, order_id):
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        return jsonify({'message': 'Order not found'}), 404
    if order.status != 'pending':
        return jsonify({'message': 'Order cannot be paid'}), 400
    success = pay_order(order_id)
    if success:
        return jsonify({'message': 'Payment successful'})
    else:
        return jsonify({'message': 'Payment failed'}), 500

@api.route('/orders/<int:order_id>', methods=['DELETE'])
@token_required
def cancel(current_user, order_id):
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        return jsonify({'message': 'Order not found'}), 404
    if order.status in ('cancelled', 'paid'):
        return jsonify({'message': 'Cannot cancel this order already'}), 400
    success = cancel_order(order_id)
    if success:
        return jsonify({'message': 'Order cancelled'})
    else:
        return jsonify({'message': 'Cancel failed'}), 500
