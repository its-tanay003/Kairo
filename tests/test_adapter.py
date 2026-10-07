"""
Comprehensive verification test for adapter shell.run.v1:
1. Tool validation against ToolSpec schema
2. Process supervisor execution with stdout/stderr capture
3. Hard timeout enforcement
4. Kill switch endpoint via SIGKILL by task_id
5. Exact 20-field event table recording in SQLite
"""

import asyncio
import json
import sqlite3
import time
import urllib.request
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


async def run_adapter_tests():
    print("\n=======================================================")
    print("TESTING ADAPTER shell.run.v1 & PROCESS SUPERVISOR")
    print("=======================================================\n")

    uri = "ws://127.0.0.1:4000/?sessionId=adapter_test_sess"
    async with websockets.connect(uri) as ws:
        # Handshake
        handshake = json.loads(await ws.recv())
        print(f"[1/5] Connected to Gateway: {handshake.get('sessionId')}")

        # Test 1: Invalid Tool Call (Schema Validation rejection)
        print("\n[2/5] Testing Gateway Schema Validation (Invalid Arguments)...")
        invalid_payload = {
            "type": "tool_call",
            "tool": "shell.run.v1",
            "args": {"command": "", "args": "not-an-array"},  # Invalid
            "sessionId": "adapter_test_sess",
        }
        await ws.send(json.dumps(invalid_payload))
        val_err = json.loads(await ws.recv())
        print(f"      -> Gateway rejected invalid tool call: {val_err.get('error')}")
        assert val_err.get("type") == "validation_error"
        assert "command" in val_err.get("error")

        # Test 2: Valid Execution of shell.run.v1
        print("\n[3/5] Testing Valid Execution of shell.run.v1 adapter...")
        valid_payload = {
            "type": "tool_call",
            "tool": "shell.run.v1",
            "args": {
                "command": "python",
                "args": ["-c", "import sys; print('STDOUT: Hello from shell.run.v1'); sys.stderr.write('STDERR: diagnostic notice\\n')"],
                "timeout_ms": 5000,
            },
            "sessionId": "adapter_test_sess",
            "taskId": "task_shell_valid_1",
        }
        await ws.send(json.dumps(valid_payload))

        status_msg = json.loads(await ws.recv())
        print(f"      -> Gateway status: {status_msg.get('status')}")

        resp_msg = json.loads(await ws.recv())
        print(f"      -> Execution reply: '{resp_msg.get('reply')}'")
        exec_info = resp_msg.get("execution")
        assert exec_info is not None, "Execution details missing"
        print(f"      -> Exit Code: {exec_info.get('exit_code')}")
        print(f"      -> Process ID: {exec_info.get('process_id')}")
        print(f"      -> Captured STDOUT: {repr(exec_info.get('stdout').strip())}")
        print(f"      -> Captured STDERR: {repr(exec_info.get('stderr').strip())}")
        assert exec_info.get("exit_code") == 0
        assert "STDOUT: Hello from shell.run.v1" in exec_info.get("stdout")
        assert "STDERR: diagnostic notice" in exec_info.get("stderr")

        event_id_valid = resp_msg.get("eventId")

        # Test 3: Hard Timeout Enforcement
        print("\n[4/5] Testing Hard Timeout Enforcement on shell.run.v1...")
        timeout_payload = {
            "type": "tool_call",
            "tool": "shell.run.v1",
            "args": {
                "command": "python",
                "args": ["-c", "import time; time.sleep(10)"],
                "timeout_ms": 600,
            },
            "sessionId": "adapter_test_sess",
            "taskId": "task_shell_timeout_2",
        }
        await ws.send(json.dumps(timeout_payload))
        await ws.recv()  # Status message
        resp_timeout = json.loads(await ws.recv())
        exec_timeout = resp_timeout.get("execution")
        print(f"      -> Timed out: {exec_timeout.get('timed_out')}")
        print(f"      -> Exit Code: {exec_timeout.get('exit_code')}")
        print(f"      -> Stderr Notice: {repr(exec_timeout.get('stderr').strip())}")
        assert exec_timeout.get("timed_out") is True
        assert exec_timeout.get("exit_code") == 124

        # Test 4: Kill switch endpoint via SIGKILL by task_id
        print("\n[5/5] Testing Kill Switch (SIGKILL by task_id)...")
        # Launch background process via Orchestrator /run
        kill_task_id = f"task_kill_test_{int(time.time())}"
        
        async def trigger_long_task():
            req_data = json.dumps({
                "session_id": "adapter_test_sess",
                "message": "run background sleep",
                "task_id": kill_task_id,
                "explicit_tool": "shell.run.v1",
                "explicit_args": {
                    "command": "python",
                    "args": ["-c", "import time; time.sleep(30)"],
                    "timeout_ms": 30000,
                },
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8000/run",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: urllib.request.urlopen(req))

        bg_task = asyncio.create_task(trigger_long_task())
        await asyncio.sleep(0.5)

        # Check process is active in supervisor
        check_req = urllib.request.Request("http://127.0.0.1:8000/processes")
        with urllib.request.urlopen(check_req) as cr:
            active_procs = json.loads(cr.read().decode("utf-8"))["active_processes"]
            print(f"      -> Active processes before kill: {[p['task_id'] for p in active_procs]}")
            assert any(p["task_id"] == kill_task_id for p in active_procs)

        # Trigger Kill Switch via Gateway HTTP endpoint: POST http://127.0.0.1:4000/kill/:taskId
        kill_req = urllib.request.Request(
            f"http://127.0.0.1:4000/kill/{kill_task_id}",
            method="POST"
        )
        with urllib.request.urlopen(kill_req) as kr:
            kill_res = json.loads(kr.read().decode("utf-8"))
            print(f"      -> Kill Switch response: {kill_res}")
            assert kill_res.get("status") == "killed"
            assert kill_res.get("signal") == "SIGKILL"

        # Await completion of long task (which was killed)
        await bg_task

        # Verify SQLite event row for valid execution has all 20 fields
        print("\n--- Validating SQLite 20-field Event Row ---")
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE id = ?", (event_id_valid,))
        row = dict(cursor.fetchone())
        conn.close()

        for field in REQUIRED_FIELDS:
            assert field in row, f"Missing {field}"
            print(f"  ✓ {field:18} = {row[field]}")

    print("\n=======================================================")
    print("ALL ADAPTER & KILL SWITCH TESTS PASSED SUCCESSFULLY!")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(run_adapter_tests())
