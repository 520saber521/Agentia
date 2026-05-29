from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import json
import asyncio

# ---------- 配置 ----------
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 密码上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

app = FastAPI(title="MockQQ Backend", version="1.0.0")

# ---------- 数据模型 ----------
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    password: str = Field(..., min_length=6)

class UserOut(BaseModel):
    id: int
    username: str

class FriendRequest(BaseModel):
    target_username: str

class MessageSend(BaseModel):
    receiver_id: int
    content: str = Field(..., max_length=500)

class MessageOut(BaseModel):
    sender_id: int
    sender_username: str
    receiver_id: int
    content: str
    timestamp: datetime

# ---------- 内存存储（模拟数据库） ----------
fake_users_db: Dict[str, dict] = {}  # username -> {id, username, hashed_password}
fake_friends: Dict[int, set] = {}    # user_id -> set of friend_ids
fake_messages: List[dict] = []       # 全部消息（简单实现）
next_user_id = 1

# ---------- 工具函数 ----------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = fake_users_db.get(username)
    if user is None:
        raise credentials_exception
    return user

def get_user_by_username(username: str):
    return fake_users_db.get(username)

def get_user_by_id(user_id: int):
    for u in fake_users_db.values():
        if u["id"] == user_id:
            return u
    return None

# ---------- REST API ----------

@app.post("/register")
async def register(user: UserRegister):
    if user.username in fake_users_db:
        raise HTTPException(status_code=400, detail="用户名已存在")
    global next_user_id
    new_user = {
        "id": next_user_id,
        "username": user.username,
        "hashed_password": get_password_hash(user.password)
    }
    fake_users_db[user.username] = new_user
    fake_friends[new_user["id"]] = set()
    next_user_id += 1
    return {"msg": "注册成功", "user_id": new_user["id"]}

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return UserOut(id=current_user["id"], username=current_user["username"])

@app.post("/friends/add")
async def add_friend(req: FriendRequest, current_user: dict = Depends(get_current_user)):
    target_user = get_user_by_username(req.target_username)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target_user["id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="不能添加自己为好友")
    if target_user["id"] in fake_friends[current_user["id"]]:
        raise HTTPException(status_code=400, detail="已是好友")
    fake_friends[current_user["id"]].add(target_user["id"])
    fake_friends[target_user["id"]].add(current_user["id"])
    return {"msg": "好友添加成功"}

@app.get("/friends/list", response_model=List[UserOut])
async def list_friends(current_user: dict = Depends(get_current_user)):
    friend_ids = fake_friends.get(current_user["id"], set())
    friends = []
    for uid in friend_ids:
        user = get_user_by_id(uid)
        if user:
            friends.append(UserOut(id=user["id"], username=user["username"]))
    return friends

@app.post("/messages/send")
async def send_message(msg: MessageSend, current_user: dict = Depends(get_current_user)):
    receiver = get_user_by_id(msg.receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="接收用户不存在")
    if msg.receiver_id not in fake_friends.get(current_user["id"], set()):
        raise HTTPException(status_code=403, detail="只能向好友发送消息")
    message_record = {
        "sender_id": current_user["id"],
        "sender_username": current_user["username"],
        "receiver_id": msg.receiver_id,
        "content": msg.content,
        "timestamp": datetime.utcnow()
    }
    fake_messages.append(message_record)
    # 尝试通过 WebSocket 实时推送
    ws_receiver = active_connections.get(msg.receiver_id)
    if ws_receiver:
        try:
            await ws_receiver.send_json({
                "type": "new_message",
                "message": {
                    "sender_id": current_user["id"],
                    "sender_username": current_user["username"],
                    "content": msg.content,
                    "timestamp": message_record["timestamp"].isoformat()
                }
            })
        except Exception:
            pass
    return {"msg": "消息已发送", "message_id": len(fake_messages)}

@app.get("/messages/history/{friend_id}", response_model=List[MessageOut])
async def get_message_history(friend_id: int, current_user: dict = Depends(get_current_user)):
    if friend_id not in fake_friends.get(current_user["id"], set()):
        raise HTTPException(status_code=403, detail="只能查看好友的聊天记录")
    user_id = current_user["id"]
    history = []
    for m in fake_messages:
        if (m["sender_id"] == user_id and m["receiver_id"] == friend_id) or \
           (m["sender_id"] == friend_id and m["receiver_id"] == user_id):
            history.append(MessageOut(**m))
    return history

# ---------- WebSocket ----------
active_connections: Dict[int, WebSocket] = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # 先认证：客户端发送第一个消息为 token
    try:
        data = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        auth_data = json.loads(data)
        token = auth_data.get("token")
        if not token:
            await websocket.send_json({"error": "缺少token"})
            await websocket.close()
            return
        # 验证 token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None or username not in fake_users_db:
            await websocket.send_json({"error": "无效token"})
            await websocket.close()
            return
        user = fake_users_db[username]
        user_id = user["id"]
        active_connections[user_id] = websocket
        await websocket.send_json({"type": "auth_ok", "user_id": user_id})
        # 保持连接，等待消息
        while True:
            try:
                msg_text = await websocket.receive_text()
                msg_data = json.loads(msg_text)
                if msg_data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_json({"error": str(e)})
    except asyncio.TimeoutError:
        await websocket.send_json({"error": "认证超时"})
    finally:
        # 清理连接
        for uid, ws in list(active_connections.items()):
            if ws == websocket:
                del active_connections[uid]
                break

# ---------- 启动 ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
