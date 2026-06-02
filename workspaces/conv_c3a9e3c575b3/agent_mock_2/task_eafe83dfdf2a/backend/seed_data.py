from models import db, User, Station, Train, TrainStop, Carriage, Seat, TicketRemaining
from datetime import time, date, datetime
import random

def seed(app):
    """插入初始样例数据"""
    with app.app_context():
        # 检查是否已有数据
        if Station.query.first() is not None:
            return  # 已存在数据，跳过

        # 车站
        stations = [
            Station(name='北京南', city='北京', code='BJP'),
            Station(name='上海虹桥', city='上海', code='SHH'),
            Station(name='广州南', city='广州', code='GZS'),
            Station(name='深圳北', city='深圳', code='SZB'),
            Station(name='杭州东', city='杭州', code='HZH'),
            Station(name='南京南', city='南京', code='NJH'),
        ]
        db.session.add_all(stations)
        db.session.commit()

        # 车次
        train1 = Train(train_number='G1234', train_type='G', 
                       start_station_id=1, end_station_id=2,
                       departure_time=time(8,0), arrival_time=time(12,30),
                       base_price=553.0)
        train2 = Train(train_number='D5678', train_type='D',
                       start_station_id=1, end_station_id=3,
                       departure_time=time(9,0), arrival_time=time(17,0),
                       base_price=480.0)
        db.session.add_all([train1, train2])
        db.session.commit()

        # 经停站
        # 北京南到上海虹桥：G1234
        stops1 = [
            TrainStop(train_id=1, station_id=1, stop_order=1, departure_time=time(8,0)),
            TrainStop(train_id=1, station_id=5, stop_order=2, arrival_time=time(9,30), departure_time=time(9,35), stop_duration=5),
            TrainStop(train_id=1, station_id=6, stop_order=3, arrival_time=time(10,15), departure_time=time(10,20), stop_duration=5),
            TrainStop(train_id=1, station_id=2, stop_order=4, arrival_time=time(12,30)),
        ]
        db.session.add_all(stops1)
        # 北京南到广州南：D5678
        stops2 = [
            TrainStop(train_id=2, station_id=1, stop_order=1, departure_time=time(9,0)),
            TrainStop(train_id=2, station_id=6, stop_order=2, arrival_time=time(10,20), departure_time=time(10,25), stop_duration=5),
            TrainStop(train_id=2, station_id=5, stop_order=3, arrival_time=time(11,15), departure_time=time(11,20), stop_duration=5),
            TrainStop(train_id=2, station_id=3, stop_order=4, arrival_time=time(17,0)),
        ]
        db.session.add_all(stops2)
        db.session.commit()

        # 车厢和座位（为每个车次添加几节车厢）
        for train_id in [1,2]:
            for carriage_num in range(1,4):
                carriage = Carriage(train_id=train_id, carriage_type='二等座', 
                                    carriage_number=f'0{carriage_num}', total_seats=80)
                db.session.add(carriage)
                db.session.commit()
                # 生成座位
                for row in range(1,21):  # 每排5座? 简化20排*4座
                    for col in ['A','B','C','D']:
                        seat = Seat(carriage_id=carriage.id, seat_number=f'{row}{col}', seat_type='二等座')
                        db.session.add(seat)
            # 再加一节一等座
            carriage = Carriage(train_id=train_id, carriage_type='一等座',
                                carriage_number='04', total_seats=50)
            db.session.add(carriage)
        db.session.commit()

        # 预生成余票数据（示例：全部80张）
        for train_id in [1,2]:
            for seat_type in ['二等座','一等座']:
                # 假设整列车所有可售区间都相同，只生成起点到终点
                tr = TicketRemaining(train_id=train_id, 
                                     start_stop_id=1, 
                                     end_stop_id=4 if train_id==1 else 4,  # 终点站stop_order=4
                                     seat_type=seat_type,
                                     remaining=80 if seat_type=='二等座' else 50,
                                     total=80 if seat_type=='二等座' else 50,
                                     date=date.today())
                db.session.add(tr)
        db.session.commit()

        # 创建测试用户
        test_user = User(username='test', phone='13812345678')
        test_user.set_password('123456')
        db.session.add(test_user)
        db.session.commit()

        print('Seed data inserted successfully.')
