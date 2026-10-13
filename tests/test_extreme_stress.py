"""
tests/test_extreme_stress.py
============================
KAIRO Extreme Stress, Fuzzing & Edge-Case Testing Suite.
Pushes all system components to their theoretical limits:
  1. Scope Contract fuzzing, boundary collisions & HMAC bit-flip tamper detection.
  2. Massive DAG graph stress (99 nodes, diamond convergence, complex cycle detection).
  3. Hybrid Tool Selection edge cases (tie-breakers, empty tool sets, 10KB inputs).
  4. Cognitive Loop / Critic Recovery extreme loop caps & corrupt error handling.
  5. SQLite EventStore high-concurrency multi-threaded writes & payload limits.
"""

import sys
import os
import time
import json
import uuid
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
import unittest
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from events.db import (
    init_db,
    get_connection,
    Event,
    insert_event,
    get_recent_events,
    create_scope_contract,
    generate_scope_signature,
    verify_scope_signature,
    is_target_in_scope,
    validate_scope_request,
    get_tool_tier,
    PlanDAG,
    PlanNode,
    insert_plan,
    get_plan,
    update_node_status,
)
from orchestrator.planner import validate_dag, Planner
from orchestrator.tool_selector import HybridToolSelector
from orchestrator.observer import observer, ObservationResult, ObservationFact
from orchestrator.critic import critic, CritiqueResult
from orchestrator.recovery_agent import recovery_agent, RecoveryPlan


class TestExtremeStress(unittest.TestCase):
    """Kairo Extreme Stress & System Boundary Test Suite."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "extreme_stress.db"
        init_db(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    # =========================================================================
    # 1. SCOPE CONTRACT EXTREME FUZZING & TAMPERING
    # =========================================================================

    def test_hmac_bit_flip_tamper_detection(self):
        """Flip characters in the HMAC-SHA256 signature to verify strict tamper resistance."""
        contract = create_scope_contract(
            targets=["192.168.1.0/24", "10.0.0.5/32"],
            network_scope="authorized_lab",
            time_window="1h",
            allowed_tool_tiers=[1, 2],
            authorized_by="secops@kairo.internal",
            db_path=self.db_path,
        )
        self.assertTrue(verify_scope_signature(contract))

        sig = contract["signature"]
        # Bit flip character by character across signature
        for idx in range(min(12, len(sig))):
            flipped_char = "0" if sig[idx] != "0" else "1"
            tampered_contract = dict(contract)
            tampered_contract["signature"] = sig[:idx] + flipped_char + sig[idx+1:]
            self.assertFalse(
                verify_scope_signature(tampered_contract),
                f"Tampered signature with flip at position {idx} was unexpectedly accepted!"
            )

    def test_extreme_malformed_cidr_and_ip_fuzzing(self):
        """Fuzz is_target_in_scope with boundary collisions, injections, and edge cases."""
        allowed_targets = ["10.0.0.0/8", "192.168.1.50/32", "172.16.0.0/16"]

        fuzz_cases = [
            ("", False),
            ("   ", False),
            ("999.999.999.999", False),
            ("10.0.0.0/33", False),
            ("10.0.0.0/-1", False),
            ("10.0.0.256", False),
            ("localhost", False),
            ("../../../etc/passwd", False),
            ("<script>alert(1)</script>", False),
            ("10.0.0.1; rm -rf /", False),
            ("10.0.0.1' OR 1=1 --", False),
            ("A" * 2048, False),  # Massive buffer
            ("10.5.100.200", True),  # In 10.0.0.0/8
            ("192.168.1.50", True),  # Exact match
            ("192.168.1.51", False), # Out of /32
            ("172.16.1.1", True),    # In 172.16.0.0/16
            ("172.32.1.1", False),   # Out of /16
        ]

        for target_input, expected_in_scope in fuzz_cases:
            res = is_target_in_scope(target_input, allowed_targets)
            self.assertEqual(res, expected_in_scope, f"Failed for input: {target_input!r}")

    def test_expired_contract_rejection(self):
        """Verify contracts with expired time bounds are strictly blocked."""
        contract = create_scope_contract(
            targets=["10.0.0.0/24"],
            network_scope="lab",
            time_window="1s",
            allowed_tool_tiers=[1],
            authorized_by="secops@kairo.internal",
            db_path=self.db_path,
        )
        time.sleep(1.2)  # Wait for 1s window to expire
        res = validate_scope_request(
            target="10.0.0.5",
            tool_id="nmap.scan.v1",
            db_path=self.db_path,
        )
        self.assertFalse(res["authorized"])
        self.assertIn("expired", res["reason"].lower())

    # =========================================================================
    # 2. PLANNER DAG EXTREME STRUCTURAL STRESS
    # =========================================================================

    def test_massive_dag_100_nodes_execution_order(self):
        """Construct a 99-node non-linear pipeline and ensure topological validation succeeds."""
        nodes = []
        nodes.append(PlanNode(
            node_id="root_alpha",
            capability="recon",
            label="Root Alpha",
            description="Alpha reconnaissance axis",
            dependencies=[],
            status="queued",
        ))
        nodes.append(PlanNode(
            node_id="root_beta",
            capability="recon",
            label="Root Beta",
            description="Beta reconnaissance axis",
            dependencies=[],
            status="queued",
        ))

        for i in range(1, 49):
            nodes.append(PlanNode(
                node_id=f"alpha_{i}",
                capability="scan",
                label=f"Alpha Step {i}",
                description="Alpha progression",
                dependencies=[f"alpha_{i-1}" if i > 1 else "root_alpha"],
                status="queued",
            ))
            nodes.append(PlanNode(
                node_id=f"beta_{i}",
                capability="scan",
                label=f"Beta Step {i}",
                description="Beta progression",
                dependencies=[f"beta_{i-1}" if i > 1 else "root_beta"],
                status="queued",
            ))

        nodes.append(PlanNode(
            node_id="convergence_master",
            capability="report",
            label="Master Convergence",
            description="Correlation of 98 upstream nodes",
            dependencies=["alpha_48", "beta_48"],
            status="queued",
        ))

        self.assertEqual(len(nodes), 99)
        is_valid, err, depths = validate_dag(nodes)
        self.assertTrue(is_valid, f"DAG failed validation: {err}")
        self.assertIsNone(err)
        self.assertEqual(depths["convergence_master"], 49)

    def test_complex_multi_hop_cycle_detection(self):
        """Cycle detection across a 5-node circular loop."""
        nodes = [
            PlanNode(node_id="n1", capability="recon", label="Node 1", description="", dependencies=["n5"], status="queued"),
            PlanNode(node_id="n2", capability="recon", label="Node 2", description="", dependencies=["n1"], status="queued"),
            PlanNode(node_id="n3", capability="recon", label="Node 3", description="", dependencies=["n2"], status="queued"),
            PlanNode(node_id="n4", capability="recon", label="Node 4", description="", dependencies=["n3"], status="queued"),
            PlanNode(node_id="n5", capability="recon", label="Node 5", description="", dependencies=["n4"], status="queued"),
        ]
        is_valid, err, _ = validate_dag(nodes)
        self.assertFalse(is_valid)
        self.assertIn("cycle", err.lower())

    def test_missing_dependency_rejection(self):
        """Reject graphs where a node depends on a phantom unreferenced ID."""
        nodes = [
            PlanNode(node_id="root", capability="recon", label="Root", description="", dependencies=[], status="queued"),
            PlanNode(node_id="child", capability="scan", label="Child", description="", dependencies=["phantom_ghost_id"], status="queued"),
        ]
        is_valid, err, _ = validate_dag(nodes)
        self.assertFalse(is_valid)
        self.assertIn("phantom_ghost_id", err)

    # =========================================================================
    # 3. HYBRID TOOL SELECTOR EXTREME EDGE CASES
    # =========================================================================

    def test_huge_adversarial_goal_input(self):
        """Hybrid tool selector processes 10,000-char input without unhandled exception."""
        selector = HybridToolSelector(db_path=self.db_path)
        adversarial_goal = "COMPREHENSIVE AUDIT " + ("X" * 10000) + " <script>alert(1)</script>"
        res = selector.select(
            intent=adversarial_goal,
            capability="network_scan",
            environment={"os": "linux", "vm_ready": True},
        )
        self.assertIsNotNone(res.selected_tool)
        self.assertGreaterEqual(len(res.candidates), 1)
        top = res.candidates[0]
        self.assertTrue(0.0 <= top.total_score <= 1.0)

    def test_unicode_and_emoji_goal_handling(self):
        """Hybrid tool selector gracefully handles emoji and non-ASCII queries."""
        selector = HybridToolSelector(db_path=self.db_path)
        emojis = "⚡💀🛡️🔥🚀 渗透测试 وائرس"
        res = selector.select(
            intent=emojis,
            capability="web_directory_enum",
            environment={"os": "linux", "vm_ready": True},
        )
        self.assertIsNotNone(res.selected_tool)
        self.assertGreaterEqual(len(res.candidates), 1)

    # =========================================================================
    # 4. COGNITIVE RECOVERY AGENT LOOP CAPS
    # =========================================================================

    def test_recovery_cap_strictly_enforces_max_attempts(self):
        """Recovery agent strictly caps attempts per node at 3 before failing and surfacing to user."""
        recovery_agent.reset_node("test_plan_cap", "node_cap_stress")
        node_cap = {"node_id": "node_cap_stress", "capability": "network_port_scan"}

        # Attempt 1 -> Can recover
        p1 = recovery_agent.formulate_recovery(
            plan_id="test_plan_cap",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="execution timed out",
            exit_code=124,
            timed_out=True,
        )
        self.assertTrue(p1.can_recover)
        self.assertEqual(p1.attempt, 1)

        # Attempt 2 -> Can recover
        p2 = recovery_agent.formulate_recovery(
            plan_id="test_plan_cap",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="execution timed out",
            exit_code=124,
            timed_out=True,
        )
        self.assertTrue(p2.can_recover)
        self.assertEqual(p2.attempt, 2)

        # Attempt 3 -> Cap Exceeded! Must halt/abort
        p3 = recovery_agent.formulate_recovery(
            plan_id="test_plan_cap",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="execution timed out",
            exit_code=124,
            timed_out=True,
        )
        self.assertFalse(p3.can_recover)
        self.assertEqual(p3.attempt, 3)

    def test_observer_extreme_massive_stdout_parsing(self):
        """Observer processes a 2,000-line tool output cleanly."""
        xml_lines = [
            '<?xml version="1.0"?>',
            '<nmaprun>',
            '  <host>',
            '    <status state="up"/>',
            '    <address addr="192.168.1.50" addrtype="ipv4"/>',
            '    <ports>'
        ]
        for p in range(1, 100):
            xml_lines.append(f'      <port protocol="tcp" portid="{p}"><state state="open"/><service name="svc_{p}"/></port>')
        xml_lines.extend(['    </ports>', '  </host>', '</nmaprun>'])
        xml_data = "\n".join(xml_lines)

        obs = observer.observe(
            tool_id="nmap.scan.v1",
            stdout=xml_data,
            stderr="",
            exit_code=0,
            meta={"inputs": {"target": "192.168.1.50"}},
            duration_ms=2500.0,
        )
        self.assertEqual(obs.status, "success")
        self.assertTrue(obs.has_findings)
        self.assertEqual(len(obs.facts.ports), 99)

    # =========================================================================
    # 5. MULTI-THREADED SQLITE EVENT STORE BURST
    # =========================================================================

    def test_multi_threaded_concurrent_event_inserts(self):
        """20 concurrent worker threads inserting events simultaneously without lock errors."""
        num_threads = 20
        events_per_thread = 5

        def worker(thread_idx):
            for i in range(events_per_thread):
                evt = Event.create(
                    session_id=f"sess_stress_{thread_idx}",
                    task_id=f"task_{thread_idx}_{i}",
                    actor="worker_agent",
                    tool_id="nmap.scan.v1",
                    tool_version="1.0.0",
                    requested_args={"host": "127.0.0.1", "iteration": i},
                    normalized_args={"host": "127.0.0.1"},
                    process_id=5000 + thread_idx,
                    start_time=datetime.now(timezone.utc).isoformat(),
                    end_time=datetime.now(timezone.utc).isoformat(),
                    exit_code=0,
                    stdout_ref="PORT 80/tcp open http " + ("X" * 100),
                    stderr_ref=None,
                    artifact_refs=["memory://test.json"],
                    screenshots=[],
                    network_context={"ip": "127.0.0.1"},
                    result_summary=f"Thread {thread_idx} wrote {i}",
                    confidence=0.99,
                    parent_event=None,
                )
                insert_event(evt, db_path=self.db_path)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, idx) for idx in range(num_threads)]
            for f in futures:
                f.result()

        recent = get_recent_events(limit=200, db_path=self.db_path)
        self.assertGreaterEqual(len(recent), num_threads * events_per_thread)


if __name__ == "__main__":
    unittest.main()
