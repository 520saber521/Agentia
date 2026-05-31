# 铁路12306模仿网站 - 技术架构文档

## 1. 整体架构
- 前端：HTML + CSS + JavaScript（单页应用）
- 后端：Python Flask RESTful API
- 数据库：SQLite（开发环境）/ PostgreSQL（生产环境）
- 版本管理：Git

## 2. 后端技术栈
| 组件        | 技术                     |
|-------------|--------------------------|
| 框架        | Flask 2.x                |
| ORM         | SQLAlchemy               |
| 认证        | JWT (PyJWT)              |
| 密码加密    | Werkzeug (generate_password_hash) |
| 序列化      | Marshmallow              |
| API文档     | 自建（或Swagger备用）    |
| 测试        | pytest                   |

## 3. 数据库设计（核心表）
- `users` : 用户表 (id, username, password_hash, phone, email, created_at)
- `stations` : 车站表 (id, name, city, code)
- `trains` : 车次表 (id, train_number, train_type, start_station_id, end_station_id, departure_time, arrival_time, duration, base_price)
- `train_stops` : 经停站表 (id, train_id, station_id, stop_order, arrival_time, departure_time, stop_duration)
- `carriages` : 车厢表 (id, train_id, carriage_type, carriage_number, total_seats)
- `seats` : 座位表 (id, carriage_id, seat_number, seat_type)
- `tickets` : 余票视图/表 (train_id, start_stop_id, end_stop_id, seat_type, remaining)
- `orders` : 订单表 (id, user_id, order_number, status, total_price, created_at, paid_at, cancelled_at)
- `order_items` : 订单明细 (id, order_id, train_id, start_stop_id, end_stop_id, seat_id, carriage_id, passenger_name, passenger_id_card, price)

## 4. API 设计
### 4.1 用户模块
- `POST /api/auth/register` - 注册
- `POST /api/auth/login` - 登录，返回JWT
- `GET /api/user/profile` - 获取用户信息（需认证）

### 4.2 车站与车次查询
- `GET /api/stations` - 获取所有车站
- `GET /api/trains` - 按条件查询车次（出发站、到达站、日期）
- `GET /api/trains/<train_id>/stops` - 获取指定车次的经停站
- `GET /api/trains/<train_id>/seats` - 获取指定车次的座位布局（可选）

### 4.3 余票查询
- `GET /api/tickets/remaining?train_id=&from=&to=&date=&seat_type=` - 查询余票

### 4.4 订单模块
- `POST /api/orders` - 创建订单（需认证）
- `GET /api/orders` - 获取用户订单列表（需认证）
- `GET /api/orders/<order_id>` - 获取订单详情（需认证）
- `PUT /api/orders/<order_id>/pay` - 模拟支付（更新状态）
- `DELETE /api/orders/<order_id>` - 取消订单（需认证）

### 4.5 其他
- 健康检查：`GET /api/health`

## 5. 安全方案
- 密码采用 PBKDF2-SHA256 哈希存储
- JWT Token 有效期 24 小时
- 敏感操作需验证 JWT
- 输入验证（防止SQL注入已由ORM处理）

## 6. 部署建议
- 使用 Gunicorn + Nginx
- 数据库迁移使用 Alembic
- 环境变量管理配置

## 7. 扩展性预留
- 引入 Redis 缓存热门查询
- 异步任务（Celery）处理支付回调
- 微服务拆分（用户、车次、订单）
