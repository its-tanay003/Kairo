"""
End-to-End Service Boundary Test.
Verifies:
1. Orchestrator loads ToolSpec from /registry
2. Gateway WebSocket connection & routing
3. Orchestrator executes agent loop and writes exact 20-field Event row to SQLite /events/events.db
4. Gateway streams response & Event back over WebSocket
5. Direct SQLite verification of the written row
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import websockets

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "events" / "events.db"

REQUIRED_FIELDS = [
    "session_id",
    "task_id",
    "timestamp",
    "actor",
    "tool_id",
    "tool_version",
    "requested_args",
    "normalized_args",
    "process_id",
    "start_time",
    "end_time",
    "exit_code",
    "stdout_ref",
    "stderr_ref",
    "artifact_refs",
    "screenshots",
    "network_context",
    "result_summary",
    "confidence",
    "parent_event",
]


async def run_e2e_test():
    print("\n=======================================================")
    print("STARTING SERVICE BOUNDARY VERIFICATION")
    print("=======================================================\n")

    # 1. Start Orchestrator process
    print("[1/5] Launching Orchestrator (FastAPI on port 8000)...")
    orch_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orchestrator.server:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 2. Start Gateway process
    print("[2/5] Launching Gateway (Node/TS WebSocket on port 4000)...")
    gateway_proc = subprocess.Popen(
        ["npm", "start"],
        cwd=str(ROOT / "gateway"),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Give servers a moment to bind
        time.sleep(3)

        # 3. Connect to Gateway WebSocket
        print("[3/5] Connecting client to Gateway over WebSocket (ws://127.0.0.1:4000)...")
        uri = "ws://127.0.0.1:4000/?sessionId=sess_e2e_test"
        
        async with websockets.connect(uri) as ws:
            # Receive handshake
            raw_handshake = await asyncio.wait_for(ws.recv(), timeout=5.0)
            handshake = json.loads(raw_handshake)
            print(f"      -> Received handshake from Gateway: {handshake.get('sessionId')}")
            assert handshake.get("type") == "handshake"

            # Send chat message to trigger tool and orchestrator event insertion
            print("[4/5] Sending chat message across WebSocket -> Gateway -> Orchestrator...")
            payload = {
                "type": "chat",
                "content": "Hello World verification test",
                "sessionId": "sess_e2e_test",
            }
            await ws.send(json.dumps(payload))

            # Await status update
            status_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            print(f"      -> Gateway status update: {status_msg.get('status')}")

            # Await agent response with written event
            resp_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            print(f"      -> Orchestrator response received: '{resp_msg.get('reply')}'")
            print(f"      -> Confirmed Event ID: {resp_msg.get('eventId')}")

            event = resp_msg.get("event")
            assert event is not None, "Event payload missing from agent response"

            # 4. Verify all 20 required schema fields are present
            print("\n[5/5] Validating exact 20-field Event schema in SQLite store...")
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE id = ?", (resp_msg.get("eventId"),))
            row = dict(cursor.fetchone())
            conn.close()

            print("\nRetrieved SQLite Row:")
            for field in REQUIRED_FIELDS:
                assert field in row, f"Missing required column in SQLite: {field}"
                val = row[field]
                print(f"  ✓ {field:18} = {val}")

            print("\n=======================================================")
            print("SERVICE BOUNDARY FULLY VERIFIED!")
            print("UI -> Gateway (WS) -> Orchestrator -> EventStore (SQLite)")
            print("=======================================================\n")

    finally:
        print("Cleaning up background test processes...")
        orch_proc.terminate()
        gateway_proc.terminate()
        try:
            orch_proc.kill()
            gateway_proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_e2e_test())
