"""
Tests for Kairo Autonomous DAG Execution Controller.

Verifies:
1. EvidenceContext parsing and accumulation (ports, services, URLs, technologies, findings).
2. Prerequisite Evidence Gates:
   - Blocking web tools when no web listeners are detected.
   - Allowing web tools when HTTP/HTTPS ports are open.
   - Blocking brute force when no authentication services are discovered.
   - Blocking vulnerability correlation when no service banners/ports are present.
   - Halting when host is offline.
3. Tool Selection & Intelligent Fallback:
   - Capability-to-adapter resolution.
   - Fallback execution when primary tool fails, recording recovery lineage.
4. Argument Resolution from Upstream Evidence Context.
5. Autonomous Multi-Step Plan Execution:
   - Full DAG lifecycle (topological ordering, ready node execution).
   - Downstream tools executing automatically without user manual intervention.
   - Skipped node dependency cascading.
   - Markdown synthesis report generation.
6. AgentLoop & Server Integration:
   - AgentLoop.run_autonomous_task
   - FastAPI endpoint POST /planner/plans/{plan_id}/run
   - FastAPI endpoint POST /planner/run
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from events.db import (
    create_scope_contract,
    get_plan,
    init_db,
    insert_plan,
)
from orchestrator.adapters.base import ToolObservation
from orchestrator.agent import AgentLoop
from orchestrator.dag_controller import (
    DAGExecutionResult,
    EvidenceContext,
    check_prerequisite_evidence,
    dag_controller,
    resolve_node_arguments,
    select_tool_for_node,
)
from orchestrator.planner import PlanDAG, PlanNode
from orchestrator.server import app


def setup_test_scope(db_path):
    return create_scope_contract(
        targets=["10.10.10.50", "10.10.10.0/24", "192.168.1.10", "192.168.1.0/24", "127.0.0.1", "http://10.10.10.50:80"],
        network_scope="internal",
        time_window="24h",
        allowed_tool_tiers=[1, 2, 3],
        authorized_by="security_admin",
        db_path=db_path,
    )


class TestEvidenceContextAndGating(unittest.TestCase):
    """Tests the accumulation of evidence facts and prerequisite evidence gates."""

    def test_evidence_context_port_and_service_parsing(self):
        ctx = EvidenceContext(target="10.10.10.50")
        sample_output = """
        Starting Nmap 7.94 ( https://nmap.org )
        Nmap scan report for 10.10.10.50
        PORT     STATE SERVICE VERSION
        22/tcp   open  ssh     OpenSSH 8.2p1 Ubuntu 4ubuntu0.5
        80/tcp   open  http    Apache httpd 2.4.41 ((Ubuntu))
        443/tcp  open  ssl/http Apache httpd 2.4.41
        8080/tcp open  http-proxy
        """
        ctx.update_from_observation("nmap.scan.v1", sample_output)

        self.assertIn(22, ctx.open_ports)
        self.assertIn(80, ctx.open_ports)
        self.assertIn(443, ctx.open_ports)
        self.assertIn(8080, ctx.open_ports)

        # Web URLs should be automatically populated
        self.assertTrue(any("http://10.10.10.50" in u for u in ctx.web_urls))
        self.assertTrue(any("https://10.10.10.50" in u for u in ctx.web_urls))
        self.assertTrue(any("8080" in u for u in ctx.web_urls))

        # Check service banners
        self.assertTrue(ctx.has_auth_service())
        self.assertTrue(ctx.has_web_presence())

    def test_evidence_context_web_enumeration_parsing(self):
        ctx = EvidenceContext(target="http://example.com")
        gobuster_output = """
        ===============================================================
        Gobuster v3.5
        ===============================================================
        /admin                (Status: 301) [Size: 178] [--> /admin/]
        /login                (Status: 200) [Size: 1540]
        /api/v1               (Status: 200) [Size: 52]
        /secret.txt           (Status: 200) [Size: 34]
        """
        ctx.update_from_observation("gobuster.dir.v1", gobuster_output)

        self.assertIn("/admin", ctx.web_endpoints)
        self.assertIn("/login", ctx.web_endpoints)
        self.assertIn("/api/v1", ctx.web_endpoints)
        self.assertIn("/secret.txt", ctx.web_endpoints)

    def test_prerequisite_gate_blocks_web_tools_without_web_listener(self):
        """Web tools must be blocked/skipped if recon discovered 0 web listeners."""
        node = {
            "node_id": "dir_fuzz_1",
            "capability": "web_directory_enumeration",
            "tool_assigned": "gobuster.dir.v1",
            "target": "192.168.1.10",
        }
        # Context with ONLY ssh open, no web listener
        ctx = EvidenceContext(target="192.168.1.10", open_ports=[22], services=["OpenSSH 8.2"])

        can_run, reason = check_prerequisite_evidence(node, ctx)
        self.assertFalse(can_run)
        self.assertIn("No open web ports", reason)

    def test_prerequisite_gate_allows_web_tools_with_web_listener(self):
        """Web tools must be allowed once port 80/443 or http service is discovered."""
        node = {
            "node_id": "dir_fuzz_1",
            "capability": "web_directory_enumeration",
            "tool_assigned": "gobuster.dir.v1",
            "target": "192.168.1.10",
        }
        ctx = EvidenceContext(
            target="192.168.1.10",
            open_ports=[22, 80],
            services=["OpenSSH 8.2", "Apache httpd"],
            web_urls=["http://192.168.1.10:80/"],
        )

        can_run, reason = check_prerequisite_evidence(node, ctx)
        self.assertTrue(can_run)
        self.assertIn("Satisfied", reason)

    def test_prerequisite_gate_blocks_brute_force_without_auth_service(self):
        """Hydra brute forcing must be blocked if no SSH/FTP/SMB authentication listener exists."""
        node = {
            "node_id": "brute_ssh",
            "capability": "credential_testing",
            "tool_assigned": "hydra.brute.v1",
            "target": "192.168.1.10",
        }
        # Only web port open
        ctx = EvidenceContext(target="192.168.1.10", open_ports=[80], services=["Apache httpd"])

        can_run, reason = check_prerequisite_evidence(node, ctx)
        self.assertFalse(can_run)
        self.assertIn("authentication services", reason)

    def test_prerequisite_gate_blocks_service_fingerprint_when_no_ports_open(self):
        """Fingerprinting must be skipped if port scan concluded 0 open ports."""
        node = {
            "node_id": "svc_scan",
            "capability": "service_version_fingerprint",
            "tool_assigned": "nmap.scan.v1",
            "target": "192.168.1.10",
        }
        ctx = EvidenceContext(target="192.168.1.10", open_ports=[])

        can_run, reason = check_prerequisite_evidence(node, ctx)
        self.assertFalse(can_run)
        self.assertIn("No open ports", reason)

    def test_prerequisite_gate_blocks_when_host_offline(self):
        """Controller must halt further exploration if host is known to be offline."""
        node = {
            "node_id": "port_scan",
            "capability": "network_port_scan",
            "tool_assigned": "nmap.scan.v1",
            "target": "192.168.1.10",
        }
        ctx = EvidenceContext(target="192.168.1.10", host_alive=False)

        can_run, reason = check_prerequisite_evidence(node, ctx)
        self.assertFalse(can_run)
        self.assertIn("Host is reported offline", reason)


class TestToolSelectionAndArgumentResolution(unittest.TestCase):
    """Tests tool mapping, fallback resolution, and argument synthesis."""

    def test_select_tool_for_node_capability(self):
        node = {"capability": "web_directory_enumeration", "tool_assigned": None}
        tool = select_tool_for_node(node)
        self.assertEqual(tool, "gobuster.dir.v1")

        node2 = {"capability": "network_port_scan"}
        tool2 = select_tool_for_node(node2)
        self.assertEqual(tool2, "nmap.scan.v1")

    def test_resolve_arguments_injects_evidence_facts(self):
        node = {
            "node_id": "dir_fuzz",
            "capability": "web_directory_enumeration",
            "tool_assigned": "gobuster.dir.v1",
            "arguments": {},
            "target": "10.0.0.5",
        }
        ctx = EvidenceContext(
            target="10.0.0.5",
            open_ports=[8080],
            web_urls=["http://10.0.0.5:8080"],
        )

        args = resolve_node_arguments(node, "gobuster.dir.v1", ctx)
        self.assertEqual(args.get("url"), "http://10.0.0.5:8080")
        self.assertIn("wordlist", args)


class TestAutonomousDAGExecution(unittest.TestCase):
    """Tests end-to-end multi-step DAG execution with mocked tool adapters."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)

        setup_test_scope(self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_autonomous_execution_completes_dag_in_topological_order(self):
        """
        Creates a 3-step DAG:
          1. Port Scan (discovers port 80)
          2. Web Dir Enumeration (depends on 1, discovers /admin)
          3. Tech Fingerprint (depends on 2)
        All steps should execute autonomously without user intervention.
        """
        plan_id = "plan_full_dag_test"
        nodes = [
            PlanNode(
                node_id="scan_ports",
                label="Port Scan",
                capability="network_port_scan",
                description="Scan target ports",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="enum_dirs",
                label="Directory Fuzzing",
                capability="web_directory_enumeration",
                description="Enumerate web directories",
                dependencies=["scan_ports"],
                status="queued",
            ),
            PlanNode(
                node_id="fingerprint_tech",
                label="Tech Fingerprint",
                capability="web_technology_fingerprint",
                description="Fingerprint web technologies",
                dependencies=["enum_dirs"],
                status="queued",
            ),
        ]
        dag = PlanDAG(
            plan_id=plan_id,
            goal="Full security recon of 10.10.10.50",
            nodes=nodes,
            session_id="sess_test_dag",
        )
        insert_plan(dag, db_path=self.temp_db_path)

        def mock_executor(tool_name, arguments):
            if "nmap" in tool_name:
                return {
                    "exit_code": 0,
                    "stdout": "PORT 80/tcp open http Apache httpd 2.4.41\nPORT 22/tcp open ssh",
                    "stderr": "",
                    "duration_ms": 150.0,
                    "observation": {"open_ports": [80, 22]},
                    "artifacts": [],
                }
            elif "gobuster" in tool_name:
                return {
                    "exit_code": 0,
                    "stdout": "/admin (Status: 200)\n/dashboard (Status: 302)",
                    "stderr": "",
                    "duration_ms": 200.0,
                    "observation": {"endpoints": ["/admin", "/dashboard"]},
                    "artifacts": [],
                }
            elif "whatweb" in tool_name:
                return {
                    "exit_code": 0,
                    "stdout": "Apache[2.4.41], PHP[7.4.3], Bootstrap[4.5.0]",
                    "stderr": "",
                    "duration_ms": 100.0,
                    "observation": {"technologies": ["Apache 2.4.41", "PHP 7.4.3"]},
                    "artifacts": [],
                }
            return {"exit_code": 0, "stdout": "ok", "stderr": "", "observation": {}}

        result = dag_controller.execute_plan(
            plan_id=plan_id,
            session_id="sess_test_dag",
            target="10.10.10.50",
            goal="Full security recon of 10.10.10.50",
            agent_executor=mock_executor,
            db_path=self.temp_db_path,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.nodes_executed, 3)
        self.assertEqual(result.nodes_failed, 0)
        self.assertEqual(result.nodes_skipped, 0)

        # Verify evidence accumulated
        self.assertIn(80, result.evidence_context.open_ports)
        self.assertIn("/admin", result.evidence_context.web_endpoints)

        # Verify plan state in DB is marked completed
        db_plan = get_plan(plan_id, db_path=self.temp_db_path)
        self.assertEqual(db_plan["status"], "completed")
        for node in db_plan["nodes"]:
            self.assertEqual(node["status"], "success")

        # Verify markdown synthesis was generated
        self.assertIn("# Security Assessment Synthesis", result.synthesis_report)
        self.assertIn("10.10.10.50", result.synthesis_report)

    def test_autonomous_execution_cascades_skip_when_prerequisite_fails(self):
        """
        If port scan finds NO web ports (only port 22 open), web directory enumeration
        must be skipped, and its downstream dependency must also be safely handled.
        """
        plan_id = "plan_skip_cascade_test"
        nodes = [
            PlanNode(
                node_id="scan_ports",
                label="Port Scan",
                capability="network_port_scan",
                description="Scan target ports",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="enum_dirs",
                label="Directory Fuzzing",
                capability="web_directory_enumeration",
                description="Enumerate web directories",
                dependencies=["scan_ports"],
                status="queued",
            ),
        ]
        dag = PlanDAG(
            plan_id=plan_id,
            goal="Scan 10.10.10.50",
            nodes=nodes,
            session_id="sess_test_skip",
        )
        insert_plan(dag, db_path=self.temp_db_path)

        def mock_executor(tool_name, arguments):
            if "nmap" in tool_name:
                # Only SSH open, NO web ports!
                return {
                    "exit_code": 0,
                    "stdout": "PORT 22/tcp open ssh OpenSSH 8.2",
                    "stderr": "",
                    "duration_ms": 100.0,
                    "observation": {"open_ports": [22]},
                    "artifacts": [],
                }
            return {"exit_code": 0, "stdout": "ok", "stderr": "", "observation": {}}

        result = dag_controller.execute_plan(
            plan_id=plan_id,
            session_id="sess_test_skip",
            target="10.10.10.50",
            goal="Scan 10.10.10.50",
            agent_executor=mock_executor,
            db_path=self.temp_db_path,
        )

        # enum_dirs should have been skipped due to prerequisite evidence gate!
        self.assertEqual(result.nodes_executed, 1)
        self.assertEqual(result.nodes_skipped, 1)

        db_plan = get_plan(plan_id, db_path=self.temp_db_path)
        nodes_dict = {n["node_id"]: n for n in db_plan["nodes"]}
        self.assertEqual(nodes_dict["scan_ports"]["status"], "success")
        self.assertEqual(nodes_dict["enum_dirs"]["status"], "skipped")

    def test_fallback_tool_on_failure_with_recovery_lineage(self):
        """
        When primary tool (e.g. gobuster) fails, controller attempts fallback tool
        (e.g. whatweb) and records recovery lineage.
        """
        plan_id = "plan_fallback_test"
        nodes = [
            PlanNode(
                node_id="web_recon",
                label="Web Recon",
                capability="web_directory_enumeration",
                description="Web directory discovery",
                dependencies=[],
                status="queued",
            ),
        ]
        dag = PlanDAG(
            plan_id=plan_id,
            goal="Web scan",
            nodes=nodes,
            session_id="sess_fallback",
        )
        insert_plan(dag, db_path=self.temp_db_path)

        call_counts = {"gobuster.dir.v1": 0, "whatweb.scan.v1": 0}

        def mock_executor(tool_name, arguments):
            call_counts[tool_name] = call_counts.get(tool_name, 0) + 1
            if tool_name == "gobuster.dir.v1":
                return {
                    "exit_code": 1,
                    "stdout": "Error: Gobuster timed out",
                    "stderr": "Connection timed out",
                    "duration_ms": 500.0,
                    "observation": {},
                }
            elif tool_name == "whatweb.scan.v1":
                return {
                    "exit_code": 0,
                    "stdout": "Fallback discovery success: Apache 2.4.41",
                    "stderr": "",
                    "duration_ms": 120.0,
                    "observation": {"technologies": ["Apache 2.4.41"]},
                }
            return {"exit_code": 0, "stdout": "ok", "stderr": "", "observation": {}}

        from orchestrator import tool_selector as ts_mod

        original_affinities = ts_mod.CAPABILITY_TOOL_AFFINITY.copy()
        # Ensure fallback candidate is whatweb.scan.v1
        ts_mod.CAPABILITY_TOOL_AFFINITY["web_directory_enumeration"] = [
            "gobuster.dir.v1",
            "whatweb.scan.v1",
        ]

        try:
            result = dag_controller.execute_plan(
                plan_id=plan_id,
                session_id="sess_fallback",
                target="http://10.10.10.50:80",
                agent_executor=mock_executor,
                db_path=self.temp_db_path,
            )

            # Both primary and fallback were invoked
            self.assertEqual(call_counts["gobuster.dir.v1"], 1)
            self.assertEqual(call_counts["whatweb.scan.v1"], 1)
            self.assertTrue(result.success)
            self.assertGreaterEqual(len(result.recovery_lineage), 1)
            self.assertEqual(result.recovery_lineage[0]["tool_attempted"], "gobuster.dir.v1")
        finally:
            ts_mod.CAPABILITY_TOOL_AFFINITY = original_affinities


class TestAgentLoopAutonomousIntegration(unittest.TestCase):
    """Tests AgentLoop autonomous task handling."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)

        setup_test_scope(self.temp_db_path)

        self.agent = AgentLoop(db_path=self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_run_autonomous_task_executes_entire_plan_to_completion(self):
        """Verifies that calling run_autonomous_task decomposes and runs all steps."""
        class MockAdapter:
            tool_id = "mock.tool.v1"
            tool_version = "1.0.0"

            def execute(self, inputs, task_id, target="vm"):
                return ToolObservation(
                    tool_id="mock.tool.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="PORT 80/tcp open http\nPORT 22/tcp open ssh",
                    raw_stderr="",
                    duration_ms=100.0,
                    observation={"open_ports": [80, 22]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockAdapter):
            result = self.agent.run_autonomous_task(
                goal="Assess attack surface for 10.10.10.50",
                session_id="sess_agent_auto",
            )

        self.assertIn("plan_id", result)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["nodes_executed"], 1)
        self.assertIn("synthesis", result)
        self.assertIn("10.10.10.50", result["synthesis"])


class TestServerPlannerEndpoints(unittest.TestCase):
    """Tests FastAPI HTTP endpoints for autonomous DAG execution."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)

        setup_test_scope(self.temp_db_path)

        from orchestrator.server import agent
        agent.db_path = self.temp_db_path
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_post_planner_plans_run_endpoint(self):
        """POST /planner/plans/{plan_id}/run should autonomously run an existing plan."""
        plan_id = "plan_http_test"
        nodes = [
            PlanNode(
                node_id="scan_1",
                label="Port Scan",
                capability="network_port_scan",
                description="Scan target",
                dependencies=[],
                status="queued",
            )
        ]
        dag = PlanDAG(
            plan_id=plan_id,
            goal="Test HTTP run",
            nodes=nodes,
            session_id="sess_http",
        )
        insert_plan(dag, db_path=self.temp_db_path)

        class MockAdapter:
            tool_id = "nmap.scan.v1"
            tool_version = "1.0.0"

            def execute(self, inputs, task_id, target="vm"):
                return ToolObservation(
                    tool_id="nmap.scan.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="PORT 80/tcp open http",
                    raw_stderr="",
                    duration_ms=100.0,
                    observation={"open_ports": [80]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockAdapter):
            resp = self.client.post(
                f"/planner/plans/{plan_id}/run",
                json={"target": "10.10.10.50", "max_steps": 10},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["plan_id"], plan_id)
        self.assertTrue(data["success"])
        self.assertEqual(data["nodes_executed"], 1)

    def test_post_planner_run_decomposes_and_executes_goal(self):
        """POST /planner/run decomposes goal and runs end-to-end."""
        class MockAdapter:
            tool_id = "mock.tool.v1"
            tool_version = "1.0.0"

            def execute(self, inputs, task_id, target="vm"):
                return ToolObservation(
                    tool_id="mock.tool.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="PORT 80/tcp open http",
                    raw_stderr="",
                    duration_ms=100.0,
                    observation={"open_ports": [80]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockAdapter):
            resp = self.client.post(
                "/planner/run",
                json={"goal": "Scan 10.10.10.50", "session_id": "sess_e2e_run"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("plan_id", data)
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["nodes_executed"], 1)


if __name__ == "__main__":
    unittest.main()
