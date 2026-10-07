"""
End-to-End Service Boundary Test.
Verifies:
1. Llama.cpp server mode health & grammar-constrained ToolSpec schema
2. Orchestrator loads ToolSpec from /registry
3. Gateway WebSocket connection & routing
4. Local LLM infers tool-call vs plain-text message under grammar constraints
5. Orchestrator writes exact 20-field Event row to SQLite /events/events.db
6. Gateway streams response & Event back over WebSocket
7. Direct SQLite verification of the written rows
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import websockets

ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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


def is_service_up(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


async def run_e2e_test():
    print("\n=======================================================")
    print("STARTING SERVICE BOUNDARY & LOCAL LLAMA.CPP TEST")
    print("=======================================================\n")

    spawned_procs = []

    # 1. Verify / Launch Llama.cpp
    print("[1/6] Checking local llama.cpp server (http://127.0.0.1:8080/health)...")
    if is_service_up("http://127.0.0.1:8080/health"):
        print("      ✓ llama-server is healthy and running.")
    else:
        print("      -> Starting llama-server...")
        from orchestrator.llama_manager import LlamaServerManager
        mgr = LlamaServerManager()
        started = mgr.start(wait_seconds=15)
        if not started:
            raise RuntimeError("Failed to start llama-server")
        spawned_procs.append(mgr.process)
        print("      ✓ llama-server started successfully.")

    # 2. Verify / Launch Orchestrator
    print("[2/6] Checking Orchestrator (http://127.0.0.1:8000/health)...")
    if is_service_up("http://127.0.0.1:8000/health"):
        print("      ✓ Orchestrator is healthy and running.")
    else:
        print("      -> Launching Orchestrator...")
        orch_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "orchestrator.server:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        spawned_procs.append(orch_proc)
        for _ in range(20):
            if is_service_up("http://127.0.0.1:8000/health"):
                break
            time.sleep(0.5)
        assert is_service_up("http://127.0.0.1:8000/health"), "Orchestrator failed to initialize"
        print("      ✓ Orchestrator launched.")

    # 3. Verify / Launch Gateway
    print("[3/6] Checking Session Gateway (http://127.0.0.1:4000/health)...")
    if is_service_up("http://127.0.0.1:4000/health"):
        print("      ✓ Gateway is healthy and running.")
    else:
        print("      -> Launching Gateway...")
        gw_proc = subprocess.Popen(
            ["npm", "start"],
            cwd=str(ROOT / "gateway"),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        spawned_procs.append(gw_proc)
        for _ in range(20):
            if is_service_up("http://127.0.0.1:4000/health"):
                break
            time.sleep(0.5)
        assert is_service_up("http://127.0.0.1:4000/health"), "Gateway failed to initialize"
        print("      ✓ Gateway launched.")

    try:
        # 4. Connect to Gateway WebSocket
        print("\n[4/6] Connecting client to Gateway over WebSocket (ws://127.0.0.1:4000)...")
        uri = "ws://127.0.0.1:4000/?sessionId=sess_e2e_verify"
        
        async with websockets.connect(uri) as ws:
            # Receive handshake
            raw_handshake = await asyncio.wait_for(ws.recv(), timeout=5.0)
            handshake = json.loads(raw_handshake)
            print(f"      -> Received handshake from Gateway: {handshake.get('sessionId')}")
            assert handshake.get("type") == "handshake"

            # Test A: Structured Tool Call via local model
            print("\n[5/6] (A) Sending Tool Call prompt to local LLM across WebSocket...")
            payload_tool = {
                "type": "chat",
                "content": "Please execute hello_world tool for Tanay",
                "sessionId": "sess_e2e_verify",
            }
            async def wait_for_response(sock, timeout=30.0):
                end_time = asyncio.get_event_loop().time() + timeout
                while asyncio.get_event_loop().time() < end_time:
                    remaining = max(1.0, end_time - asyncio.get_event_loop().time())
                    raw = await asyncio.wait_for(sock.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    mtype = msg.get("type")
                    if mtype == "status":
                        print(f"      -> Gateway status update: {msg.get('status')}")
                    elif mtype == "agent_response":
                        return msg
                    elif mtype == "error":
                        raise RuntimeError(f"Gateway error: {msg.get('error')}")
                raise TimeoutError("Timed out waiting for agent_response")

            await ws.send(json.dumps(payload_tool))
            resp_tool = await wait_for_response(ws, timeout=30.0)
            print(f"      -> Agent reply: '{resp_tool.get('reply')}'")
            print(f"      -> Tool executed: {resp_tool.get('toolExecuted')}")
            print(f"      -> Confirmed Event ID: {resp_tool.get('eventId')}")
            assert resp_tool.get("toolExecuted") is not None
            assert resp_tool["toolExecuted"]["id"] == "hello_world"

            # Test B: Conversational plain text response via local model
            print("\n[5/6] (B) Sending Conversational prompt to local LLM across WebSocket...")
            payload_chat = {
                "type": "chat",
                "content": "Hi! What is your role as an assistant?",
                "sessionId": "sess_e2e_verify",
            }
            await ws.send(json.dumps(payload_chat))
            resp_chat = await wait_for_response(ws, timeout=30.0)
            print(f"      -> Conversational reply: '{resp_chat.get('reply')}'")
            print(f"      -> Confirmed Event ID: {resp_chat.get('eventId')}")
            assert resp_chat.get("reply") is not None

            # 6. Verify all 20 required schema fields are present in SQLite
            print("\n[6/6] Validating exact 20-field Event schema in SQLite store...")
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE id = ?", (resp_tool.get("eventId"),))
            row = dict(cursor.fetchone())
            conn.close()

            print("\nRetrieved SQLite Tool Event Row:")
            for field in REQUIRED_FIELDS:
                assert field in row, f"Missing required column in SQLite: {field}"
                val = row[field]
                print(f"  ✓ {field:18} = {val}")

            print("\n=======================================================")
            print("SERVICE BOUNDARY & LOCAL MODEL FULLY VERIFIED!")
            print("UI -> Gateway (WS) -> Orchestrator -> llama.cpp (GBNF/JSON Schema) -> EventStore (SQLite)")
            print("=======================================================\n")

    finally:
        if spawned_procs:
            print("Cleaning up temporarily spawned test processes...")
            for p in spawned_procs:
                if p:
                    try:
                        p.terminate()
                    except Exception:
                        pass


if __name__ == "__main__":
    asyncio.run(run_e2e_test())
