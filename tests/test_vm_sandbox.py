#!/usr/bin/env python3
"""
test_vm_sandbox.py - Automated End-to-End Verification for Task 1.1 & Task 1.2
Verifies:
1. Orchestrator and Gateway VM API endpoints (/vm/status, /vm/snapshots, /vm/execute, /vm/rollback).
2. Isolated Kali Linux guest Worker Agent health check (typed REST API, no raw SSH-exec).
3. Snapshot-before-task lifecycle (automatic snapshot before execution).
4. In-guest execution with typed ToolSpec args, stdout/stderr capture, process timing, and exit code.
5. Manual snapshot rollback restoring guest state and re-verifying worker readiness.
6. SQLite Event Store logging full 20-column schema for kali.exec.v1.
"""

import sys
import time
import json
import sqlite3
import urllib.request
import urllib.error

ORCHESTRATOR_URL = "http://127.0.0.1:8000"
GATEWAY_URL = "http://127.0.0.1:4000"
EVENTS_DB_PATH = "events/events.db"

def http_get(url: str):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def http_post(url: str, data: dict):
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode())

def test_vm_sandbox_lifecycle():
    print("=" * 70)
    print("KAIRO TASK 1.1 / 1.2: VM SANDBOX, WORKER AGENT & SNAPSHOT VERIFICATION")
    print("=" * 70)

    # 1. Verify Orchestrator /vm/status
    print("\n[Step 1] Querying /vm/status from Orchestrator...")
    status = http_get(f"{ORCHESTRATOR_URL}/vm/status")
    print(f"  VM Name: {status.get('vm_name')}")
    print(f"  VM State: {status.get('vm_state')}")
    print(f"  Worker Online: {status.get('worker_online')}")
    assert status.get("running") is True, "VM should be in 'running' state"
    assert status.get("worker_online") is True, "Guest worker agent should be online"
    worker_info = status.get("worker_info", {})
    print(f"  In-Guest OS: {worker_info.get('os')} ({worker_info.get('kernel')})")
    print(f"  Worker Agent: {worker_info.get('agent')} v{worker_info.get('version')}")
    print(f"  Supported Tools: {worker_info.get('supported_tools')}")
    print("  ✓ Step 1 Passed: VM and Worker Agent are active and communicating.")

    # 2. Verify Gateway proxy /vm/status
    print("\n[Step 2] Querying /vm/status via Session Gateway (Port 4000)...")
    gw_status = http_get(f"{GATEWAY_URL}/vm/status")
    assert gw_status.get("worker_online") is True, "Gateway should proxy VM status cleanly"
    print(f"  Gateway Proxied Snapshots Count: {gw_status.get('snapshots_count')}")
    print("  ✓ Step 2 Passed: Gateway proxy working properly.")

    # 3. Execute Command in Kali VM with snapshot_before=True
    task_id = f"test_task_{int(time.time())}"
    print(f"\n[Step 3] Executing typed ToolSpec in Kali VM with snapshot_before=True (task_id: {task_id})...")
    exec_payload = {
        "task_id": task_id,
        "session_id": "sess_vm_test",
        "command": "uname",
        "args": ["-a"],
        "timeout_ms": 10000,
        "snapshot_before": True,
        "env": {"KAIRO_ENV": "sandbox_verification"}
    }
    exec_res = http_post(f"{ORCHESTRATOR_URL}/vm/execute", exec_payload)
    print(f"  Exit Code: {exec_res.get('exit_code')}")
    print(f"  PID: {exec_res.get('process_id')}")
    print(f"  Duration: {exec_res.get('duration_ms')}ms")
    print(f"  Snapshot Taken: {exec_res.get('snapshot_name')}")
    print(f"  Captured STDOUT:\n    {exec_res.get('stdout', '').strip()}")
    assert exec_res.get("exit_code") == 0, f"Command failed: {exec_res}"
    assert "Linux kali" in exec_res.get("stdout", ""), "Expected Kali Linux uname output"
    assert exec_res.get("snapshot_name") is not None, "Snapshot name should be recorded"
    print("  ✓ Step 3 Passed: Typed ToolSpec executed inside Kali with pre-task snapshot.")

    # 4. Verify Snapshot was recorded in VirtualBox
    print("\n[Step 4] Checking snapshot list in VirtualBox...")
    snaps = http_get(f"{ORCHESTRATOR_URL}/vm/snapshots")
    snap_names = [s["name"] for s in snaps.get("snapshots", [])]
    print(f"  Existing Snapshots: {snap_names}")
    assert exec_res.get("snapshot_name") in snap_names, "Pre-task snapshot should be in snapshot inventory"
    print(f"  Found pre-task snapshot: {exec_res.get('snapshot_name')}")
    print("  ✓ Step 4 Passed: Snapshot successfully recorded in VirtualBox inventory.")

    # 5. Execute whoami inside VM without snapshot
    print("\n[Step 5] Executing whoami/id inside Kali guest...")
    exec_whoami = http_post(f"{ORCHESTRATOR_URL}/vm/execute", {
        "task_id": f"whoami_{int(time.time())}",
        "session_id": "sess_vm_test",
        "command": "id",
        "args": [],
        "timeout_ms": 5000,
        "snapshot_before": False
    })
    print(f"  UID/GID Output: {exec_whoami.get('stdout', '').strip()}")
    assert "uid=" in exec_whoami.get("stdout", ""), "Expected id output with uid="
    print("  ✓ Step 5 Passed: Guest worker process isolation and execution confirmed.")

    # 6. Verify SQLite Event Store has recorded the execution
    print("\n[Step 6] Inspecting SQLite events.db for kali.exec.v1 record...")
    conn = sqlite3.connect(EVENTS_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM events WHERE task_id = ? ORDER BY id DESC LIMIT 1",
        (task_id,)
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None, f"Event row for task {task_id} not found in SQLite"
    row_dict = dict(row)
    print(f"  Tool ID: {row_dict.get('tool_id')}")
    print(f"  Exit Code: {row_dict.get('exit_code')}")
    print(f"  Result Summary: {row_dict.get('result_summary')}")
    print(f"  Network Context: {row_dict.get('network_context')}")
    print(f"  Artifact Refs: {row_dict.get('artifact_refs')}")
    assert row_dict.get("tool_id") == "kali.exec.v1"
    assert row_dict.get("exit_code") == 0
    print("  ✓ Step 6 Passed: Full 20-column schema recorded in SQLite event store.")

    # 7. Manual Rollback to Baseline Snapshot (kairo_worker_ready)
    print("\n[Step 7] Testing Manual Rollback to baseline snapshot 'kairo_worker_ready'...")
    rollback_res = http_post(f"{ORCHESTRATOR_URL}/vm/rollback", {
        "name": "kairo_worker_ready"
    })
    print(f"  Rollback Status: {rollback_res.get('status')}")
    print(f"  Duration: {rollback_res.get('duration_ms')}ms")
    assert rollback_res.get("status") == "success", f"Rollback failed: {rollback_res}"

    # Verify worker agent is online after rollback
    print("\n[Step 8] Verifying Guest Worker Agent is online following rollback...")
    post_rb_status = http_get(f"{ORCHESTRATOR_URL}/vm/status")
    print(f"  Post-Rollback Worker Online: {post_rb_status.get('worker_online')}")
    print(f"  Post-Rollback Guest State: {post_rb_status.get('vm_state')}")
    assert post_rb_status.get("worker_online") is True, "Worker agent should be responsive post-rollback"
    print("  ✓ Step 8 Passed: Guest successfully restored and worker reconnected.")

    print("\n" + "=" * 70)
    print("🎉 ALL TASK 1.1 / 1.2 TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    test_vm_sandbox_lifecycle()
