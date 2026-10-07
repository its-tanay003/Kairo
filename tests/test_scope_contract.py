"""
Comprehensive test suite for Scope Contract enforcement, HMAC-SHA256 signing,
execution gateway rejection, and event store audit logging.
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from events.db import (
    Event,
    init_db,
    get_connection,
    get_recent_events,
    create_scope_contract,
    get_active_scope_contract,
    list_scope_contracts,
    validate_scope_request,
    generate_scope_signature,
    verify_scope_signature,
    is_target_in_scope,
    get_tool_tier,
    seed_default_scope_contract,
)
from orchestrator.agent import AgentLoop


class TestScopeContract(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_events.db"
        init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scope_contract_creation_and_hmac_signature(self):
        """Tests that creating a scope contract properly generates an HMAC-SHA256 signature."""
        contract = create_scope_contract(
            targets=["127.0.0.1", "192.168.1.0/24", "lab.internal"],
            network_scope="authorized_lab",
            time_window="8h",
            allowed_tool_tiers=[1, 2],
            authorized_by="secops_lead@kairo.internal",
            db_path=self.db_path,
        )

        self.assertIsNotNone(contract["contract_id"])
        self.assertTrue(contract["signature_valid"])
        self.assertGreater(contract["seconds_remaining"], 0)
        self.assertFalse(contract["is_expired"])
        self.assertEqual(contract["allowed_tool_tiers"], [1, 2])

        # Verify active scope retrieval
        active = get_active_scope_contract(self.db_path)
        self.assertIsNotNone(active)
        self.assertEqual(active["contract_id"], contract["contract_id"])
        self.assertTrue(active["signature_valid"])

    def test_signature_tamper_detection(self):
        """Tests that modifying any scope parameter breaks cryptographic verification."""
        contract = create_scope_contract(
            targets=["192.168.1.0/24"],
            network_scope="authorized_lab",
            time_window="4h",
            allowed_tool_tiers=[1, 2],
            authorized_by="secops_lead@kairo.internal",
            db_path=self.db_path,
        )

        # 1. Unmodified should be valid
        self.assertTrue(verify_scope_signature(contract))

        # 2. Tamper with targets by adding an unauthorized IP
        tampered_contract = dict(contract)
        tampered_contract["targets"] = ["192.168.1.0/24", "8.8.8.8"]
        self.assertFalse(verify_scope_signature(tampered_contract))

        # 3. Tamper with allowed tiers
        tampered_contract2 = dict(contract)
        tampered_contract2["allowed_tool_tiers"] = [1, 2, 3]
        self.assertFalse(verify_scope_signature(tampered_contract2))

        # 4. Tamper with authorized_by
        tampered_contract3 = dict(contract)
        tampered_contract3["authorized_by"] = "attacker@external.com"
        self.assertFalse(verify_scope_signature(tampered_contract3))

    def test_target_boundary_matching(self):
        """Tests subnet CIDR containment, exact hostnames, and wildcard domain matching."""
        allowed = ["127.0.0.1", "192.168.1.0/24", "target.local", "*.corp.internal"]

        # Valid targets
        self.assertTrue(is_target_in_scope("127.0.0.1", allowed))
        self.assertTrue(is_target_in_scope("http://127.0.0.1:8080/test", allowed))
        self.assertTrue(is_target_in_scope("192.168.1.55", allowed))
        self.assertTrue(is_target_in_scope("192.168.1.254:443", allowed))
        self.assertTrue(is_target_in_scope("target.local", allowed))
        self.assertTrue(is_target_in_scope("api.corp.internal", allowed))
        self.assertTrue(is_target_in_scope("staging.corp.internal", allowed))

        # Out-of-scope targets
        self.assertFalse(is_target_in_scope("10.0.0.1", allowed))
        self.assertFalse(is_target_in_scope("192.168.2.1", allowed))
        self.assertFalse(is_target_in_scope("google.com", allowed))
        self.assertFalse(is_target_in_scope("corp.external", allowed))

    def test_tool_tier_classification(self):
        """Tests tool tier assignments (Tier 1 = passive, Tier 2 = active scan, Tier 3 = intrusive/exec)."""
        self.assertEqual(get_tool_tier("whois.lookup.v1"), 1)
        self.assertEqual(get_tool_tier("dig.lookup.v1"), 1)
        self.assertEqual(get_tool_tier("searchsploit.search.v1"), 1)
        self.assertEqual(get_tool_tier("hello_world"), 1)

        self.assertEqual(get_tool_tier("nmap.scan.v1"), 2)
        self.assertEqual(get_tool_tier("gobuster.dir.v1"), 2)
        self.assertEqual(get_tool_tier("ffuf.fuzz.v1"), 2)
        self.assertEqual(get_tool_tier("nikto.scan.v1"), 2)

        self.assertEqual(get_tool_tier("sqlmap.scan.v1"), 3)
        self.assertEqual(get_tool_tier("hydra.brute.v1"), 3)
        self.assertEqual(get_tool_tier("metasploit.rpc.v1"), 3)
        self.assertEqual(get_tool_tier("kali.exec.v1"), 3)
        self.assertEqual(get_tool_tier("shell.run.v1"), 3)

    def test_scope_validation_rejection_and_event_logging(self):
        """Tests that requests violating scope are rejected and logged to events.db."""
        # Create restrictive contract (only 192.168.1.0/24 and Tiers [1, 2])
        create_scope_contract(
            targets=["192.168.1.0/24"],
            network_scope="authorized_lab",
            time_window="4h",
            allowed_tool_tiers=[1, 2],
            authorized_by="secops_lead@kairo.internal",
            db_path=self.db_path,
        )

        agent = AgentLoop(db_path=self.db_path)

        # 1. Permitted execution (target in scope, Tier 1)
        res_ok = agent.execute_task(
            session_id="test_sess",
            message="Check hello_world on 192.168.1.10",
            task_id="task_ok",
            explicit_tool="hello_world",
            explicit_args={"input": "Hello", "target": "192.168.1.10"},
        )
        self.assertNotEqual(res_ok.get("status"), "rejected")

        # 2. Blocked by target boundary (target out of scope)
        res_bad_target = agent.execute_task(
            session_id="test_sess",
            message="Scan unauthorized target 10.0.0.99",
            task_id="task_bad_target",
            explicit_tool="hello_world",
            explicit_args={"input": "Hello", "target": "10.0.0.99"},
        )
        self.assertEqual(res_bad_target.get("status"), "rejected")
        self.assertEqual(res_bad_target.get("error"), "SCOPE_VIOLATION")
        self.assertIn("OUT_OF_SCOPE_TARGET", res_bad_target["scope_violation"]["reason"])

        # 3. Blocked by tool tier (Tier 3 tool shell.run.v1 when only Tiers [1, 2] allowed)
        res_bad_tier = agent.execute_task(
            session_id="test_sess",
            message="Run raw shell command on 192.168.1.50",
            task_id="task_bad_tier",
            explicit_tool="shell.run.v1",
            explicit_args={"command": "python", "args": ["-c", "print('test')"], "target": "192.168.1.50"},
        )
        self.assertEqual(res_bad_tier.get("status"), "rejected")
        self.assertEqual(res_bad_tier.get("error"), "SCOPE_VIOLATION")
        self.assertIn("TOOL_TIER_EXCEEDED", res_bad_tier["scope_violation"]["reason"])

        # 4. Verify rejection events logged in SQLite event store
        events = get_recent_events(limit=10, db_path=self.db_path)
        rejection_events = [e for e in events if e["actor"] == "gateway:scope_guard"]
        self.assertGreaterEqual(len(rejection_events), 2)
        
        # Verify event details
        for rev in rejection_events:
            self.assertEqual(rev["exit_code"], 403)
            self.assertIn("SCOPE_REJECTION", rev["result_summary"])

    def test_expired_scope_contract_rejection(self):
        """Tests that an expired scope contract blocks execution."""
        # Create an expired contract directly in DB
        now = datetime.now(timezone.utc)
        past_created = (now - timedelta(hours=5)).isoformat()
        past_expired = (now - timedelta(hours=1)).isoformat()

        payload = {
            "targets": ["192.168.1.0/24"],
            "network_scope": "authorized_lab",
            "time_window": "4h",
            "allowed_tool_tiers": [1, 2, 3],
            "authorized_by": "secops_lead@kairo.internal",
            "created_at": past_created,
            "expires_at": past_expired,
        }
        sig = generate_scope_signature(payload)

        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scope_contracts SET is_active = 0 WHERE is_active = 1")
            cursor.execute(
                """
                INSERT INTO scope_contracts (
                    contract_id, targets, network_scope, time_window,
                    allowed_tool_tiers, authorized_by, created_at, expires_at,
                    signature, is_active, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    "scope_expired_test",
                    json.dumps(payload["targets"]),
                    payload["network_scope"],
                    payload["time_window"],
                    json.dumps(payload["allowed_tool_tiers"]),
                    payload["authorized_by"],
                    past_created,
                    past_expired,
                    sig,
                    json.dumps({}),
                ),
            )
        conn.close()

        val = validate_scope_request(target="192.168.1.50", tool_id="hello_world", db_path=self.db_path)
        self.assertFalse(val["authorized"])
        self.assertIn("SCOPE_EXPIRED", val["reason"])


if __name__ == "__main__":
    unittest.main()
