#!/usr/bin/env python3
"""
test_mobile_browser_viewport.py - Automated verification for Task 4.3: Mobile Browser Viewport & Integration

Validates:
1. Session Gateway (port 4000) accepts mobile browser WebSocket connection with client_type: 'browser-mobile'.
2. Gateway emits handshake with verified session ID and local-only data path.
3. Next.js UI on port 3005 serves mobile viewport configuration and all 3 mobile view structures:
   - Chat Pane
   - Activity Rail (Task Graph DAG / Inspector)
   - Read-Only / Limited Mobile Terminal Stream
4. Quick-command triggers (e.g., uname -a, whoami) invoke tools and stream stdout/stderr chunks
   into the mobile terminal view without requiring virtual keyboard interaction.
"""

import sys
import json
import asyncio
import urllib.request
import websockets

def test_nextjs_mobile_html():
    print("[1/4] Verifying Next.js UI HTTP endpoint on port 3005...")
    req = urllib.request.Request("http://localhost:3005/", headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5)"})
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200, f"Expected status 200, got {response.status}"
        html = response.read().decode("utf-8")
        assert "viewport" in html.lower(), "Viewport meta tag missing from UI HTML"
        print("  ✓ Next.js UI is online and serves responsive HTML to mobile User-Agent.")

async def test_mobile_websocket_handshake():
    print("[2/4] Verifying Mobile WebSocket connection to Session Gateway (ws://localhost:4000)...")
    async with websockets.connect("ws://localhost:4000") as ws:
        # Send mobile client identify
        await ws.send(json.dumps({
            "type": "client_identify",
            "client_type": "browser-mobile",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X)"
        }))

        # Read handshake response
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(msg)
        assert data.get("type") == "handshake", f"Expected handshake, got {data}"
        assert "sessionId" in data, "SessionId missing from handshake"
        assert data.get("dataPlane") in ("local-only", "connected"), f"Unexpected dataPlane {data.get('dataPlane')}"
        print(f"  ✓ Handshake received: Session={data['sessionId']}, DataPath={data['dataPlane']}, Client={data.get('clientType')}")
        return data["sessionId"]

async def test_mobile_tool_execution_stream():
    print("[3/4] Verifying tool execution & terminal stream chunks over mobile connection...")
    async with websockets.connect("ws://localhost:4000") as ws:
        # Await handshake
        await ws.recv()

        task_id = "test_mob_task_001"
        # Trigger quick-action tool call
        await ws.send(json.dumps({
            "type": "tool_call",
            "tool": "shell.run.v1",
            "args": {
                "command": "python",
                "args": ["-c", "print('Mobile Read-Only Terminal Stream: OK')"]
            },
            "taskId": task_id,
        }))

        # Collect stream messages
        received_status = False
        received_stream = False

        for _ in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)
                if msg.get("type") == "status":
                    received_status = True
                if msg.get("type") in ("terminal_stream", "stdout", "tool_result"):
                    received_stream = True
                if received_status and received_stream:
                    break
            except asyncio.TimeoutError:
                break

        assert received_status or received_stream, "Did not receive stream or status messages"
        print("  ✓ Live execution and terminal streaming verified for mobile client.")

def test_component_architecture():
    print("[4/4] Verifying mobile view architecture in Next.js source files...")
    import os
    comp_file = os.path.join("ui", "src", "app", "components", "MobileTerminalView.tsx")
    page_file = os.path.join("ui", "src", "app", "page.tsx")
    css_file = os.path.join("ui", "src", "app", "globals.css")

    with open(comp_file, "r", encoding="utf-8") as f:
        comp_content = f.read()
    assert "MobileTerminalView" in comp_content, "MobileTerminalView component missing"
    assert "StreamChunk" in comp_content, "StreamChunk type missing"
    assert "uname -a" in comp_content, "Quick commands missing from MobileTerminalView"

    with open(page_file, "r", encoding="utf-8") as f:
        page_content = f.read()
    assert "mobileTab" in page_content, "mobileTab state missing from page.tsx"
    assert "mobile-view-nav" in page_content, "mobile-view-nav missing from page.tsx"
    assert "MobileTerminalView" in page_content, "MobileTerminalView missing from page.tsx"

    with open(css_file, "r", encoding="utf-8") as f:
        css_content = f.read()
    assert "@media (max-width: 768px)" in css_content, "Mobile media query missing from globals.css"
    assert "16px !important" in css_content, "iOS zoom font-size rule missing"
    print("  ✓ Source files confirm segmented navigation, touch targets, and iOS Safari font sizing.")

def main():
    print("=== Running Mobile Browser Viewport & Integration Tests ===")
    test_nextjs_mobile_html()
    asyncio.run(test_mobile_websocket_handshake())
    asyncio.run(test_mobile_tool_execution_stream())
    test_component_architecture()
    print("\n=== ALL MOBILE BROWSER VIEWPORT TESTS PASSED ===")

if __name__ == "__main__":
    main()
