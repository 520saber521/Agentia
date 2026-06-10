Storage/state facade example

```python
from storage.facade import StorageFacade
from state.facade import recover_workspace

store = StorageFacade.open("/path/to/workspace", roles=["MAIN", "A", "B", "C", "D"])

message = {
    "id": "msg-1",
    "session": store.session["session_id"],
    "epoch": 1,
    "seq": 1,
    "from": "MAIN",
    "to": ["A"],
    "type": "ask",
    "action": "assign",
    "task_id": "TASK-1",
    "ts": 1710000000000,
    "body": "{\"task_type\":\"implement\"}",
}

store.append_message(epoch=1, message=message)
store.record_inbox_delivery(agent="A", message_id="msg-1")
store.append_ack(epoch=1, message_id="msg-1", ack="delivered", agent="A")

bundle = recover_workspace("/path/to/workspace", agents=["MAIN", "A"])
print(bundle.router_state.epoch, bundle.max_seq)
```
