import os
import sys
import tempfile


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from router import Router  # noqa: E402


def run_smoke_test() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        router = Router(workspace)
        router.start()
        message = {
            "from": "MAIN",
            "to": ["A"],
            "type": "ask",
            "action": "assign",
            "task_id": "SMOKE-1",
            "owner": "MAIN",
            "deadline": 1700000000000,
            "agent_instance": "MAIN-01",
            "body_encoding": "json",
            "body": "{\"task_type\":\"implement\",\"files\":[\"src/router/router.py\"],\"success_criteria\":[\"smoke\"],\"dependencies\":[]}",
        }
        response = router.receive_message(message)
        if response.get("status") != "delivered":
            raise RuntimeError("message not delivered")
        ack = router.receive_ack(
            {"ack_stage": "accepted", "corr": response["id"], "agent": "A"}
        )
        if ack.get("ack") != "accepted":
            raise RuntimeError("ack not accepted")
        status = router.status(include_tasks=True)
        if "SMOKE-1" not in status.get("tasks", {}):
            raise RuntimeError("task not tracked")
        trace = router.trace(message_id=response["id"])
        if not trace.get("message"):
            raise RuntimeError("trace missing message")
        router.stop(timeout=1)
    print("smoke test ok")


if __name__ == "__main__":
    run_smoke_test()
