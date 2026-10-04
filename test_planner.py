"""
Tests for Kairo Planner Component (Task Graph DAG Engine).
Verifies:
1. Natural language goal decomposition into a Directed Acyclic Graph (DAG).
2. Parallel root execution (non-linear branching: independent recon axes).
3. Multi-parent convergence (correlation nodes waiting on multiple upstream axes).
4. Cycle rejection (Kahn's algorithm validation).
5. Event Store SQLite persistence (task_graphs and task_nodes tables).
6. Node status transitions (queued -> running -> success/warning/failed).
7. Ready nodes computation (topological dependency resolution).
8. Orchestrator FastAPI planner endpoints.
"""

import os
import sys
import unittest
import tempfile

# Add repo root to sys.path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from orchestrator.planner import (
    Planner,
    PlanNode,
    PlanDAG,
    validate_dag,
    PLANNER_SYSTEM_PROMPT,
)
from events.db import (
    init_db,
    insert_plan,
    get_plan,
    list_plans,
    update_node_status,
    get_ready_nodes,
)
from fastapi.testclient import TestClient
from orchestrator.server import app


class TestPlannerEngine(unittest.TestCase):
    """Tests the Planner core graph generation and validation logic."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)
        self.planner = Planner(db_path=self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_planner_system_prompt_mandates_dag(self):
        """Assures the planner system prompt explicitly forbids linear lists and requires DAG."""
        prompt = PLANNER_SYSTEM_PROMPT.lower()
        self.assertIn("directed acyclic graph", prompt)
        self.assertIn("parallel", prompt)
        self.assertIn("convergence", prompt)
        self.assertIn("single linear list", prompt)
        self.assertIn("pentestgpt", prompt)
        self.assertIn("hexstrike", prompt)

    def test_dag_validation_valid_graph(self):
        """Tests that a well-formed DAG with parallel branches and convergence passes validation."""
        nodes = [
            PlanNode(
                node_id="node_1",
                label="Port Scan",
                capability="network_port_scan",
                description="Scan open TCP/UDP ports",
                dependencies=[],
            ),
            PlanNode(
                node_id="node_2",
                label="DNS & Virtual Host Discovery",
                capability="dns_subdomain_discovery",
                description="Discover subdomains and virtual hosts",
                dependencies=[],
            ),
            PlanNode(
                node_id="node_3",
                label="Web Directory Enumeration",
                capability="web_directory_enum",
                description="Enumerate hidden paths on discovered web service",
                dependencies=["node_1"],
            ),
            PlanNode(
                node_id="node_4",
                label="Multi-Vector Correlation",
                capability="vulnerability_correlation",
                description="Correlate web endpoints and open services",
                dependencies=["node_2", "node_3"],  # Multi-parent convergence!
            ),
        ]

        is_valid, err, depths = validate_dag(nodes)
        self.assertTrue(is_valid, f"Expected valid DAG but got: {err}")
        self.assertEqual(len(depths), 4)
        self.assertEqual(depths["node_1"], 0)
        self.assertEqual(depths["node_2"], 0)
        self.assertEqual(depths["node_3"], 1)
        self.assertEqual(depths["node_4"], 2)

    def test_dag_validation_rejects_cycles(self):
        """Tests that cyclical dependencies are strictly rejected."""
        nodes = [
            PlanNode(
                node_id="node_1",
                label="Task 1",
                capability="cap_1",
                description="Task 1",
                dependencies=["node_2"],  # Depends on node_2
            ),
            PlanNode(
                node_id="node_2",
                label="Task 2",
                capability="cap_2",
                description="Task 2",
                dependencies=["node_1"],  # Depends on node_1 -> CYCLE!
            ),
        ]

        is_valid, err, depths = validate_dag(nodes)
        self.assertFalse(is_valid)
        self.assertIn("cycle", err.lower())

    def test_dag_validation_rejects_missing_dependency(self):
        """Tests that dependencies pointing to non-existent nodes are rejected."""
        nodes = [
            PlanNode(
                node_id="node_1",
                label="Task 1",
                capability="cap_1",
                description="Task 1",
                dependencies=["non_existent_node"],
            )
        ]
        is_valid, err, _ = validate_dag(nodes)
        self.assertFalse(is_valid)
        self.assertIn("non-existent", err)

    def test_decompose_goal_fallback_dag_structure(self):
        """Tests decomposition produces a genuine non-linear DAG with parallel branches and convergence."""
        goal = "Conduct penetration test on target 192.168.1.50 with web assessment and SSH audit."
        plan = self.planner.decompose(goal=goal, session_id="test_sess_01", prefer_llm=False)

        self.assertIsInstance(plan, dict)
        self.assertIn("plan_id", plan)
        self.assertTrue(plan.get("is_dag"))
        nodes = plan["nodes"]
        self.assertGreaterEqual(len(nodes), 4)

        # Check parallel roots (at least 2 nodes with dependencies == [])
        roots = [n for n in nodes if len(n["dependencies"]) == 0]
        self.assertGreaterEqual(
            len(roots),
            2,
            f"Expected at least 2 parallel root nodes, got {len(roots)}: {[r['node_id'] for r in roots]}",
        )

        # Check convergence node (at least 1 node with len(dependencies) >= 2)
        convergences = [n for n in nodes if len(n["dependencies"]) >= 2]
        self.assertGreaterEqual(
            len(convergences),
            1,
            f"Expected at least 1 convergence node, got {len(convergences)}",
        )

        # Check abstract capabilities (ensure no raw tool commands like 'nmap -sV')
        for node in nodes:
            cap = node["capability"]
            self.assertFalse(cap.startswith("nmap "), f"Found raw tool in capability: {cap}")
            self.assertFalse(cap.startswith("gobuster "), f"Found raw tool in capability: {cap}")
            self.assertIn("_", cap, f"Capability should be standardized snake_case: {cap}")


class TestEventStorePlanPersistence(unittest.TestCase):
    """Tests SQLite persistence of task graphs and task nodes."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_insert_and_get_plan(self):
        """Tests inserting a full PlanDAG and retrieving it with all nodes."""
        nodes = [
            PlanNode(
                node_id="node_1",
                label="Recon 1",
                capability="network_port_scan",
                description="Scan ports",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="node_2",
                label="Recon 2",
                capability="web_directory_enum",
                description="Enumerate dirs",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="node_3",
                label="Correlation",
                capability="vulnerability_correlation",
                description="Correlate findings",
                dependencies=["node_1", "node_2"],
                status="queued",
            ),
        ]

        plan_dag = PlanDAG(
            plan_id="plan_test_01",
            session_id="session_persist_1",
            goal="Comprehensive security assessment",
            nodes=nodes,
            status="created",
            created_at="2026-10-04T12:00:00Z",
        )

        ok = insert_plan(plan_dag, db_path=self.temp_db_path)
        self.assertTrue(ok)

        # Retrieve plan
        retrieved = get_plan("plan_test_01", db_path=self.temp_db_path)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["plan_id"], "plan_test_01")
        self.assertEqual(retrieved["total_nodes"], 3)
        self.assertEqual(len(retrieved["nodes"]), 3)
        self.assertEqual(retrieved["parallel_roots"], ["node_1", "node_2"])
        self.assertEqual(retrieved["convergence_nodes"], ["node_3"])

        # Check list plans
        plans_list = list_plans(limit=10, db_path=self.temp_db_path)
        self.assertEqual(len(plans_list), 1)
        self.assertEqual(plans_list[0]["plan_id"], "plan_test_01")

    def test_update_node_status_and_ready_resolution(self):
        """Tests that ready nodes dynamically update as upstream dependencies succeed."""
        nodes = [
            PlanNode(node_id="A", label="A", capability="cap_a", description="A", dependencies=[]),
            PlanNode(node_id="B", label="B", capability="cap_b", description="B", dependencies=[]),
            PlanNode(node_id="C", label="C", capability="cap_c", description="C", dependencies=["A", "B"]),
        ]
        plan_dag = PlanDAG(
            plan_id="plan_deps_test",
            session_id="sess_dep",
            goal="Test dependency resolution",
            nodes=nodes,
            status="created",
            created_at="2026-10-04T12:00:00Z",
        )
        insert_plan(plan_dag, db_path=self.temp_db_path)

        # Step 1: Initially, only A and B have 0 dependencies and should be ready
        ready = get_ready_nodes("plan_deps_test", db_path=self.temp_db_path)
        ready_ids = [r["node_id"] for r in ready]
        self.assertIn("A", ready_ids)
        self.assertIn("B", ready_ids)
        self.assertNotIn("C", ready_ids)

        # Step 2: Mark A as 'success'
        update_node_status("plan_deps_test", "A", "success", db_path=self.temp_db_path)
        ready = get_ready_nodes("plan_deps_test", db_path=self.temp_db_path)
        ready_ids = [r["node_id"] for r in ready]
        self.assertNotIn("A", ready_ids)  # A is no longer queued
        self.assertIn("B", ready_ids)      # B is still queued and ready
        self.assertNotIn("C", ready_ids)  # C is waiting on B!

        # Step 3: Mark B as 'running'
        update_node_status("plan_deps_test", "B", "running", db_path=self.temp_db_path)
        ready = get_ready_nodes("plan_deps_test", db_path=self.temp_db_path)
        ready_ids = [r["node_id"] for r in ready]
        self.assertNotIn("B", ready_ids)  # B is running
        self.assertNotIn("C", ready_ids)  # C cannot start until B succeeds!

        # Step 4: Mark B as 'success'
        update_node_status("plan_deps_test", "B", "success", db_path=self.temp_db_path)
        ready = get_ready_nodes("plan_deps_test", db_path=self.temp_db_path)
        ready_ids = [r["node_id"] for r in ready]
        self.assertIn("C", ready_ids)  # C is now UNBLOCKED and ready to execute in parallel!


class TestOrchestratorPlannerEndpoints(unittest.TestCase):
    """Tests the FastAPI planner routes."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_decompose_endpoint(self):
        resp = self.client.post(
            "/planner/decompose",
            json={
                "goal": "Scan network 10.10.10.0/24 and enumerate web services in parallel",
                "session_id": "test_endpoint_session",
                "prefer_llm": False,
            },
        )
        self.assertEqual(resp.status_code, 200, f"Error: {resp.text}")
        data = resp.json()
        self.assertIn("plan_id", data)
        self.assertTrue(data.get("is_dag"))
        self.assertGreaterEqual(len(data.get("nodes", [])), 3)

        plan_id = data["plan_id"]

        # Test GET /planner/plans/{plan_id}
        get_resp = self.client.get(f"/planner/plans/{plan_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["plan_id"], plan_id)

        # Test GET /planner/plans/{plan_id}/ready
        ready_resp = self.client.get(f"/planner/plans/{plan_id}/ready")
        self.assertEqual(ready_resp.status_code, 200)
        ready_data = ready_resp.json()
        self.assertGreaterEqual(ready_data["ready_count"], 1)

        # Test POST node status update
        first_node_id = data["nodes"][0]["node_id"]
        status_resp = self.client.post(
            f"/planner/plans/{plan_id}/nodes/{first_node_id}/status",
            json={"status": "running", "result": {"test": True}},
        )
        self.assertEqual(status_resp.status_code, 200)
        updated_plan = status_resp.json()
        node = next(n for n in updated_plan["nodes"] if n["node_id"] == first_node_id)
        self.assertEqual(node["status"], "running")


if __name__ == "__main__":
    unittest.main()
