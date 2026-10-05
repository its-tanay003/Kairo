"""
Comprehensive test suite for the Playwright Security Testing Browser Adapter,
Visible State Extraction, Action History, Scripted Workflows (XSS check, auth walkthrough, audits),
Scope Contract Enforcement, and Orchestrator REST Endpoints.
"""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from registry.loader import ToolRegistry
from events.db import (
    ScopeContract,
    create_scope_contract,
    get_connection,
    get_tool_tier,
    init_db,
    seed_default_scope_contract,
    validate_scope_request,
)
from orchestrator.adapters.base import ToolObservation
from orchestrator.adapters.browser_adapter import (
    BrowserActionStep,
    BrowserCookie,
    BrowserDialog,
    SecurityBrowserAdapter,
    browser_adapter,
)
from orchestrator.adapters.registry import adapter_registry
from orchestrator.evidence_store import EvidenceClass, EvidenceStore
from orchestrator.server import app


@pytest.fixture
def temp_browser_env():
    """Sets up an isolated SQLite database and artifact directory for browser tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_browser_events.db"
        artifacts_dir = tmp_path / "test_browser_artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        init_db(db_path)
        store = EvidenceStore(db_path=db_path, artifacts_dir=artifacts_dir)
        adapter = SecurityBrowserAdapter(store=store)

        yield {
            "tmp_path": tmp_path,
            "db_path": db_path,
            "artifacts_dir": artifacts_dir,
            "store": store,
            "adapter": adapter,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Conformance, Registry Discovery, and ToolSpec YAML Schema
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserAdapterConformance:
    def test_browser_adapter_registered_in_registry(self):
        """Verifies that browser.security.v1 is discovered by AdapterRegistry."""
        tool_ids = adapter_registry.list_tool_ids()
        assert "browser.security.v1" in tool_ids
        adapter_cls = adapter_registry.get("browser.security.v1")
        assert adapter_cls is SecurityBrowserAdapter

    def test_tier2_classification_in_db_mapping(self):
        """Verifies that browser tools are classified as Tier 2 active testing tools in db.py."""
        assert get_tool_tier("browser.security.v1") == 2
        assert get_tool_tier("playwright.browser.v1") == 2
        assert get_tool_tier("browser.test.v1") == 2

    def test_toolspec_yaml_schema_conformance(self):
        """Validates that browser_security_v1.yaml conforms to the 16-field ToolSpec schema."""
        registry = ToolRegistry()
        tools_dict = {t.id: t for t in registry.list_tools()}

        assert "browser.security.v1" in tools_dict
        spec = tools_dict["browser.security.v1"]
        assert spec.binary == "playwright"
        assert spec.category == "web_security"
        assert "browser_automation" in spec.capabilities
        assert "xss_testing" in spec.capabilities
        assert "auth_walkthrough" in spec.capabilities
        assert "visual_evidence" in spec.capabilities
        assert spec.gui is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Lifecycle & Visible State Extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserLifecycleAndVisibleState:
    def test_lifecycle_and_visible_state_extraction(self, temp_browser_env):
        """Verifies browser launch, stop, and visible state extraction."""
        adapter = temp_browser_env["adapter"]

        assert not adapter.is_running
        launch_res = adapter.launch(task_id="task_init")
        assert adapter.is_running
        assert adapter.current_url == "http://target.local/portal"
        assert "Target Security Testing Portal" in adapter.page_title
        assert adapter.status_code == 200

        # Extract visible state
        state = adapter.extract_visible_state()
        assert state["tool_id"] == "browser.security.v1"
        assert state["is_running"] is True
        assert state["url"] == "http://target.local/portal"
        assert "security_context" in state
        assert "dom_snapshot" in state
        assert state["dom_snapshot"]["elements_count"] > 0
        assert state["last_screenshot"] is not None
        assert state["last_screenshot"]["sha256"] is not None

        # Stop
        stop_res = adapter.stop()
        assert not adapter.is_running
        assert stop_res["status"] == "stopped"

    def test_sequential_action_history_recording(self, temp_browser_env):
        """Verifies that actions record sequential step-by-step audit history with Visual Evidence."""
        adapter = temp_browser_env["adapter"]

        adapter.launch(task_id="task_h1")
        adapter.navigate("http://target.local/login.php", task_id="task_h2")
        adapter.fill_input("input#username", "testuser", task_id="task_h3")
        adapter.click_element("button[type='submit']", task_id="task_h4")

        history = adapter.get_action_history()
        assert len(history) == 4

        # Verify sequential ordering and fields
        for i, step in enumerate(history, 1):
            assert step["step_index"] == i
            assert "action" in step
            assert "target" in step
            assert "status" in step
            assert "duration_ms" in step
            assert "timestamp" in step
            assert step["screenshot_sha256"] is not None
            assert step["thumbnail_b64"] is not None

        assert history[0]["action"] == "launch"
        assert history[1]["action"] == "navigate"
        assert history[1]["target"] == "http://target.local/login.php"
        assert history[2]["action"] == "fill"
        assert history[2]["target"] == "input#username"
        assert history[3]["action"] == "click"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scripted Security Workflows
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserScriptedWorkflows:
    def test_workflow_xss_check_alert_and_reflection(self, temp_browser_env):
        """
        Tests the scripted XSS check workflow:
        - Injects <script>alert('kairo-xss')</script>
        - Verifies alert dialog capture
        - Verifies DOM reflection
        - Confirms vulnerability finding and Visual Evidence with SHA-256
        """
        adapter = temp_browser_env["adapter"]

        res = adapter.execute_workflow(
            workflow_name="xss_check",
            params={
                "url": "http://target.local/search.php",
                "selector": "input[name='q']",
                "payload": "<script>alert('kairo-xss')</script>",
            },
            task_id="task_xss_test",
        )

        assert res["workflow"] == "xss_check"
        assert res["status"] == "vulnerability_detected"
        assert res["vulnerability_detected"] is True

        # Check finding
        finding = res["finding"]
        assert finding["type"] == "Cross-Site Scripting (XSS)"
        assert finding["severity"] == "HIGH"
        assert finding["alert_triggered"] is True
        assert finding["alert_message"] == "kairo-xss"
        assert finding["reflected_unescaped"] is True

        # Check alert dialog captured
        assert len(adapter.alerts_captured) > 0
        assert adapter.alerts_captured[-1].message == "kairo-xss"

        # Check Visual Evidence screenshot
        step = res["step"]
        assert step["screenshot_sha256"] is not None
        assert step["screenshot_path"] is not None
        assert Path(step["screenshot_path"]).exists()

        # Check that finding is stored in adapter findings
        assert len(adapter.findings) > 0

    def test_workflow_auth_walkthrough_and_session_cookie(self, temp_browser_env):
        """
        Tests the scripted authentication walkthrough:
        - Fills credentials
        - Submits login form
        - Captures newly issued session cookie with HttpOnly & Secure flags
        - Verifies redirect to admin dashboard
        """
        adapter = temp_browser_env["adapter"]

        res = adapter.execute_workflow(
            workflow_name="auth_walkthrough",
            params={
                "login_url": "http://target.local/login.php",
                "username_selector": "input#username",
                "username": "admin",
                "password_selector": "input#password",
                "password": "SuperSecretPassword123!",
            },
            task_id="task_auth_test",
        )

        assert res["workflow"] == "auth_walkthrough"
        assert res["status"] == "success"
        auth = res["auth_details"]
        assert auth["authenticated"] is True
        assert auth["user"] == "admin"
        assert "dashboard" in auth["post_auth_url"]
        assert "auth_token" in adapter.cookies

        # Check session cookie security flags
        cookie = adapter.cookies["auth_token"]
        assert cookie.http_only is True
        assert cookie.secure is True
        assert cookie.same_site == "Strict"

    def test_workflow_cookie_audit(self, temp_browser_env):
        """Tests auditing cookies for missing HttpOnly, Secure, and SameSite flags."""
        adapter = temp_browser_env["adapter"]

        res = adapter.execute_workflow(
            workflow_name="cookie_audit",
            params={"url": "http://target.local/portal"},
            task_id="task_cookie_audit",
        )

        assert res["workflow"] == "cookie_audit"
        assert res["status"] == "vulnerability_detected"
        assert len(res["vulnerabilities"]) > 0
        # Check that legacy_session was flagged
        vuln_names = [v["cookie_name"] for v in res["vulnerabilities"]]
        assert "legacy_session" in vuln_names

    def test_workflow_dom_audit(self, temp_browser_env):
        """Tests auditing DOM for dangerous sinks and missing CSRF tokens."""
        adapter = temp_browser_env["adapter"]

        res = adapter.execute_workflow(
            workflow_name="dom_audit",
            params={"url": "http://target.local/search.php"},
            task_id="task_dom_audit",
        )

        assert res["workflow"] == "dom_audit"
        assert res["status"] == "vulnerability_detected"
        assert len(res["findings"]) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Scope Contract Authorization Enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserScopeContractEnforcement:
    def test_browser_blocked_when_tier2_unauthorized(self, temp_browser_env):
        """Verifies that browser active testing is denied if ScopeContract only permits Tier 1 (passive)."""
        db_path = temp_browser_env["db_path"]

        create_scope_contract(
            targets=["http://target.local", "target.local"],
            network_scope="10.0.0.0/24",
            time_window="8h",
            allowed_tool_tiers=[1],  # Only Tier 1 passive permitted
            authorized_by="Lead Auditor",
            db_path=db_path,
        )

        val = validate_scope_request(
            target="http://target.local",
            tool_id="browser.security.v1",
            tool_tier=2,
            db_path=db_path,
        )
        assert val["authorized"] is False
        assert "TOOL_TIER_EXCEEDED" in val["reason"]

    def test_browser_permitted_when_tier2_authorized(self, temp_browser_env):
        """Verifies that browser active testing is permitted when Tier 2 is authorized."""
        db_path = temp_browser_env["db_path"]

        create_scope_contract(
            targets=["http://target.local", "target.local"],
            network_scope="10.0.0.0/24",
            time_window="8h",
            allowed_tool_tiers=[1, 2],  # Tier 2 authorized
            authorized_by="Lead Auditor",
            db_path=db_path,
        )

        val = validate_scope_request(
            target="http://target.local",
            tool_id="browser.security.v1",
            tool_tier=2,
            db_path=db_path,
        )
        assert val["authorized"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Orchestrator REST Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorBrowserEndpoints:
    @pytest.fixture(autouse=True)
    def setup_client(self):
        self.client = TestClient(app)

    def test_get_browser_state(self):
        """GET /browser/state returns visible browser state."""
        resp = self.client.get("/browser/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_id"] == "browser.security.v1"
        assert "url" in data
        assert "page_title" in data
        assert "security_context" in data

    def test_post_browser_execute_workflow(self):
        """POST /browser/execute runs scripted XSS workflow."""
        create_scope_contract(
            targets=["http://target.local", "target.local", "127.0.0.1", "localhost"],
            network_scope="authorized_lab",
            time_window="8h",
            allowed_tool_tiers=[1, 2, 3],
            authorized_by="secops_lead@kairo.internal",
        )

        payload = {
            "session_id": "test_session",
            "action": "workflow",
            "workflow": "xss_check",
            "url": "http://target.local/search.php",
            "selector": "input[name='q']",
            "payload": "<script>alert('kairo-rest-xss')</script>",
        }
        resp = self.client.post("/browser/execute", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_id"] == "browser.security.v1"
        assert data["status"] in ("success", "vulnerability_detected")
        assert "observation" in data

    def test_get_browser_history(self):
        """GET /browser/history returns action history array."""
        resp = self.client.get("/browser/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert "count" in data
        assert isinstance(data["history"], list)

    def test_post_browser_screenshot(self):
        """POST /browser/screenshot generates on-demand visual evidence."""
        resp = self.client.post("/browser/screenshot?caption=Audit+Snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "sha256" in data
        assert "thumbnail_b64" in data
        assert data["sha256"] is not None

    def test_post_browser_stop(self):
        """POST /browser/stop halts the browser session."""
        resp = self.client.post("/browser/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"
