from models import db, User, Train, TrainStop, Station, Order, OrderItem, TicketRemaining, Carriage, Seat
from datetime import datetime, date, time
import random

def generate_order_number():
    # 简单生成：日期+随机数
    return 'T' + datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(1000,9999))

def get_remaining_tickets(train_id, from_stop_id, to_stop_id, seat_type, query_date):
    """
    查询指定车次、区间、座位类型的余票数量。
    这里简单实现：从ticket_remaining表读取。
    若表中无数据则计算总座位数作为剩余（假设无售出）。
    """
    remaining = TicketRemaining.query.filter_by(
        train_id=train_id,
        start_stop_id=from_stop_id,
        end_stop_id=to_stop_id,
        seat_type=seat_type,
        date=query_date
    ).first()
    if remaining:
        return remaining.remaining, remaining.total
    else:
        # 估算总座位数
        carriages = Carriage.query.filter_by(train_id=train_id).all()
        total = 0
        for car in carriages:
            # 根据车厢类型选择座位类型？简化：假设所有座位均为指定seat_type? 实际上需要匹配
            if car.carriage_type == seat_type:
                total += car.total_seats
        return total, total  # 假定全部未售

def create_order(user_id, items_data):
    """
    创建订单。items_data: list of dicts with keys:
    train_id, from_stop_id, to_stop_id, seat_id, passenger_name, passenger_id_card, price
    """
    order = Order()
    order.user_id = user_id
    order.order_number = generate_order_number()
    order.status = 'pending'
    order.created_at = datetime.utcnow()
    total = 0.0
    for item in items_data:
        oi = OrderItem()
        oi.order_id = order.id  # 等order插入后才有id，先赋值None？更好先flush
        oi.train_id = item['train_id']
        oi.start_stop_id = item['from_stop_id']
        oi.end_stop_id = item['to_stop_id']
        oi.seat_id = item['seat_id']
        oi.carriage_id = item['carriage_id']
        oi.passenger_name = item['passenger_name']
        oi.passenger_id_card = item['passenger_id_card']
        oi.price = item['price']
        order.items.append(oi)
        total += item['price']
    order.total_price = total
    db.session.add(order)
    db.session.commit()
    return order

def pay_order(order_id):
    order = Order.query.get(order_id)
    if not order or order.status != 'pending':
        return False
    order.status = 'paid'
    order.paid_at = datetime.utcnow()
    db.session.commit()
    return True

def cancel_order(order_id):
    order = Order.query.get(order_id)
    if not order or order.status == 'cancelled':
        return False
    order.status = 'cancelled'
    order.cancelled_at = datetime.utcnow()
    db.session.commit()
    return True
