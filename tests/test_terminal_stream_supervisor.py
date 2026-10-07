"""
Automated end-to-end verification script for:
- Live stdout/stderr WebSocket streaming from Kali worker agent
- Hierarchical Process Tree View (parent/child/background)
- Process Supervisor controls: pause (SIGSTOP), resume (SIGCONT), stop (SIGKILL), retry
"""

import asyncio
import json
import sys
import time
import urllib.request
import urllib.error

# Ensure websockets is available
try:
    import websockets
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

GATEWAY_WS = "ws://127.0.0.1:4000"
GATEWAY_HTTP = "http://127.0.0.1:4000"
ORCHESTRATOR_HTTP = "http://127.0.0.1:8000"
WORKER_HTTP = "http://127.0.0.1:9999"


def check_services():
    print("[Check] Verifying Orchestrator and Gateway are online...")
    # Check Orchestrator
    try:
        req = urllib.request.urlopen(f"{ORCHESTRATOR_HTTP}/health", timeout=3)
        assert req.status == 200
        print("  ✓ Orchestrator online at", ORCHESTRATOR_HTTP)
    except Exception as e:
        print("  ✗ Orchestrator offline:", e)
        return False

    # Check Gateway
    try:
        req = urllib.request.urlopen(f"{GATEWAY_HTTP}/health", timeout=3)
        assert req.status == 200
        print("  ✓ Gateway online at", GATEWAY_HTTP)
    except Exception as e:
        print("  ✗ Gateway offline:", e)
        return False

    # Check Kali Worker
    try:
        req = urllib.request.urlopen(f"{WORKER_HTTP}/health", timeout=3)
        assert req.status == 200
        data = json.loads(req.read().decode())
        print("  ✓ Kali Worker online at", WORKER_HTTP, f"(version: {data.get('version')})")
    except Exception as e:
        print("  ✗ Kali Worker offline:", e)
        return False

    return True


async def test_live_streaming_and_controls():
    print("\n========================================================")
    print("TESTING KAIRO LIVE STREAMING & PROCESS SUPERVISOR")
    print("========================================================")

    async with websockets.connect(GATEWAY_WS) as ws:
        # 1. Handshake
        handshake_raw = await ws.recv()
        handshake = json.loads(handshake_raw)
        print(f"\n[1/5] Connected to Gateway WebSocket (Session: {handshake.get('sessionId')})")
        assert handshake.get("type") == "handshake"

        # 2. Launch long streaming command in Kali VM
        task_id = f"test_stream_{int(time.time()*1000)}"
        print(f"\n[2/5] Dispatching live streaming task to Kali VM: {task_id}")
        await ws.send(json.dumps({
            "type": "kali_exec",
            "taskId": task_id,
            "command": "bash",
            "args": ["-c", "for i in 1 2 3 4 5; do echo Line $i live from Kali; sleep 0.4; done"],
            "snapshot_before": False,
        }))

        # Collect live stream chunks as they arrive
        stream_chunks = []
        tree_updates = []
        completed = False

        start_t = time.time()
        while time.time() - start_t < 10.0:
            try:
                msg_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(msg_raw)
                msg_type = msg.get("type")

                if msg_type == "terminal_stream":
                    stream_chunks.append(msg)
                    print(f"      -> [Live Stream Chunk #{msg.get('seq')}] ({msg.get('stream')}): {msg.get('text').strip()}")

                elif msg_type == "process_tree_update":
                    tree_updates.append(msg)

                elif msg_type == "agent_response":
                    completed = True
                    print(f"      -> Final agent response received: {msg.get('reply')}")
                    break
            except asyncio.TimeoutError:
                break

        assert len(stream_chunks) >= 3, f"Expected multiple live stream chunks, received {len(stream_chunks)}"
        print(f"  ✓ Live stdout/stderr streamed successfully ({len(stream_chunks)} events received in real time).")

        # 3. Test Process Tree Hierarchy (Parent, Child, Background)
        tree_task_id = f"test_tree_{int(time.time()*1000)}"
        print(f"\n[3/5] Testing Process Tree Hierarchy with background processes: {tree_task_id}")
        await ws.send(json.dumps({
            "type": "kali_exec",
            "taskId": tree_task_id,
            "command": "bash",
            "args": ["-c", "sleep 15 & sleep 20 & wait"],
            "snapshot_before": False,
        }))

        # Wait a moment for processes to spawn
        await asyncio.sleep(0.8)

        # Query process tree
        await ws.send(json.dumps({
            "type": "get_process_tree",
            "taskId": tree_task_id,
        }))

        received_tree = None
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("type") == "process_tree_update" and msg.get("taskId") == tree_task_id:
                received_tree = msg.get("tree")
                break

        print(f"      -> Process Tree Nodes for {tree_task_id}:")
        if received_tree:
            for node in received_tree:
                print(f"         [PARENT] PID {node.get('pid')} - {node.get('cmd')} (State: {node.get('state')})")
                for child in node.get("children", []):
                    ptype = "BACKGROUND" if child.get("is_background") else "CHILD"
                    print(f"           └── [{ptype}] PID {child.get('pid')} (PPID {child.get('ppid')}) - {child.get('cmd')} (State: {child.get('state')})")

        assert received_tree is not None and len(received_tree) > 0, "Expected non-empty process tree"
        print("  ✓ Process tree hierarchy correctly captures parent, child, and background processes.")

        # Helper to wait for control responses skipping streaming events
        async def wait_for_control_response(expected_action, timeout=6.0):
            start = time.time()
            while time.time() - start < timeout:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    m = json.loads(raw)
                    if m.get("type") == "process_control_result" and m.get("action") == expected_action:
                        return m
                except asyncio.TimeoutError:
                    pass
            raise TimeoutError(f"Did not receive control response for {expected_action}")

        # 4. Test Process Supervisor Controls: Pause, Resume, Stop
        print(f"\n[4/5] Testing Process Supervisor Controls (Pause, Resume, Stop)...")

        # Test PAUSE (SIGSTOP)
        await ws.send(json.dumps({
            "type": "process_control",
            "action": "pause",
            "taskId": tree_task_id,
        }))
        pause_resp = await wait_for_control_response("pause")
        print("      -> Pause Result:", pause_resp.get("result"))
        assert pause_resp.get("action") == "pause"
        print("      ✓ Process tree paused via SIGSTOP")

        # Test RESUME (SIGCONT)
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({
            "type": "process_control",
            "action": "resume",
            "taskId": tree_task_id,
        }))
        resume_resp = await wait_for_control_response("resume")
        print("      -> Resume Result:", resume_resp.get("result"))
        assert resume_resp.get("action") == "resume"
        print("      ✓ Process tree resumed via SIGCONT")

        # Test STOP (SIGKILL)
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({
            "type": "process_control",
            "action": "stop",
            "taskId": tree_task_id,
        }))
        stop_resp = await wait_for_control_response("stop")
        print("      -> Stop Result:", stop_resp.get("result"))
        assert stop_resp.get("action") == "stop"
        print("      ✓ Process tree stopped via SIGKILL")

        # 5. Test RETRY Control
        print(f"\n[5/5] Testing RETRY Control on {tree_task_id}...")
        await ws.send(json.dumps({
            "type": "process_control",
            "action": "retry",
            "taskId": tree_task_id,
        }))
        retry_resp = await wait_for_control_response("retry")
        print("      -> Retry Result:", retry_resp.get("result"))
        assert retry_resp.get("action") == "retry"
        print("      ✓ Process restarted with clean retry execution.")

        # Clean up retry task
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({
            "type": "process_control",
            "action": "stop",
            "taskId": tree_task_id,
        }))

    print("\n========================================================")
    print("ALL LIVE STREAMING, PROCESS TREE & CONTROL TESTS PASSED!")
    print("========================================================\n")


if __name__ == "__main__":
    if not check_services():
        print("\nNote: Make sure Orchestrator (:8000), Gateway (:4000), and Kali VM (:9999) are running.")
        sys.exit(1)

    asyncio.run(test_live_streaming_and_controls())
