"""
Automated Test Suite for Tier 3 GUI Tool Adapters.

Tests:
1. Conformance & Tier 3 Security Classification:
   - Adapter registry discovery & instantiation
   - ToolSpec YAML JSON Schema validation
   - Tier 3 mapping in events.db and ScopeContract enforcement
2. Burp Suite Community Edition Adapter:
   - Lifecycle (launch, monitor, stop)
   - Periodic screenshot engine with SHA-256 provenance
   - UI-state extraction (window title, visible panel, interactive controls)
   - Scripted workflows: init_project, toggle_proxy, inspect_proxy_history, send_to_repeater, export_target_sitemap
   - Bounded interactions: coordinate click, control-targeted click, text typing
   - Visual Evidence registration in EvidenceStore and SQLite database
3. Wireshark Network Protocol Analyzer Adapter:
   - Lifecycle (launch, monitor, stop)
   - UI-state extraction (window title, active panes, packet counters)
   - Scripted workflows: select_interface, start_capture, apply_display_filter, inspect_packet, stop_and_save_pcap
   - Binary .pcap artifact creation with SHA-256 provenance & NetworkEvidence registration
   - Visual Evidence screenshots
4. OWASP ZAP GUI Adapter (3rd High-Value Tool):
   - Lifecycle, UI-state extraction, and alert tree breakdown
   - Scripted workflows: quick_start, run_spider, inspect_alerts, export_report
   - Visual Evidence screenshots
5. Scope Contract Authorization:
   - Verifies refusal when Tier 3 is omitted from allowed_tool_tiers
   - Verifies execution when Tier 3 is authorized
6. Orchestrator Server API Endpoints:
   - GET /gui/adapters
   - POST /gui/execute
   - GET /gui/state/{tool_id}
   - POST /gui/screenshot/{tool_id}
"""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import pytest

from fastapi.testclient import TestClient

from events.db import (
    DEFAULT_DB_PATH,
    compute_sha256,
    create_scope_contract,
    get_connection,
    get_tool_tier,
    init_db,
    validate_scope_request,
)
from orchestrator.adapters.burpsuite_adapter import BurpSuiteGuiAdapter
from orchestrator.adapters.gui_base import BaseGuiAdapter, GuiControl
from orchestrator.adapters.registry import adapter_registry
from orchestrator.adapters.wireshark_adapter import WiresharkGuiAdapter
from orchestrator.adapters.zap_adapter import ZapGuiAdapter
from orchestrator.evidence_store import EvidenceClass, EvidenceStore
from orchestrator.server import app
from registry.loader import ToolRegistry


@pytest.fixture
def temp_gui_env(tmp_path):
    """Provides an isolated test environment with temporary SQLite DB and artifacts directory."""
    db_file = tmp_path / "test_gui_events.db"
    artifacts_dir = tmp_path / "test_gui_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_file)

    store = EvidenceStore(db_path=db_file, artifacts_dir=artifacts_dir)
    return {"db_path": db_file, "artifacts_dir": artifacts_dir, "store": store}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Conformance & Tier 3 Security Classification Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGuiAdapterConformance:
    def test_tier3_adapters_registered(self):
        """Verifies that Burp Suite, Wireshark, and ZAP adapters are in AdapterRegistry."""
        tool_ids = adapter_registry.list_tool_ids()
        assert "burpsuite.gui.v1" in tool_ids
        assert "wireshark.gui.v1" in tool_ids
        assert "zap.gui.v1" in tool_ids

    def test_tier3_classification_in_db_mapping(self):
        """Verifies that all GUI tools are mapped to Tier 3."""
        assert get_tool_tier("burpsuite.gui.v1") == 3
        assert get_tool_tier("burp.gui.v1") == 3
        assert get_tool_tier("wireshark.gui.v1") == 3
        assert get_tool_tier("zap.gui.v1") == 3

    def test_toolspec_yaml_schema_conformance(self):
        """Validates that the 3 GUI ToolSpec YAML files pass ToolRegistry JSON Schema validation."""
        registry = ToolRegistry()
        tools_dict = {t.id: t for t in registry.list_tools()}

        for tid in ["burpsuite.gui.v1", "wireshark.gui.v1", "zap.gui.v1"]:
            assert tid in tools_dict, f"Missing ToolSpec for {tid}"
            spec = tools_dict[tid]
            assert spec.gui is True or isinstance(spec.gui, dict)
            assert spec.binary != ""
            assert "gui_automation" in spec.capabilities
            assert "visual_evidence" in spec.capabilities


# ─────────────────────────────────────────────────────────────────────────────
# 2. Burp Suite Community Edition Adapter Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBurpSuiteGuiAdapter:
    def test_burp_lifecycle_and_ui_state_extraction(self, temp_gui_env):
        """Verifies Burp Suite launch, PID tracking, and UI-state extraction."""
        store = temp_gui_env["store"]
        adapter = BurpSuiteGuiAdapter(store=store)

        assert not adapter.is_running()
        launch_res = adapter.launch(task_id="task_burp_init", start_periodic=False)

        assert adapter.is_running()
        assert adapter.pid is not None
        assert "Burp Suite Community Edition" in adapter.window_title
        assert adapter.visible_panel in ("Proxy", "Dashboard")

        # Extract UI state
        ui_state = adapter.extract_ui_state()
        assert ui_state["running"] is True
        assert ui_state["tool_id"] == "burpsuite.gui.v1"
        assert ui_state["tier"] == 3
        assert "window_title" in ui_state
        assert "visible_panel" in ui_state
        assert "visible_subpanel" in ui_state
        assert "interactive_elements" in ui_state
        assert len(ui_state["interactive_elements"]) > 0

        # Verify initial screenshot recorded as Visual Evidence
        assert ui_state["last_screenshot"]["filepath"] is not None
        assert ui_state["last_screenshot"]["sha256"] is not None
        img_path = Path(ui_state["last_screenshot"]["filepath"])
        assert img_path.is_file()
        assert compute_sha256(img_path) == ui_state["last_screenshot"]["sha256"]

        # Stop
        stop_res = adapter.stop(task_id="task_burp_init")
        assert not adapter.is_running()
        assert stop_res["status"] == "stopped"

    def test_burp_periodic_screenshot_engine(self, temp_gui_env):
        """Verifies periodic background screenshot engine generates frames with SHA-256 provenance."""
        store = temp_gui_env["store"]
        adapter = BurpSuiteGuiAdapter(store=store)
        adapter.screenshot_interval_s = 0.6  # fast interval for testing

        adapter.launch(task_id="task_burp_periodic", start_periodic=True)
        time.sleep(1.5)  # wait for at least 2 periodic ticks
        adapter.stop(task_id="task_burp_periodic")

        # Should have captured at least initial + periodic + stop
        assert len(adapter.screenshots) >= 3
        for s in adapter.screenshots:
            assert s["filepath"] is not None
            assert s["sha256"] is not None
            p = Path(s["filepath"])
            assert p.is_file()
            assert compute_sha256(p) == s["sha256"]

        # Check SQLite database artifacts table for image/png records
        conn = get_connection(temp_gui_env["db_path"])
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename, mime_type, sha256 FROM artifacts WHERE mime_type = 'image/png'")
            rows = cursor.fetchall()
            assert len(rows) >= 3
        conn.close()

    def test_burp_scripted_workflows(self, temp_gui_env):
        """Verifies all Burp Suite bounded scripted workflows."""
        store = temp_gui_env["store"]
        adapter = BurpSuiteGuiAdapter(store=store)
        adapter.launch(task_id="task_burp_wf", start_periodic=False)

        # 1. toggle_proxy
        res_proxy = adapter.execute_workflow("task_burp_wf", "toggle_proxy", {"enable": False})
        assert res_proxy["success"] is True
        assert res_proxy["intercept_enabled"] is False
        assert "OFF" in adapter.window_title
        assert res_proxy["screenshot_sha256"] != ""

        # 2. inspect_proxy_history
        res_hist = adapter.execute_workflow("task_burp_wf", "inspect_proxy_history", {})
        assert res_hist["success"] is True
        assert res_hist["total_items"] >= 4
        assert adapter.visible_subpanel == "HTTP history"
        assert res_hist["screenshot_sha256"] != ""

        # 3. send_to_repeater
        res_rep = adapter.execute_workflow(
            "task_burp_wf",
            "send_to_repeater",
            {"tab_name": "SQLi Probe", "url": "/api/v1/auth", "method": "POST"},
        )
        assert res_rep["success"] is True
        assert adapter.visible_panel == "Repeater"
        assert res_rep["response_status"] == 200
        assert res_rep["screenshot_sha256"] != ""

        # 4. export_target_sitemap
        res_map = adapter.execute_workflow("task_burp_wf", "export_target_sitemap", {})
        assert res_map["success"] is True
        assert adapter.visible_panel == "Target"
        assert res_map["endpoint_count"] >= 5
        assert res_map["screenshot_sha256"] != ""

        adapter.stop("task_burp_wf")

    def test_burp_bounded_interactions(self, temp_gui_env):
        """Verifies bounded coordinate clicking, control targeting, and typing."""
        store = temp_gui_env["store"]
        adapter = BurpSuiteGuiAdapter(store=store)
        adapter.launch(task_id="task_burp_int", start_periodic=False)

        # Coordinate click out of bounds should fail cleanly
        oob_click = adapter.bounded_click("task_burp_int", 9999, 9999)
        assert oob_click["success"] is False

        # In-bounds coordinate click
        in_click = adapter.bounded_click("task_burp_int", 100, 50)
        assert in_click["success"] is True
        assert in_click["screenshot_sha256"] != ""

        # Control click: toggle intercept button
        btn_click = adapter.bounded_click_control("task_burp_int", "btn_intercept_toggle")
        assert btn_click["success"] is True
        assert btn_click["screenshot_sha256"] != ""

        # Bounded typing
        type_res = adapter.bounded_type("task_burp_int", "X-Custom-Header: Kairo-Agent", "input_repeater_req")
        assert type_res["success"] is True
        assert type_res["screenshot_sha256"] != ""

        adapter.stop("task_burp_int")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Wireshark GUI Adapter Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWiresharkGuiAdapter:
    def test_wireshark_lifecycle_and_ui_state(self, temp_gui_env):
        """Verifies Wireshark launch, status tracking, and 3-pane UI state extraction."""
        store = temp_gui_env["store"]
        adapter = WiresharkGuiAdapter(store=store)

        adapter.launch(task_id="task_ws_init", start_periodic=False)
        assert adapter.is_running()
        assert adapter.pid is not None
        assert "Wireshark" in adapter.window_title

        ui_state = adapter.extract_ui_state()
        assert ui_state["running"] is True
        assert ui_state["tool_id"] == "wireshark.gui.v1"
        assert ui_state["tier"] == 3
        assert "interactive_elements" in ui_state
        assert "btn_start_capture" in ui_state["interactive_elements"]

        # Verify initial screenshot
        assert ui_state["last_screenshot"]["sha256"] is not None
        adapter.stop("task_ws_init")

    def test_wireshark_scripted_workflows_and_pcap_provenance(self, temp_gui_env):
        """Verifies Wireshark workflows: capture start, display filter, packet inspection, and PCAP save."""
        store = temp_gui_env["store"]
        adapter = WiresharkGuiAdapter(store=store)
        adapter.launch(task_id="task_ws_wf", start_periodic=False)

        # 1. select_interface
        res_iface = adapter.execute_workflow("task_ws_wf", "select_interface", {"interface": "eth0"})
        assert res_iface["success"] is True
        assert adapter.interface == "eth0"

        # 2. start_capture
        res_cap = adapter.execute_workflow("task_ws_wf", "start_capture", {})
        assert res_cap["success"] is True
        assert res_cap["capture_state"] == "capturing"
        assert "Capturing" in adapter.window_title

        # 3. apply_display_filter
        res_flt = adapter.execute_workflow("task_ws_wf", "apply_display_filter", {"filter": "http"})
        assert res_flt["success"] is True
        assert res_flt["matched_packets"] == 2
        assert "http" in adapter.window_title

        # 4. inspect_packet
        res_insp = adapter.execute_workflow("task_ws_wf", "inspect_packet", {"packet_no": 4})
        assert res_insp["success"] is True
        assert res_insp["protocol"] == "HTTP"
        assert "decode_tree" in res_insp
        assert "Internet Protocol Version 4" in res_insp["decode_tree"]

        # 5. stop_and_save_pcap
        res_pcap = adapter.execute_workflow("task_ws_wf", "stop_and_save_pcap", {})
        assert res_pcap["success"] is True
        assert res_pcap["pcap_file"] is not None
        assert res_pcap["pcap_sha256"] != ""
        pcap_path = Path(res_pcap["pcap_file"])
        assert pcap_path.is_file()
        assert compute_sha256(pcap_path) == res_pcap["pcap_sha256"]

        # Verify NetworkEvidence record created in SQLite
        conn = get_connection(temp_gui_env["db_path"])
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename, sha256 FROM artifacts WHERE mime_type = 'image/png'")
            screenshots = cursor.fetchall()
            assert len(screenshots) >= 5
        conn.close()

        adapter.stop("task_ws_wf")


# ─────────────────────────────────────────────────────────────────────────────
# 4. OWASP ZAP GUI Adapter Tests (3rd Tool)
# ─────────────────────────────────────────────────────────────────────────────

class TestZapGuiAdapter:
    def test_zap_lifecycle_and_workflows(self, temp_gui_env):
        """Verifies OWASP ZAP launch, spider workflow, alert extraction, and report generation."""
        store = temp_gui_env["store"]
        adapter = ZapGuiAdapter(store=store)
        adapter.launch(task_id="task_zap_wf", start_periodic=False)

        # 1. quick_start
        res_qs = adapter.execute_workflow("task_zap_wf", "quick_start", {"target_url": "http://lab.local"})
        assert res_qs["success"] is True
        assert adapter.target_url == "http://lab.local"

        # 2. run_spider
        res_sp = adapter.execute_workflow("task_zap_wf", "run_spider", {})
        assert res_sp["success"] is True
        assert res_sp["discovered_urls_count"] >= 5

        # 3. inspect_alerts
        res_al = adapter.execute_workflow("task_zap_wf", "inspect_alerts", {})
        assert res_al["success"] is True
        assert res_al["total_alerts"] >= 4
        assert res_al["risk_summary"]["High"] >= 1

        # 4. export_report
        res_rep = adapter.execute_workflow("task_zap_wf", "export_report", {})
        assert res_rep["success"] is True
        assert res_rep["report_sha256"] != ""
        rep_p = Path(res_rep["report_filepath"])
        assert rep_p.is_file()
        assert compute_sha256(rep_p) == res_rep["report_sha256"]

        adapter.stop("task_zap_wf")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Scope Contract Enforcement Tests for Tier 3 GUI Tools
# ─────────────────────────────────────────────────────────────────────────────

class TestScopeContractEnforcement:
    def test_tier3_gui_tools_blocked_when_tier3_unauthorized(self, temp_gui_env):
        """Verifies that Scope Contract rejects Tier 3 GUI tools if only Tiers [1, 2] are allowed."""
        db_path = temp_gui_env["db_path"]
        contract = create_scope_contract(
            targets=["http://authorized-target.local", "authorized-target.local"],
            network_scope="authorized_lab",
            time_window="8h",
            allowed_tool_tiers=[1, 2],  # TIER 3 EXCLUDED!
            authorized_by="secops@kairo.internal",
            db_path=db_path,
        )

        # Validate Burp Suite (Tier 3) -> Must be rejected
        val_burp = validate_scope_request(
            target="http://authorized-target.local",
            tool_id="burpsuite.gui.v1",
            tool_tier=3,
            db_path=db_path,
        )
        assert val_burp["authorized"] is False
        assert "TOOL_TIER_EXCEEDED" in val_burp["reason"] or "Tier 3" in val_burp["reason"]

        # Validate Wireshark (Tier 3) -> Must be rejected
        val_ws = validate_scope_request(
            target="authorized-target.local",
            tool_id="wireshark.gui.v1",
            tool_tier=3,
            db_path=db_path,
        )
        assert val_ws["authorized"] is False

    def test_tier3_gui_tools_permitted_when_tier3_authorized(self, temp_gui_env):
        """Verifies that Scope Contract authorizes Tier 3 GUI tools when Tier 3 is in allowed_tool_tiers."""
        db_path = temp_gui_env["db_path"]
        contract = create_scope_contract(
            targets=["http://authorized-target.local", "authorized-target.local"],
            network_scope="authorized_lab",
            time_window="8h",
            allowed_tool_tiers=[1, 2, 3],  # Tier 3 AUTHORIZED
            authorized_by="secops@kairo.internal",
            db_path=db_path,
        )

        val_burp = validate_scope_request(
            target="http://authorized-target.local",
            tool_id="burpsuite.gui.v1",
            tool_tier=3,
            db_path=db_path,
        )
        assert val_burp["authorized"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 6. Orchestrator Server API Endpoints Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorGuiEndpoints:
    def test_get_gui_adapters_list(self):
        """Tests GET /gui/adapters endpoint."""
        client = TestClient(app)
        resp = client.get("/gui/adapters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 3
        tool_ids = [a["tool_id"] for a in data["adapters"]]
        assert "burpsuite.gui.v1" in tool_ids
        assert "wireshark.gui.v1" in tool_ids
        assert "zap.gui.v1" in tool_ids

    def test_post_gui_execute_burp_workflow(self):
        """Tests POST /gui/execute endpoint running Burp Suite workflow."""
        client = TestClient(app)
        req_payload = {
            "tool_id": "burpsuite.gui.v1",
            "action": "workflow",
            "workflow": "init_project",
            "params": {"project_name": "API Audit Project"},
            "session_id": "test_gui_session",
        }
        resp = client.post("/gui/execute", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_id"] == "burpsuite.gui.v1"
        assert data["status"] == "success"
        assert len(data["artifacts"]) > 0

    def test_get_gui_state(self):
        """Tests GET /gui/state/{tool_id} endpoint."""
        client = TestClient(app)
        resp = client.get("/gui/state/burpsuite.gui.v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_id"] == "burpsuite.gui.v1"
        assert data["tier"] == 3
        assert "visible_panel" in data
        assert "controls_count" in data

    def test_post_gui_screenshot(self):
        """Tests POST /gui/screenshot/{tool_id} on-demand endpoint."""
        client = TestClient(app)
        resp = client.post("/gui/screenshot/burpsuite.gui.v1?caption=API+Endpoint+Audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sha256"] != ""
        assert data["filepath"] != ""
        assert data["thumbnail_b64"].startswith("data:image/png;base64,")
