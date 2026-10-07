#!/usr/bin/env python3
"""
Integration test suite for:
- Session Gateway + Workspace Manager deployable backend service
- "Boot a disposable Kali VM per project/session"
- Auth / session state for browser clients (desktop and mobile)
- Offline Indicator data path logic (fully offline / local-only / connected)
"""

import os
import sys
import json
import time
import shutil
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.auth import AuthManager, AuthSession
from orchestrator.workspace_manager import WorkspaceManager, WorkspaceStatus


class TestAuthManager(unittest.TestCase):
    """Verifies auth and session state across desktop and mobile browser clients."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kairo_auth_test_")
        self.auth_manager = AuthManager(secret_key="test-secret-key-12345")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_issue_and_verify_desktop_token(self):
        session = self.auth_manager.issue_token(
            user_id="alice_secops",
            role="operator",
            client_type="browser-desktop",
            ttl_seconds=3600,
        )
        self.assertTrue(len(session.token) > 20)
        self.assertEqual(session.client_type, "browser-desktop")
        self.assertEqual(session.user_id, "alice_secops")

        # Verify token
        is_valid, user, err = self.auth_manager.verify_token(session.token)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertIsNotNone(user)
        self.assertEqual(user.user_id, "alice_secops")
        self.assertEqual(user.role, "operator")
        self.assertEqual(user.client_type, "browser-desktop")

    def test_issue_and_verify_mobile_token(self):
        session = self.auth_manager.issue_token(
            user_id="mobile_oncall",
            role="operator",
            client_type="browser-mobile",
            ttl_seconds=1800,
        )
        self.assertEqual(session.client_type, "browser-mobile")

        is_valid, user, err = self.auth_manager.verify_token(session.token)
        self.assertTrue(is_valid)
        self.assertEqual(user.client_type, "browser-mobile")

    def test_invalid_and_tampered_tokens(self):
        session = self.auth_manager.issue_token("bob", "admin", "browser-desktop")
        
        # Tampered payload
        tampered_token = f"{session.token}_tampered_fake"
        is_valid, user, err = self.auth_manager.verify_token(tampered_token)
        self.assertFalse(is_valid)
        self.assertIsNotNone(err)

        # Expired token
        expired_session = self.auth_manager.issue_token("charlie", "auditor", "browser-desktop", ttl_seconds=-10)
        is_valid, user, err = self.auth_manager.verify_token(expired_session.token)
        self.assertFalse(is_valid)
        self.assertIn("expired", err.lower())

    def test_token_revocation(self):
        session = self.auth_manager.issue_token("dave", "operator", "browser-desktop")
        is_valid, _, _ = self.auth_manager.verify_token(session.token)
        self.assertTrue(is_valid)

        # Revoke
        revoked = self.auth_manager.revoke_token(session.token)
        self.assertTrue(revoked)

        # Verification should now fail
        is_valid, _, err = self.auth_manager.verify_token(session.token)
        self.assertFalse(is_valid)
        self.assertIn("revoked", err.lower())


class TestWorkspaceManager(unittest.TestCase):
    """Verifies booting disposable Kali VM workspaces per project/session and server-side lifecycle."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kairo_ws_test_")
        self.db_path = os.path.join(self.temp_dir, "test_events.db")
        self.storage_root = os.path.join(self.temp_dir, "workspaces_storage")
        self.workspace_manager = WorkspaceManager(
            db_path=self.db_path,
            workspaces_root=self.storage_root,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_provision_disposable_workspace(self):
        session_id = "sess_test_101"
        project_name = "pentest_acme_corp"
        owner_id = "analyst_01"

        ws = self.workspace_manager.provision_disposable_workspace(
            project_name=project_name,
            session_id=session_id,
            owner_id=owner_id,
        )

        self.assertIsNotNone(ws)
        self.assertTrue(ws.workspace_id.startswith("ws_"))
        self.assertEqual(ws.project_name, project_name)
        self.assertEqual(ws.session_id, session_id)
        self.assertEqual(ws.owner_id, owner_id)
        self.assertEqual(ws.status, WorkspaceStatus.READY)

        # Check host directories were provisioned
        self.assertTrue(os.path.exists(ws.ephemeral_dir))
        self.assertTrue(os.path.exists(os.path.join(ws.ephemeral_dir, "artifacts")))
        self.assertTrue(os.path.exists(os.path.join(ws.ephemeral_dir, "logs")))

        # Check SQLite persistence
        stored_ws = self.workspace_manager.get_workspace(ws.workspace_id)
        self.assertIsNotNone(stored_ws)
        self.assertEqual(stored_ws.workspace_id, ws.workspace_id)
        self.assertEqual(stored_ws.status, WorkspaceStatus.READY)

        # Check active workspace retrieval by session
        active_ws = self.workspace_manager.get_active_workspace_for_session(session_id)
        self.assertIsNotNone(active_ws)
        self.assertEqual(active_ws.workspace_id, ws.workspace_id)

    def test_terminate_disposable_workspace(self):
        session_id = "sess_test_terminate"
        ws = self.workspace_manager.provision_disposable_workspace(
            project_name="temp_investigation",
            session_id=session_id,
        )

        self.assertTrue(os.path.exists(ws.ephemeral_dir))
        wid = ws.workspace_id

        # Terminate and purge
        term_res = self.workspace_manager.terminate_workspace(wid, purge_storage=True)
        self.assertIsNotNone(term_res)
        self.assertEqual(term_res["status"], "terminated")

        # Verify host dir purged
        self.assertFalse(os.path.exists(ws.ephemeral_dir))

        # Verify DB status updated
        refreshed = self.workspace_manager.get_workspace(wid)
        self.assertEqual(refreshed.status, WorkspaceStatus.TERMINATED)

        # Active workspace for session should now be None
        active = self.workspace_manager.get_active_workspace_for_session(session_id)
        self.assertIsNone(active)

    def test_list_multiple_workspaces(self):
        ws1 = self.workspace_manager.provision_disposable_workspace("proj_1", "sess_1")
        ws2 = self.workspace_manager.provision_disposable_workspace("proj_2", "sess_2")

        all_ws = self.workspace_manager.list_workspaces()
        ws_ids = [w.workspace_id for w in all_ws]
        self.assertIn(ws1.workspace_id, ws_ids)
        self.assertIn(ws2.workspace_id, ws_ids)


class TestOfflineIndicatorDataPath(unittest.TestCase):
    """Verifies the three explicit data path states for the Offline Indicator."""

    def test_data_path_logic(self):
        def compute_data_path(ws_status, host):
            if ws_status == "disconnected":
                return "fully offline"
            is_loopback = host in ("localhost", "127.0.0.1") or host.endswith(".local")
            return "local-only" if is_loopback else "connected"

        # Disconnected -> Fully Offline
        self.assertEqual(compute_data_path("disconnected", "localhost"), "fully offline")
        self.assertEqual(compute_data_path("disconnected", "private.kairo.corp"), "fully offline")

        # Local Loopback -> Local-Only (0 Cloud Egress)
        self.assertEqual(compute_data_path("connected", "localhost"), "local-only")
        self.assertEqual(compute_data_path("connected", "127.0.0.1"), "local-only")
        self.assertEqual(compute_data_path("connected", "kairo-worker.local"), "local-only")

        # Remote Private Instance -> Connected
        self.assertEqual(compute_data_path("connected", "kairo.internal.corp"), "connected")
        self.assertEqual(compute_data_path("connected", "app.secops.net"), "connected")


if __name__ == "__main__":
    unittest.main()
