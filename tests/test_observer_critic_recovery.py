"""
Unit and Integration Test Suite for Observer, Critic, and Recovery Agent.

Verifies:
1. Observer: Converts raw tool output -> structured observation facts, reusing Task 1.3 parsers.
2. Critic: Checks whether latest observation moved the task graph toward the goal; flags no-progress state.
3. Recovery Agent: Handles timeout, malformed args, missing tool, parser mismatch.
4. Recovery Cap: Strictly caps attempts at 3 per node and surfaces failure rather than looping silently.
5. Cognitive Engine: End-to-end execution loop.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import init_db, insert_plan, PlanDAG, PlanNode, get_plan, seed_default_scope_contract
from orchestrator.observer import observer, ObservationResult, ObservationFact
from orchestrator.critic import critic, CritiqueResult
from orchestrator.recovery_agent import recovery_agent, RecoveryPlan
from orchestrator.cognitive_engine import cognitive_engine


class TestObserver(unittest.TestCase):
    """Verifies that the Observer converts raw outputs to structured facts reusing adapters."""

    def test_observer_nmap_xml(self):
        xml_data = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.1.50" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.2p1"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache httpd" version="2.4.41"/>
      </port>
    </ports>
  </host>
</nmaprun>"""
        obs = observer.observe(
            tool_id="nmap.scan.v1",
            stdout=xml_data,
            stderr="",
            exit_code=0,
            meta={"inputs": {"target": "192.168.1.50"}},
            duration_ms=1200.0,
        )

        self.assertEqual(obs.status, "success")
        self.assertTrue(obs.has_findings)
        self.assertFalse(obs.is_empty)
        self.assertEqual(obs.facts.hosts, ["192.168.1.50"])
        self.assertEqual(len(obs.facts.ports), 2)
        self.assertEqual(obs.facts.ports[0]["port"], 22)
        self.assertEqual(obs.facts.ports[0]["service"], "ssh")
        self.assertEqual(obs.facts.ports[1]["port"], 80)
        self.assertIn("Apache httpd 2.4.41", obs.facts.technologies)
        self.assertIn("Discovered 2 open port(s)", obs.summary)

    def test_observer_gobuster(self):
        gobuster_stdout = """
===============================================================
Gobuster v3.5
===============================================================
Found: /admin (Status: 301) [Size: 178] -> http://192.168.1.50/admin/
Found: /login (Status: 200) [Size: 2450]
Found: /api (Status: 200) [Size: 520]
===============================================================
"""
        obs = observer.observe(
            tool_id="gobuster.dir.v1",
            stdout=gobuster_stdout,
            stderr="",
            exit_code=0,
            meta={"inputs": {"url": "http://192.168.1.50"}},
        )

        self.assertEqual(obs.status, "success")
        self.assertTrue(obs.has_findings)
        self.assertEqual(len(obs.facts.endpoints), 3)
        self.assertEqual(obs.facts.endpoints[0]["path"], "/admin")
        self.assertEqual(obs.facts.endpoints[1]["path"], "/login")
        self.assertIn("Discovered 3 web endpoint(s)", obs.summary)

    def test_observer_sqlmap(self):
        sqlmap_stdout = """
[*] starting @ 12:00:00
[INFO] testing connection to the target URL
sqlmap identified the following injection point(s) with a total of 56 HTTP(s) requests:
---
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1 AND 5821=5821
---
[INFO] the back-end DBMS is MySQL
web server operating system: Linux Ubuntu
[*] shutting down
"""
        obs = observer.observe(
            tool_id="sqlmap.scan.v1",
            stdout=sqlmap_stdout,
            stderr="",
            exit_code=0,
            meta={"inputs": {"url": "http://192.168.1.50/vuln.php?id=1"}},
        )

        self.assertEqual(obs.status, "success")
        self.assertTrue(obs.has_findings)
        self.assertTrue(len(obs.facts.vulnerabilities) >= 1)
        self.assertEqual(obs.facts.vulnerabilities[0]["id"], "SQLI")
        self.assertEqual(obs.facts.vulnerabilities[0]["parameter"], "id")
        self.assertIn("DBMS: MySQL", obs.facts.technologies)

    def test_observer_parser_mismatch_fallback(self):
        """When an adapter fails to parse or output is malformed, fallback extraction recovers facts."""
        malformed_stdout = """
Starting Port Scan...
Discovered open port: 8080/tcp open http-proxy Squid http proxy 3.5.27
Discovered open port: 3306/tcp open mysql MySQL 5.7.33
Found: /secret.php (Status: 200)
Vulnerability: CVE-2021-41773 detected
login: admin password: password123
"""
        # Pass to nmap adapter which expects XML, triggering text/regex fallback
        obs = observer.observe(
            tool_id="nmap.scan.v1",
            stdout=malformed_stdout,
            stderr="",
            exit_code=0,
            meta={"inputs": {"target": "192.168.1.50"}},
        )

        self.assertTrue(obs.has_findings)
        self.assertTrue(len(obs.facts.ports) >= 2)
        port_numbers = [p["port"] for p in obs.facts.ports]
        self.assertIn(8080, port_numbers)
        self.assertIn(3306, port_numbers)
        self.assertTrue(any(v["id"] == "CVE-2021-41773" for v in obs.facts.vulnerabilities))
        self.assertTrue(len(obs.facts.credentials) >= 1)
        self.assertEqual(obs.facts.credentials[0]["username"], "admin")

    def test_observer_empty_output(self):
        obs = observer.observe(
            tool_id="nmap.scan.v1",
            stdout="",
            stderr="",
            exit_code=0,
            meta={"inputs": {"target": "192.168.1.50"}},
        )
        self.assertTrue(obs.is_empty)
        self.assertFalse(obs.has_findings)
        self.assertEqual(obs.facts.total_facts_count(), 0)


class TestCritic(unittest.TestCase):
    """Verifies that the Critic evaluates progress toward goal and flags no-progress states."""

    def setUp(self):
        self.node = {
            "node_id": "scan_ports",
            "capability": "network_port_scan",
            "label": "Network Port Discovery",
            "description": "Scan 192.168.1.50 for open TCP ports",
            "assigned_tool": "nmap.scan.v1",
        }

    def test_critic_confirms_progress(self):
        obs = ObservationResult(
            tool_id="nmap.scan.v1",
            exit_code=0,
            status="success",
            summary="Discovered 2 open port(s)",
            facts=ObservationFact(
                hosts=["192.168.1.50"],
                ports=[{"port": 80, "service": "http", "state": "open"}],
            ),
            raw_observation={},
            has_findings=True,
            is_empty=False,
        )

        critique = critic.evaluate(
            node=self.node,
            plan_goal="Assess attack surface of 192.168.1.50",
            observation=obs,
        )

        self.assertTrue(critique.has_progress)
        self.assertEqual(critique.status, "progress")
        self.assertEqual(critique.recommendation, "advance")
        self.assertGreater(critique.score, 0.8)

    def test_critic_flags_no_progress_empty_results(self):
        obs = ObservationResult(
            tool_id="nmap.scan.v1",
            exit_code=0,
            status="success",
            summary="0 open ports discovered",
            facts=ObservationFact(),
            raw_observation={},
            has_findings=False,
            is_empty=True,
        )

        critique = critic.evaluate(
            node=self.node,
            plan_goal="Assess attack surface of 192.168.1.50",
            observation=obs,
        )

        self.assertFalse(critique.has_progress)
        self.assertEqual(critique.status, "no_progress")
        self.assertTrue(critique.is_stagnant)
        self.assertIn("Task graph has not progressed", critique.critique)
        self.assertIn("Expand port range", critique.suggested_action)

    def test_critic_flags_no_progress_on_timeout(self):
        obs = ObservationResult(
            tool_id="nmap.scan.v1",
            exit_code=124,
            status="timeout",
            summary="Tool exceeded execution timeout budget",
            facts=ObservationFact(),
            raw_observation={},
            has_findings=False,
            is_empty=True,
        )

        critique = critic.evaluate(
            node=self.node,
            plan_goal="Assess attack surface",
            observation=obs,
        )

        self.assertFalse(critique.has_progress)
        self.assertEqual(critique.status, "no_progress")
        self.assertIn("timed out", critique.critique)

    def test_critic_flags_circular_stagnation(self):
        fact = ObservationFact(ports=[{"port": 80, "service": "http"}])
        obs = ObservationResult(
            tool_id="nmap.scan.v1",
            exit_code=0,
            status="success",
            summary="Discovered port 80",
            facts=fact,
            raw_observation={},
            has_findings=True,
            is_empty=False,
        )
        prev = [{"facts": fact.to_dict()}]

        critique = critic.evaluate(
            node=self.node,
            plan_goal="Assess attack surface",
            observation=obs,
            previous_observations=prev,
        )

        self.assertFalse(critique.has_progress)
        self.assertEqual(critique.status, "no_progress")
        self.assertTrue(critique.is_circular)
        self.assertIn("Circular state detected", critique.critique)


class TestRecoveryAgent(unittest.TestCase):
    """Verifies error classification, schema repair, tool switching, and 3-attempt cap."""

    def setUp(self):
        recovery_agent.reset_node("test_plan", "node_1")
        self.node = {
            "node_id": "node_1",
            "capability": "web_directory_enum",
            "label": "Web Directory Enumeration",
            "description": "Fuzz web directories on 192.168.1.50",
            "assigned_tool": "gobuster.dir.v1",
        }

    def test_recovery_timeout_strategy(self):
        plan = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=self.node,
            current_tool="gobuster.dir.v1",
            current_args={"url": "http://192.168.1.50", "timeout_ms": 10000},
            stdout="",
            stderr="execution timed out",
            exit_code=124,
            timed_out=True,
        )

        self.assertTrue(plan.can_recover)
        self.assertEqual(plan.attempt, 1)
        self.assertEqual(plan.error_type, "timeout")
        self.assertEqual(plan.strategy, "retry_timeout")
        self.assertGreater(plan.repaired_args["timeout_ms"], 10000)

    def test_recovery_missing_tool_selects_alternate(self):
        plan = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=self.node,
            current_tool="gobuster.dir.v1",
            current_args={"url": "http://192.168.1.50"},
            stdout="",
            stderr="gobuster: command not found",
            exit_code=127,
        )

        self.assertTrue(plan.can_recover)
        self.assertEqual(plan.error_type, "missing_tool")
        self.assertEqual(plan.strategy, "switch_tool")
        # Tool selector should select alternate tool like ffuf
        self.assertNotEqual(plan.tool_id, "gobuster.dir.v1")
        self.assertIn(plan.tool_id, ["ffuf.fuzz.v1", "whatweb.scan.v1", "nikto.scan.v1", "hello_world"])

    def test_recovery_malformed_args_repair(self):
        # Missing http scheme, invalid extra parameter
        bad_args = {
            "url": "192.168.1.50",
            "invalid_flag_xyz": 12345,
        }
        plan = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=self.node,
            current_tool="gobuster.dir.v1",
            current_args=bad_args,
            stdout="",
            stderr="Error: invalid option --invalid_flag_xyz",
            exit_code=1,
        )

        self.assertTrue(plan.can_recover)
        self.assertEqual(plan.error_type, "malformed_args")
        self.assertEqual(plan.strategy, "repair_args")
        self.assertTrue(plan.repaired_args["url"].startswith("http://"))
        self.assertNotIn("invalid_flag_xyz", plan.repaired_args)

    def test_recovery_cap_enforcement_at_3_attempts(self):
        """Strictly caps recovery attempts per node at 3 before failing and surfacing to user."""
        recovery_agent.reset_node("test_plan", "node_cap")
        node_cap = {"node_id": "node_cap", "capability": "network_port_scan"}

        # Attempt 1
        p1 = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="timeout",
            exit_code=124,
            timed_out=True,
        )
        self.assertTrue(p1.can_recover)
        self.assertEqual(p1.attempt, 1)

        # Attempt 2
        p2 = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="timeout",
            exit_code=124,
            timed_out=True,
        )
        self.assertTrue(p2.can_recover)
        self.assertEqual(p2.attempt, 2)

        # Attempt 3 -> Cap Exceeded!
        p3 = recovery_agent.formulate_recovery(
            plan_id="test_plan",
            node=node_cap,
            current_tool="nmap.scan.v1",
            current_args={"target": "10.0.0.1"},
            stdout="",
            stderr="timeout",
            exit_code=124,
            timed_out=True,
        )
        self.assertFalse(p3.can_recover)
        self.assertEqual(p3.attempt, 3)
        self.assertEqual(p3.error_type, "cap_exceeded")
        self.assertEqual(p3.strategy, "abort_cap_exceeded")
        self.assertTrue(p3.failure_surfaced_to_user)
        self.assertIn("RECOVERY_EXHAUSTED", p3.reason)


class TestCognitiveEngine(unittest.TestCase):
    """End-to-end execution of a node through CognitiveEngine."""

    def setUp(self):
        init_db()
        seed_default_scope_contract()

    def test_execute_node_success(self):
        plan = PlanDAG(
            plan_id="cog_plan_1",
            session_id="cog_session",
            goal="Test host live detection",
            nodes=[
                PlanNode(
                    node_id="n1",
                    capability="host_live_detection",
                    label="Ping Diagnostic",
                    dependencies=[],
                )
            ],
        )
        insert_plan(plan)
        saved_plan = get_plan("cog_plan_1")
        contract = {
            "allowed_tool_tiers": [1, 2, 3],
            "targets": ["127.0.0.1"],
        }

        res = cognitive_engine.execute_node(
            plan_id="cog_plan_1",
            node=saved_plan["nodes"][0],
            plan=saved_plan,
            contract=contract,
            max_attempts=3,
        )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["attempts"] >= 1)
        self.assertIn("observation", res)
        self.assertIn("critique", res)
        self.assertTrue(res["critique"]["has_progress"])


if __name__ == "__main__":
    unittest.main()
