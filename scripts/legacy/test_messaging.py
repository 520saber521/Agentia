#!/usr/bin/env python3
"""
Test script for verifying inter-window messaging.
This script simulates sending and receiving messages between agents.

Usage:
    # First, start the router (in a separate terminal):
    python3 src/api/server.py . --host 127.0.0.1 --port 8765

    # Then run this test:
    python3 scripts/test_messaging.py
"""

import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

ROUTER_URL = "http://127.0.0.1:8765"


def wait_for_router(timeout=10):
    """Wait for router to be available."""
    print(f"Waiting for router at {ROUTER_URL}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{ROUTER_URL}/health", method="GET")
            with urlopen(req, timeout=2) as res:
                if res.status == 200:
                    print("✓ Router is available")
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    print("✗ Router not available")
    return False


def register_presence(agent_id, role):
    """Register agent presence."""
    url = f"{ROUTER_URL}/presence/register"
    payload = {
        "agent": agent_id,
        "meta": {"role": role}
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as res:
            result = json.loads(res.read())
            print(f"✓ Registered presence: {agent_id} ({role})")
            return result
    except Exception as e:
        print(f"✗ Failed to register presence: {e}")
        return None


def send_message(from_role, to_role, message_text, task_id=None):
    """Send a message through the router."""
    url = f"{ROUTER_URL}/messages"
    
    # Body must be a JSON-encoded string, not a dict
    body_dict = {
        "code_path": "test.py",
        "question": message_text,
        "context": "test context"
    }
    
    payload = {
        "v": "1",
        "type": "ask",
        "action": "clarify",
        "from": from_role,
        "to": [to_role],
        "body": json.dumps(body_dict),  # Must be JSON string
        "body_encoding": "json",
        "agent_instance": f"{from_role}-test-001",
        "task_id": task_id or f"TEST-{from_role}-{int(time.time())}",
        "owner": from_role,
    }
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as res:
            result = json.loads(res.read())
            print(f"✓ Sent message from {from_role} to {to_role}: {message_text[:50]}...")
            return result
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
        print(f"✗ Failed to send message: {e} - {error_body}")
        return None
    except Exception as e:
        print(f"✗ Failed to send message: {e}")
        return None


def check_inbox(agent_id, limit=5):
    """Check the inbox for an agent."""
    url = f"{ROUTER_URL}/inbox?agent={agent_id}&limit={limit}"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as res:
            result = json.loads(res.read())
            messages = result.get("messages", [])
            if messages:
                print(f"✓ Found {len(messages)} message(s) in {agent_id}'s inbox")
                for msg in messages:
                    body = msg.get("body", "")
                    # Body might be a JSON string, try to parse it
                    if isinstance(body, str):
                        try:
                            body = json.loads(body)
                        except:
                            pass
                    question = body.get("question", "") if isinstance(body, dict) else str(body)
                    print(f"  - From: {msg.get('from')}, Body: {question[:50]}...")
            else:
                print(f"  No messages in {agent_id}'s inbox")
            return messages
    except Exception as e:
        print(f"✗ Failed to check inbox: {e}")
        return []


def send_ack(agent_id, message_id):
    """Send an acknowledgment for a message."""
    url = f"{ROUTER_URL}/acks"
    payload = {
        "ack": "accepted",
        "id": message_id,
        "agent": agent_id
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as res:
            print(f"✓ Acknowledged message: {message_id}")
            return json.loads(res.read())
    except Exception as e:
        print(f"✗ Failed to send ack: {e}")
        return None


def main():
    print("=" * 60)
    print("Inter-Window Messaging Test")
    print("=" * 60)
    print()
    
    # Step 1: Wait for router
    if not wait_for_router():
        print("\nPlease start the router first:")
        print("  python3 src/api/server.py . --host 127.0.0.1 --port 8765")
        sys.exit(1)
    print()
    
    # Step 2: Register agents
    print("Registering agents...")
    agents = [
        ("MAIN-test-001", "MAIN"),
        ("A-test-001", "A"),
        ("B-test-001", "B"),
    ]
    for agent_id, role in agents:
        register_presence(agent_id, role)
    print()
    
    # Step 3: Send message from MAIN to A
    print("Sending message from MAIN to A...")
    result = send_message("MAIN", "A", "Hello Agent A, please help me implement a function.", task_id="TEST-TASK-001")
    if result:
        message_id = result.get("id")
        print(f"  Message ID: {message_id}")
    print()
    
    # Step 4: Check A's inbox
    print("Checking A's inbox...")
    messages = check_inbox("A-test-001")
    if messages:
        # Acknowledge the message
        for msg in messages:
            send_ack("A-test-001", msg.get("id"))
    print()
    
    # Step 5: Send message from A to B
    print("Sending message from A to B...")
    send_message("A", "B", "Hey B, can you review this code?", task_id="TEST-TASK-002")
    print()
    
    # Step 6: Check B's inbox
    print("Checking B's inbox...")
    messages = check_inbox("B-test-001")
    if messages:
        for msg in messages:
            send_ack("B-test-001", msg.get("id"))
    print()
    
    # Step 7: Check overall status
    print("Checking router status...")
    try:
        req = Request(f"{ROUTER_URL}/status?tasks=1", method="GET")
        with urlopen(req, timeout=5) as res:
            status = json.loads(res.read())
            print(f"  Session: {status.get('session')}")
            print(f"  Epoch: {status.get('epoch')}")
            print(f"  Last Seq: {status.get('last_seq')}")
            pending = status.get('pending_inbox', {})
            if pending:
                print(f"  Pending messages: {pending}")
    except Exception as e:
        print(f"✗ Failed to get status: {e}")
    
    print()
    print("=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
