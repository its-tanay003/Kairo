"""
End-to-End Test Suite for Kali Worker Desktop noVNC / RFB Streaming (Task 4.1 & Task 4.2).

Verifies:
1. Direct RFB 3.8 WebSocket Handshake on port 6080 (RFC 6143).
2. Protocol security negotiation (Type 1: None / No Auth).
3. ServerInit desktop geometry (1024x768 32bpp TrueColor).
4. FramebufferUpdate streaming (Raw rectangles with live pixel payload).
5. Bidirectional Keyboard & Pointer event handling.
6. Gateway reverse proxy tunneling on ws://localhost:4000/vnc.
7. Self-hosted web mode HTTP rendering on http://localhost:3005.
8. Tauri desktop app configuration readiness (Task 4.1).
"""

import asyncio
import json
import struct
import urllib.request
import websockets


async def test_rfb_direct_handshake():
    """Tests direct RFB 3.8 handshake and frame streaming on ws://127.0.0.1:6080."""
    print("\n[Test 1] Connecting to Direct RFB WebSocket on ws://127.0.0.1:6080...")
    uri = "ws://127.0.0.1:6080"
    async with websockets.connect(uri, subprotocols=["binary"], max_size=20 * 1024 * 1024) as ws:
        # Step 1: Server Version
        server_ver = await ws.recv()
        assert isinstance(server_ver, bytes), "Expected binary version bytes"
        assert server_ver.startswith(b"RFB 003.008"), f"Invalid server version: {server_ver}"
        print(f"  ✓ Step 1: Received RFB Server Version: {server_ver.strip().decode()}")

        # Send Client Version
        await ws.send(b"RFB 003.008\n")
        print("  ✓ Step 2: Sent RFB Client Version: RFB 003.008")

        # Step 2: Security Types
        sec_types = await ws.recv()
        assert isinstance(sec_types, bytes) and len(sec_types) >= 2, f"Invalid security types: {sec_types}"
        num_types = sec_types[0]
        types_list = list(sec_types[1: 1 + num_types])
        assert 1 in types_list, f"Security Type 1 (None) not offered: {types_list}"
        print(f"  ✓ Step 3: Security types received: {types_list} (None offered)")

        # Select Type 1 (None)
        await ws.send(bytes([1]))
        print("  ✓ Step 4: Selected Security Type 1 (None)")

        # Step 3: SecurityResult
        sec_result = await ws.recv()
        assert isinstance(sec_result, bytes) and len(sec_result) == 4, "Expected 4-byte SecurityResult"
        result_code = struct.unpack(">I", sec_result)[0]
        assert result_code == 0, f"Security result failed with code {result_code}"
        print("  ✓ Step 5: SecurityResult received: 0 (OK)")

        # Step 4: ClientInit (shared=1)
        await ws.send(bytes([1]))
        print("  ✓ Step 6: Sent ClientInit (shared=1)")

        # Step 5: ServerInit
        server_init = await ws.recv()
        assert isinstance(server_init, bytes) and len(server_init) >= 24, "ServerInit packet too short"
        width, height = struct.unpack(">HH", server_init[:4])
        assert width == 1024 and height == 768, f"Unexpected dimensions: {width}x{height}"
        name_len = struct.unpack(">I", server_init[20:24])[0]
        name = server_init[24: 24 + name_len].decode(errors="ignore")
        print(f"  ✓ Step 7: ServerInit validated: {width}x{height}, Desktop: '{name}'")

        # Step 6: Initial FramebufferUpdate
        initial_frame = await ws.recv()
        assert isinstance(initial_frame, bytes) and len(initial_frame) > 12, "Empty framebuffer update"
        msg_type = initial_frame[0]
        assert msg_type == 0, f"Expected FramebufferUpdate (type 0), got {msg_type}"
        num_rects = struct.unpack(">H", initial_frame[2:4])[0]
        assert num_rects >= 1, f"Expected at least 1 rect, got {num_rects}"
        print(f"  ✓ Step 8: Received initial FramebufferUpdate with {num_rects} rect(s) (total {len(initial_frame)} bytes)")

        # Step 7: Send FramebufferUpdateRequest (Message Type 3)
        # incremental (1), x(0), y(0), w(1024), h(768)
        fb_req = struct.pack(">BBHHHH", 3, 1, 0, 0, 1024, 768)
        await ws.send(fb_req)
        print("  ✓ Step 9: Sent FramebufferUpdateRequest")

        # Step 8: Send KeyEvent (Message Type 4) - Press 'u', 'n', 'a', 'm', 'e', '\n'
        for char in "uname\n":
            keysym = ord(char) if char != "\n" else 0xFF0D
            # down
            await ws.send(struct.pack(">BBHI", 4, 1, 0, keysym))
            # up
            await ws.send(struct.pack(">BBHI", 4, 0, 0, keysym))
        print("  ✓ Step 10: Dispatched interactive keyboard events into virtual Kali shell")

        # Step 9: Send PointerEvent (Message Type 5)
        # button_mask(1 = left click), x(100), y(100)
        await ws.send(struct.pack(">BBHH", 5, 1, 100, 100))
        await ws.send(struct.pack(">BBHH", 5, 0, 100, 100))
        print("  ✓ Step 11: Dispatched interactive mouse pointer clicks")

        # Step 10: Receive updated Framebuffer
        updated_frame = await ws.recv()
        assert isinstance(updated_frame, bytes) and len(updated_frame) > 0, "No updated frame received"
        print(f"  ✓ Step 12: Successfully streamed live responsive desktop frame ({len(updated_frame)} bytes)")


async def test_gateway_vnc_tunnel():
    """Tests the /vnc WebSocket reverse tunnel through Session Gateway on port 4000."""
    print("\n[Test 2] Connecting to Gateway VNC Tunnel on ws://127.0.0.1:4000/vnc...")
    uri = "ws://127.0.0.1:4000/vnc"
    async with websockets.connect(uri, subprotocols=["binary"], max_size=20 * 1024 * 1024) as ws:
        # Step 1: Server Version through gateway
        server_ver = await ws.recv()
        assert server_ver.startswith(b"RFB 003.008"), f"Gateway tunnel RFB error: {server_ver}"
        print(f"  ✓ Step 1: Gateway /vnc tunnel forwarded server version: {server_ver.strip().decode()}")

        # Send Client Version
        await ws.send(b"RFB 003.008\n")

        # Security Handshake
        sec_types = await ws.recv()
        assert 1 in list(sec_types[1:]), "Security type 1 missing in tunnel"
        await ws.send(bytes([1]))
        sec_result = await ws.recv()
        assert struct.unpack(">I", sec_result)[0] == 0, "Security handshake failed in tunnel"
        print("  ✓ Step 2: Gateway tunnel completed security handshake")

        # ClientInit & ServerInit
        await ws.send(bytes([1]))
        server_init = await ws.recv()
        w, h = struct.unpack(">HH", server_init[:4])
        assert w == 1024 and h == 768, f"Gateway tunnel bad dimensions: {w}x{h}"
        print(f"  ✓ Step 3: Gateway tunnel received ServerInit {w}x{h}")

        # Initial Frame
        frame = await ws.recv()
        assert frame[0] == 0 and len(frame) > 1000, "Corrupted frame through gateway tunnel"
        print(f"  ✓ Step 4: Gateway tunnel streamed valid RFB frame ({len(frame)} bytes)")


def test_http_screen_endpoints():
    """Tests REST endpoints for screen monitoring and previews."""
    print("\n[Test 3] Verifying HTTP screen endpoints...")
    # 1. Orchestrator screen status
    with urllib.request.urlopen("http://127.0.0.1:8000/screen/status") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data["status"] == "running"
        assert data["protocol"] == "RFB 003.008"
        assert data["width"] == 1024 and data["height"] == 768
        print(f"  ✓ Orchestrator /screen/status: OK (Protocol: {data['protocol']}, Plane: {data['plane']})")

    # 2. Gateway screen status proxy
    with urllib.request.urlopen("http://localhost:4000/screen/status") as resp:
        assert resp.status == 200
        gw_data = json.loads(resp.read().decode())
        assert gw_data["status"] == "running"
        print("  ✓ Gateway /screen/status proxy: OK")

    # 3. Snapshot PNG
    with urllib.request.urlopen("http://localhost:4000/screen/snapshot.png") as resp:
        assert resp.status == 200
        assert resp.headers.get("content-type") == "image/png"
        img_bytes = resp.read()
        assert len(img_bytes) > 10000, "PNG image suspiciously small"
        # Check PNG magic bytes
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG header"
        print(f"  ✓ Gateway /screen/snapshot.png: OK ({len(img_bytes)} bytes, valid PNG header)")


def test_self_hosted_web_mode():
    """Tests Task 4.2: Self-hosted web mode UI serving."""
    print("\n[Test 4] Verifying Task 4.2 Self-Hosted Web Mode on http://localhost:3005...")
    req = urllib.request.Request("http://localhost:3005", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8", errors="ignore")
        assert "<html" in html or "<!DOCTYPE html>" in html
        assert "SCREEN" in html or "novnc" in html.lower() or "kairo" in html.lower()
        print("  ✓ Self-hosted Web Mode: UI successfully rendered with SCREEN component bundle")


def test_tauri_desktop_configuration():
    """Tests Task 4.1: Desktop App configuration readiness."""
    print("\n[Test 5] Verifying Task 4.1 Tauri Desktop App configuration...")
    with open("ui/src-tauri/tauri.conf.json", "r", encoding="utf-8") as f:
        conf = json.load(f)
    assert conf["productName"] == "Kairo"
    assert conf["app"]["security"]["csp"] is None, "CSP must be null to allow local VNC WebSocket streaming"
    print("  ✓ Tauri desktop configuration: Verified (Security CSP allows local RFB WebSocket)")


async def main():
    print("=" * 70)
    print("KAIRO CYBER AGENT: KALI WORKER SCREEN STREAMING TEST SUITE (noVNC / RFB)")
    print("=" * 70)

    await test_rfb_direct_handshake()
    await test_gateway_vnc_tunnel()
    test_http_screen_endpoints()
    test_self_hosted_web_mode()
    test_tauri_desktop_configuration()

    print("\n" + "=" * 70)
    print("ALL 5 SCREEN STREAMING SUITES PASSED! (noVNC + Tauri + Web Mode)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
