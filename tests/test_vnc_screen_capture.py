"""
Test Suite for Real Screen Capture via VNC Server and Kali Worker in Kairo.

Verifies:
1. VncStreamerServer capture mechanisms:
   - Priority resolution (custom provider, RFB socket, in-guest Kali worker).
   - Live framebuffer update and _has_real_frame tracking.
   - Convenience helper capture_live_session().
2. In-guest Kali worker display capture (_capture_from_kali_worker):
   - scrot / xwd / import execution and base64 PNG decoding.
   - Proper refusal / fallback when connector is simulated mock or disconnected.
3. RFB 3.8 socket capture (_capture_from_vnc_socket):
   - Protocol negotiation (handshake, security, ServerInit, FramebufferUpdate).
   - Pixel decoding into PIL Image.
4. BaseGuiAdapter & Tier 3 Adapters (Burp, Wireshark, ZAP) Real vs Fallback:
   - When real GUI session is reachable:
     * Saves genuine screenshot without amber simulation banner.
     * Metadata has is_simulated=False, simulation_notice=None, capture_source="vnc_live".
     * Caption omits [SIMULATED] prefix.
     * UI state summary omits SIMULATION_NOTICE_TEXT.
     * execute() returns ToolObservation with is_simulated=False and clean stdout.
   - When no real GUI session is reachable:
     * Falls back to synthetic frame.
     * Burns amber warning banner and watermark pill.
     * Metadata has is_simulated=True, simulation_notice=SIMULATION_NOTICE_TEXT, capture_source="synthetic_fallback".
     * Caption prefixes [SIMULATED].
     * UI state summary and execute() stdout maintain honest labeling safety net.
5. Pointer and Keyboard event forwarding from bounded_click/bounded_type to VNC desktop.
"""

import base64
import io
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional
import pytest
from PIL import Image, ImageDraw

from events.db import init_db
from orchestrator.adapters.burpsuite_adapter import BurpSuiteGuiAdapter
from orchestrator.adapters.gui_base import BaseGuiAdapter
from orchestrator.adapters.wireshark_adapter import WiresharkGuiAdapter
from orchestrator.adapters.zap_adapter import ZapGuiAdapter
from orchestrator.evidence_store import EvidenceStore
from orchestrator.kali_connector import ExecutionPlaneInfo, ExecutionPlaneType, SIMULATION_NOTICE_TEXT
from orchestrator.vnc_server import (
    VncStreamerServer,
    _capture_from_kali_worker,
    _capture_from_vnc_socket,
    capture_live_session,
    vnc_server,
)


@pytest.fixture
def temp_gui_env(tmp_path):
    """Provides an isolated test environment with temporary SQLite DB and artifacts directory."""
    db_file = tmp_path / "test_gui_events.db"
    artifacts_dir = tmp_path / "test_gui_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_file)

    store = EvidenceStore(db_path=db_file, artifacts_dir=artifacts_dir)
    return {"db_path": db_file, "artifacts_dir": artifacts_dir, "store": store}


class MockKaliConnector:
    """Mock connector simulating live Kali worker plane."""

    def __init__(self, is_connected: bool = True, plane_type: ExecutionPlaneType = ExecutionPlaneType.LINUX_NATIVE, image_to_return: Optional[Image.Image] = None):
        self._is_connected = is_connected
        self._plane_type = plane_type
        self._image_to_return = image_to_return or Image.new("RGB", (800, 600), (40, 80, 120))

    def get_info(self) -> ExecutionPlaneInfo:
        return ExecutionPlaneInfo(
            platform="linux",
            plane_type=self._plane_type,
            backend_name="Mock Kali Container",
            is_connected=self._is_connected,
            host_os="Linux",
            host_arch="x86_64",
        )

    def execute(self, task_id: str, command: str, args: list, timeout_ms: int = 5000) -> Dict[str, Any]:
        if not self._is_connected:
            return {"status": "error", "error": "Worker disconnected"}
        buf = io.BytesIO()
        self._image_to_return.save(buf, format="PNG")
        b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "status": "success",
            "stdout": b64_str,
            "stderr": "",
            "exit_code": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Direct VNC Server & Capture Mechanisms Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestVncServerCaptureMechanisms:

    def test_custom_capture_provider_hook(self):
        """Verifies that a custom capture provider hook returns live frames and updates desktop."""
        server = VncStreamerServer()
        live_img = Image.new("RGB", (640, 480), (10, 200, 100))

        # Register provider hook
        server._custom_capture_provider = lambda tool_id, app_name: live_img

        captured = server.capture_screen(tool_id="test_tool", app_name="Test App")
        assert captured is not None
        assert captured.size == (640, 480)
        assert server.desktop._has_real_frame is True
        assert server.desktop.image.size == (640, 480)

    def test_capture_live_session_helper(self):
        """Verifies the module-level capture_live_session helper."""
        live_img = Image.new("RGB", (320, 240), (200, 50, 50))
        prev_provider = getattr(vnc_server, "_custom_capture_provider", None)
        try:
            vnc_server._custom_capture_provider = lambda tid, app: live_img
            result = capture_live_session(tool_id="burp", app_name="Burp Suite")
            assert result is not None
            assert result.size == (320, 240)
        finally:
            vnc_server._custom_capture_provider = prev_provider

    def test_capture_from_kali_worker_decodes_png(self):
        """Verifies in-guest Kali worker capture successfully parses base64 scrot output."""
        expected_img = Image.new("RGB", (400, 300), (20, 30, 40))
        mock_conn = MockKaliConnector(is_connected=True, plane_type=ExecutionPlaneType.LINUX_NATIVE, image_to_return=expected_img)

        result = _capture_from_kali_worker(connector=mock_conn, tool_name="wireshark")
        assert result is not None
        assert result.size == (400, 300)

    def test_capture_from_kali_worker_refuses_simulated_plane(self):
        """Verifies in-guest capture skips when connector is simulated mock."""
        mock_conn = MockKaliConnector(is_connected=True, plane_type=ExecutionPlaneType.SIMULATED_MOCK)
        result = _capture_from_kali_worker(connector=mock_conn, tool_name="burp")
        assert result is None

    def test_capture_from_kali_worker_disconnected(self):
        """Verifies in-guest capture returns None when connector is disconnected."""
        mock_conn = MockKaliConnector(is_connected=False)
        result = _capture_from_kali_worker(connector=mock_conn)
        assert result is None

    def test_capture_from_vnc_socket_rfb_handshake(self):
        """
        Spins up a lightweight mock RFB 3.8 socket server and verifies _capture_from_vnc_socket
        negotiates the RFB handshake, requests a framebuffer update, and decodes raw pixels.
        """
        # Find an ephemeral open port
        sock_find = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_find.bind(("127.0.0.1", 0))
        port = sock_find.getsockname()[1]
        sock_find.close()

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", port))
        server_sock.listen(1)

        def mock_rfb_peer():
            try:
                conn, _ = server_sock.accept()
                conn.settimeout(2.0)
                # 1. Send RFB 003.008\n
                conn.sendall(b"RFB 003.008\n")
                # Receive client version
                client_ver = conn.recv(12)
                # 2. Send Security Types (1 type: None = 1)
                conn.sendall(b"\x01\x01")
                # Receive client security choice
                conn.recv(1)
                # 3. SecurityResult: OK (0)
                conn.sendall(b"\x00\x00\x00\x00")
                # Receive ClientInit (shared-flag: 1 byte)
                conn.recv(1)
                # 4. ServerInit: width=100, height=50, 16 bytes pixel format, name length=4, name="Mock"
                # Pixel format: 32 bpp, 24 depth, big-endian=0, true-colour=1,
                # red-max=255, green-max=255, blue-max=255, red-shift=16, green-shift=8, blue-shift=0, 3 pad
                pix_fmt = struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
                server_init = struct.pack(">HH", 100, 50) + pix_fmt + struct.pack(">I", 4) + b"Mock"
                conn.sendall(server_init)
                # Receive SetPixelFormat / SetEncodings / FramebufferUpdateRequest
                conn.recv(1024)

                # 5. Send FramebufferUpdate: msg_type=0, pad=0, num_rects=1
                # Rect header: x=0, y=0, w=100, h=50, encoding=0 (RAW)
                fb_header = struct.pack(">BBH", 0, 0, 1)
                rect_header = struct.pack(">HHHHi", 0, 0, 100, 50, 0)
                # 100 * 50 * 4 bytes raw BGRX pixels (e.g. Blue=255, Green=128, Red=64, X=0)
                pixel_row = b"\xff\x80\x40\x00" * 100
                pixel_data = pixel_row * 50
                conn.sendall(fb_header + rect_header + pixel_data)
                time.sleep(0.1)
                conn.close()
            except Exception:
                pass
            finally:
                server_sock.close()

        th = threading.Thread(target=mock_rfb_peer, daemon=True)
        th.start()

        img = _capture_from_vnc_socket(host="127.0.0.1", port=port, timeout=2.0)
        assert img is not None
        assert img.size == (100, 50)


# ─────────────────────────────────────────────────────────────────────────────
# 2. BaseGuiAdapter Real vs Fallback Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseGuiAdapterRealVsFallback:

    def test_real_screen_capture_path(self, temp_gui_env):
        """
        When vnc_server has an active session, capture_screenshot uses the real frame,
        sets is_simulated=False, simulation_notice=None, and does not burn the amber warning banner.
        """
        store = temp_gui_env["store"]
        real_img = Image.new("RGB", (800, 600), (30, 45, 60))

        # Configure custom capture provider on singleton
        vnc_server._custom_capture_provider = lambda tid, app: real_img
        try:
            adapter = BurpSuiteGuiAdapter(store=store)
            vis = adapter.capture_screenshot(
                task_id="real_test_task",
                caption="Burp Suite Real Dashboard",
                workflow_step="real_capture",
            )

            # Metadata validations
            assert vis.metadata["is_simulated"] is False
            assert vis.metadata["simulation_notice"] is None
            assert vis.metadata["capture_source"] == "vnc_live"
            assert adapter.last_screenshot_is_simulated is False
            assert adapter.has_real_captures is True

            # Caption should not have [SIMULATED] prefix
            assert "[SIMULATED]" not in vis.caption
            assert vis.caption == "Burp Suite Real Dashboard"

            # UI State validations
            ui_state = adapter.extract_ui_state()
            assert ui_state["is_simulated"] is False
            assert ui_state["simulation_notice"] is None
            assert SIMULATION_NOTICE_TEXT not in adapter.get_state_summary()

            # Execute method validation
            obs = adapter.execute(
                inputs={"action": "workflow", "workflow": "toggle_proxy"},
                task_id="real_exec_task",
            )
            assert obs.is_simulated is False
            assert obs.simulation_notice is None
            assert obs.fallback_notice is None
            assert SIMULATION_NOTICE_TEXT not in obs.raw_stdout
            assert obs.observation["is_simulated"] is False
            assert obs.observation["simulation_notice"] is None
        finally:
            vnc_server._custom_capture_provider = None

    def test_fallback_simulation_notice_safety_net(self, temp_gui_env):
        """
        When no real GUI session is reachable, capture_screenshot falls back to
        honest labeling with amber banner, SIMULATION_NOTICE_TEXT, and simulated plane.
        """
        store = temp_gui_env["store"]
        vnc_server._custom_capture_provider = None  # Ensure no real capture is provided

        adapter = BurpSuiteGuiAdapter(store=store)
        vis = adapter.capture_screenshot(
            task_id="fallback_test_task",
            caption="Burp Suite Fallback Dashboard",
            workflow_step="fallback_capture",
        )

        # Metadata assertions for honest simulation safety net
        assert vis.metadata["is_simulated"] is True
        assert vis.metadata["simulation_notice"] == SIMULATION_NOTICE_TEXT
        assert vis.metadata["execution_plane"] == ExecutionPlaneType.SIMULATED_MOCK.value
        assert vis.metadata["capture_source"] == "synthetic_fallback"
        assert adapter.last_screenshot_is_simulated is True

        # Caption must contain [SIMULATED]
        assert vis.caption.startswith("[SIMULATED]")

        # UI state must reflect simulation
        ui_state = adapter.extract_ui_state()
        assert ui_state["is_simulated"] is True
        assert ui_state["simulation_notice"] == SIMULATION_NOTICE_TEXT
        assert SIMULATION_NOTICE_TEXT in adapter.get_state_summary()

        # ToolObservation must preserve honest simulation notice
        obs = adapter.execute(
            inputs={"action": "workflow", "workflow": "toggle_proxy"},
            task_id="fallback_exec_task",
        )
        assert obs.is_simulated is True
        assert obs.simulation_notice == SIMULATION_NOTICE_TEXT
        assert obs.fallback_notice == SIMULATION_NOTICE_TEXT
        assert SIMULATION_NOTICE_TEXT in obs.raw_stdout
        assert obs.execution_plane == ExecutionPlaneType.SIMULATED_MOCK.value

    def test_amber_banner_burned_only_on_fallback(self, temp_gui_env):
        """
        Verifies that the amber warning banner is drawn on fallback screenshots
        but NOT drawn on genuine live session captures.
        """
        store = temp_gui_env["store"]

        # 1. Fallback capture: banner is drawn with outline (245, 158, 11)
        vnc_server._custom_capture_provider = None
        adapter_fb = WiresharkGuiAdapter(store=store)
        vis_fb = adapter_fb.capture_screenshot("task_fb", "Wireshark Fallback")
        assert vis_fb.metadata["capture_source"] == "synthetic_fallback"
        assert vis_fb.metadata["is_simulated"] is True

        img_fb = Image.open(vis_fb.image_path)
        # Top banner outline is at y=0 with amber outline color (245, 158, 11)
        has_amber_fb = any(img_fb.getpixel((x, 0))[:3] == (245, 158, 11) for x in range(10, 200))
        assert has_amber_fb is True

        # 2. Live capture: pure clean frame without amber banner
        clean_img = Image.new("RGBA", (800, 600), (20, 20, 20, 255))
        vnc_server._custom_capture_provider = lambda tid, app: clean_img
        try:
            adapter_live = WiresharkGuiAdapter(store=store)
            vis_live = adapter_live.capture_screenshot("task_live", "Wireshark Live")
            assert vis_live.metadata["capture_source"] == "vnc_live"
            assert vis_live.metadata["is_simulated"] is False

            img_live = Image.open(vis_live.image_path)
            has_amber_live = any(img_live.getpixel((x, 0))[:3] == (245, 158, 11) for x in range(10, 200))
            assert has_amber_live is False
        finally:
            vnc_server._custom_capture_provider = None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Interactive Input Forwarding Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestVncInteractiveForwarding:

    def test_bounded_click_forwards_pointer_to_vnc_desktop(self, temp_gui_env):
        """Verifies bounded_click dispatches pointer position to vnc_server.desktop."""
        store = temp_gui_env["store"]
        adapter = ZapGuiAdapter(store=store)

        vnc_server.desktop.mouse_x = 0
        vnc_server.desktop.mouse_y = 0

        res = adapter.bounded_click(task_id="click_task", x=120, y=140)
        assert res["success"] is True
        assert vnc_server.desktop.mouse_x == 120
        assert vnc_server.desktop.mouse_y == 140

    def test_bounded_type_forwards_keys_to_vnc_desktop(self, temp_gui_env):
        """Verifies bounded_type forwards keystrokes into vnc_server.desktop."""
        store = temp_gui_env["store"]
        adapter = ZapGuiAdapter(store=store)

        vnc_server.desktop.current_input = ""
        res = adapter.bounded_type(task_id="type_task", text="admin")
        assert res["success"] is True
        # vnc_server.desktop receives keystrokes
        assert vnc_server.desktop.current_input == "admin"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Multi-Tool Adapter Real Capture Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestAllGuiAdaptersLiveCapture:

    @pytest.mark.parametrize("adapter_cls,wf_name", [
        (BurpSuiteGuiAdapter, "inspect_proxy_history"),
        (WiresharkGuiAdapter, "start_capture"),
        (ZapGuiAdapter, "run_spider"),
    ])
    def test_adapter_workflows_reflect_live_screen_capture(self, temp_gui_env, adapter_cls, wf_name):
        """Verifies Burp, Wireshark, and ZAP all seamlessly switch to live mode when screen capture succeeds."""
        store = temp_gui_env["store"]
        live_img = Image.new("RGB", (1024, 768), (50, 100, 150))
        vnc_server._custom_capture_provider = lambda tid, app: live_img

        try:
            adapter = adapter_cls(store=store)
            res = adapter.execute_workflow(task_id="wf_live_task", workflow_name=wf_name)
            assert res["success"] is True
            assert res["is_simulated"] is False
            assert res["simulation_notice"] is None
            assert res["execution_plane"] != ExecutionPlaneType.SIMULATED_MOCK.value

            # Verify UI state reflects live capture
            ui_state = res["ui_state"]
            assert ui_state["is_simulated"] is False
            assert ui_state["simulation_notice"] is None
        finally:
            vnc_server._custom_capture_provider = None
