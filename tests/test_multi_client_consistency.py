#!/usr/bin/env python3
"""
test_multi_client_consistency.py - End-to-End Multi-Client Consistency Test

Validates the user requirement:
"open the same project from a Linux desktop, a Windows desktop (via WSL2),
 and a phone browser connected to your self-hosted backend, and see consistent state across all three."

Test Topology:
- Linux Desktop client (Session Gateway WS with clientType: "linux-desktop")
- Windows Desktop / WSL2 client (Session Gateway WS with clientType: "windows-desktop")
- Phone Browser client (Session Gateway WS with clientType: "browser-mobile")

All 3 clients connect to the self-hosted Session Gateway (port 4000) backed by the Orchestrator (port 8000).
They attach to the same project workspace and observe real-time synchronized state:
1. Shared Workspace provisioning and binding
2. Tool execution broadcasts (Kali VM & host tools)
3. Terminal output streaming across all viewports
4. VM snapshot state synchronized across all 3 viewports
5. Workspace lifecycle termination reflected across all 3 viewports
"""

import sys
import json
import asyncio
import websockets

GATEWAY_WS = "ws://localhost:4000"

async def receive_until(ws, target_types, timeout=30.0):
    """Wait and collect messages until a message with one of the target_types is received."""
    start = asyncio.get_event_loop().time()
    collected = []
    while asyncio.get_event_loop().time() - start < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout - (asyncio.get_event_loop().time() - start))
            msg = json.loads(raw)
            collected.append(msg)
            if msg.get("type") in target_types:
                return msg, collected
        except asyncio.TimeoutError:
            break
    raise TimeoutError(f"Timed out waiting for message type in {target_types}. Collected: {[m.get('type') for m in collected]}")

async def main():
    print("=" * 75)
    print("  KAIRO: MULTI-CLIENT CROSS-DEVICE STATE CONSISTENCY TEST")
    print("  Clients: Linux Desktop + Windows Desktop (WSL2) + Phone Browser")
    print("=" * 75)

    # 1. Establish 3 concurrent connections representing 3 distinct platforms
    print("\n[Step 1] Connecting 3 concurrent clients to self-hosted Session Gateway...")
    ws_linux = await websockets.connect(f"{GATEWAY_WS}?clientType=linux-desktop")
    ws_windows = await websockets.connect(f"{GATEWAY_WS}?clientType=windows-desktop")
    ws_mobile = await websockets.connect(f"{GATEWAY_WS}?clientType=browser-mobile")

    # Read handshakes
    hs_linux = json.loads(await ws_linux.recv())
    hs_windows = json.loads(await ws_windows.recv())
    hs_mobile = json.loads(await ws_mobile.recv())

    assert hs_linux["clientType"] == "linux-desktop", f"Unexpected clientType {hs_linux}"
    assert hs_windows["clientType"] == "windows-desktop", f"Unexpected clientType {hs_windows}"
    assert hs_mobile["clientType"] == "browser-mobile", f"Unexpected clientType {hs_mobile}"

    print(f"  ✓ Linux Desktop connected:   Session {hs_linux['sessionId']}")
    print(f"  ✓ Windows (WSL2) connected:  Session {hs_windows['sessionId']}")
    print(f"  ✓ Phone Browser connected:   Session {hs_mobile['sessionId']}")

    # 2. Linux client provisions a shared project workspace
    print("\n[Step 2] Linux Desktop provisions shared disposable project workspace...")
    project_name = "kairo-shared-multidevice-project"
    await ws_linux.send(json.dumps({
        "type": "provision_workspace",
        "projectName": project_name,
        "sessionId": hs_linux["sessionId"],
    }))

    # Verify all 3 clients receive workspace_provisioned
    wp_linux, _ = await receive_until(ws_linux, ["workspace_provisioned"])
    wp_windows, _ = await receive_until(ws_windows, ["workspace_provisioned"])
    wp_mobile, _ = await receive_until(ws_mobile, ["workspace_provisioned"])

    wid_linux = wp_linux["workspace"]["workspace_id"]
    wid_windows = wp_windows["workspace"]["workspace_id"]
    wid_mobile = wp_mobile["workspace"]["workspace_id"]

    assert wid_linux == wid_windows == wid_mobile, "Workspace ID mismatch across clients!"
    print(f"  ✓ Consistent Workspace ID broadcast to all 3 clients: {wid_linux}")
    print(f"    - Guest path: {wp_linux['workspace']['guest_dir']}")
    print(f"    - Host path:  {wp_linux['workspace']['host_dir']}")

    # 3. Windows WSL2 and Phone Browser join the shared workspace
    print("\n[Step 3] Windows Desktop and Phone Browser bind to the shared workspace...")
    await ws_windows.send(json.dumps({
        "type": "join_workspace",
        "workspaceId": wid_linux,
    }))
    wj_windows, _ = await receive_until(ws_windows, ["workspace_joined"])
    assert wj_windows["workspace"]["workspace_id"] == wid_linux

    # Linux client should receive peer_joined notification for Windows
    peer_win, _ = await receive_until(ws_linux, ["peer_joined"])
    print(f"  ✓ Linux Desktop received peer join alert: {peer_win['clientType']} joined")

    await ws_mobile.send(json.dumps({
        "type": "join_workspace",
        "workspaceId": wid_linux,
    }))
    wj_mobile, _ = await receive_until(ws_mobile, ["workspace_joined"])
    assert wj_mobile["workspace"]["workspace_id"] == wid_linux

    # Both Linux and Windows should receive peer_joined for Mobile
    peer_mob_l, _ = await receive_until(ws_linux, ["peer_joined"])
    peer_mob_w, _ = await receive_until(ws_windows, ["peer_joined"])
    print(f"  ✓ Linux & Windows received peer join alert: {peer_mob_l['clientType']} joined")

    # 4. Windows Desktop executes a Kali VM command (uname -a)
    print("\n[Step 4] Windows Desktop issues Kali VM execution ('uname -a')...")
    kali_task_id = "task_sync_kali_001"
    await ws_windows.send(json.dumps({
        "type": "kali_exec",
        "command": "uname",
        "args": ["-a"],
        "taskId": kali_task_id,
        "workspace_id": wid_linux,
    }))

    # Verify all 3 clients receive:
    # a) user_message_broadcast
    # b) status update
    # c) agent_response with exit_code 0
    print("  -> Verifying user_message_broadcast on all 3 clients...")
    umb_l, _ = await receive_until(ws_linux, ["user_message_broadcast"])
    umb_w, _ = await receive_until(ws_windows, ["user_message_broadcast"])
    umb_m, _ = await receive_until(ws_mobile, ["user_message_broadcast"])

    assert umb_l["taskId"] == kali_task_id
    assert umb_w["taskId"] == kali_task_id
    assert umb_m["taskId"] == kali_task_id
    print("  ✓ User command broadcast verified across Linux, Windows, and Phone Browser.")

    print("  -> Verifying agent_response completion on all 3 clients...")
    resp_l, _ = await receive_until(ws_linux, ["agent_response"])
    resp_w, _ = await receive_until(ws_windows, ["agent_response"])
    resp_m, _ = await receive_until(ws_mobile, ["agent_response"])

    assert resp_l["execution"]["exit_code"] == 0
    assert resp_w["execution"]["exit_code"] == 0
    assert resp_m["execution"]["exit_code"] == 0
    assert "Linux" in resp_l["execution"]["output"]
    print(f"  ✓ Consistent Kali VM execution output across all 3 viewports: {resp_l['execution']['output'].strip()}")

    # 5. Phone Browser issues a host tool call
    print("\n[Step 5] Phone Browser issues tool call ('shell.run.v1 python')...")
    shell_task_id = "task_sync_phone_002"
    expected_token = "KAIRO_TRI_DEVICE_SYNC_VERIFIED_OK"
    await ws_mobile.send(json.dumps({
        "type": "tool_call",
        "tool": "shell.run.v1",
        "args": {
            "command": "python",
            "args": ["-c", f"print('{expected_token}')"],
        },
        "taskId": shell_task_id,
        "workspace_id": wid_linux,
    }))

    # Verify user_message_broadcast and agent_response across Linux and Windows
    umb2_l, _ = await receive_until(ws_linux, ["user_message_broadcast"])
    umb2_w, _ = await receive_until(ws_windows, ["user_message_broadcast"])
    umb2_m, _ = await receive_until(ws_mobile, ["user_message_broadcast"])
    print("  ✓ Phone Browser action broadcasted to Linux Desktop and Windows Desktop.")

    resp2_l, _ = await receive_until(ws_linux, ["agent_response"])
    resp2_w, _ = await receive_until(ws_windows, ["agent_response"])
    resp2_m, _ = await receive_until(ws_mobile, ["agent_response"])

    out_l = resp2_l["execution"].get("output") or resp2_l["execution"].get("stdout") or resp2_l.get("reply", "")
    out_w = resp2_w["execution"].get("output") or resp2_w["execution"].get("stdout") or resp2_w.get("reply", "")
    out_m = resp2_m["execution"].get("output") or resp2_m["execution"].get("stdout") or resp2_m.get("reply", "")

    assert expected_token in out_l
    assert expected_token in out_w
    assert expected_token in out_m
    print("  ✓ Output state verified identical across all 3 clients.")

    # 6. Linux Desktop triggers VM snapshot
    print("\n[Step 6] Linux Desktop captures VM snapshot of project workspace state...")
    snap_name = "snap_multiclient_sync"
    await ws_linux.send(json.dumps({
        "type": "vm_snapshot",
        "name": snap_name,
        "description": "Cross-device verified snapshot",
    }))

    sn_l, _ = await receive_until(ws_linux, ["vm_snapshot_result"])
    sn_w, _ = await receive_until(ws_windows, ["vm_snapshot_result"])
    sn_m, _ = await receive_until(ws_mobile, ["vm_snapshot_result"])

    assert (sn_l["data"].get("name") or sn_l["data"].get("snapshot_name")) == snap_name
    assert (sn_w["data"].get("name") or sn_w["data"].get("snapshot_name")) == snap_name
    assert (sn_m["data"].get("name") or sn_m["data"].get("snapshot_name")) == snap_name
    print(f"  ✓ Snapshot '{snap_name}' confirmed synchronized on Linux, Windows, and Phone Browser.")

    # 7. Phone Browser terminates the project workspace
    print("\n[Step 7] Phone Browser terminates the shared project workspace...")
    await ws_mobile.send(json.dumps({
        "type": "terminate_workspace",
        "workspaceId": wid_linux,
    }))

    term_l, _ = await receive_until(ws_linux, ["workspace_terminated"])
    term_w, _ = await receive_until(ws_windows, ["workspace_terminated"])
    term_m, _ = await receive_until(ws_mobile, ["workspace_terminated"])

    assert term_l["workspaceId"] == wid_linux
    assert term_w["workspaceId"] == wid_linux
    assert term_m["workspaceId"] == wid_linux
    print("  ✓ Workspace termination & cleanup broadcast to all 3 clients.")

    # Clean up sockets
    await ws_linux.close()
    await ws_windows.close()
    await ws_mobile.close()

    print("\n" + "=" * 75)
    print("  ALL 7 MULTI-CLIENT CONSISTENCY CHECKS PASSED SUCCESSFULLY!")
    print("  Consistent state verified across Linux Desktop, Windows (WSL2), & Phone Browser.")
    print("=" * 75)

if __name__ == "__main__":
    asyncio.run(main())
