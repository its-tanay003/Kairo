"""
Tests for Kairo Hybrid Tool-Selection Scoring Engine & Tool Memory Store.
Verifies:
1. Exact formula weights:
   Score(tool) = 0.30 semantic_fit + 0.20 capability_coverage +
                 0.15 environment_compatibility + 0.10 expected_signal +
                 0.10 reliability_history + 0.05 execution_cost + 0.10 prior_task_success
   Sum of weights = 1.00.
2. Top 3 candidate ranking & full score breakdown (not just picking top tool silently).
3. Raw empirical signals on every dimension (e.g. "succeeded 23/25 prior runs").
4. Tool Memory store persistence in SQLite (global system state per blueprint).
5. Dynamic update of reliability_history after tool execution.
6. FastAPI endpoints: POST /tools/select, GET /tools/memory, GET /tools/memory/{id}.
"""

import os
import sys
import unittest
import tempfile
import json

# Add repo root to sys.path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from orchestrator.tool_selector import (
    HybridToolSelector,
    WEIGHT_SEMANTIC_FIT,
    WEIGHT_CAPABILITY_COVERAGE,
    WEIGHT_ENVIRONMENT_COMPATIBILITY,
    WEIGHT_EXPECTED_SIGNAL,
    WEIGHT_RELIABILITY_HISTORY,
    WEIGHT_EXECUTION_COST,
    WEIGHT_PRIOR_TASK_SUCCESS,
    WEIGHTS,
)
from events.db import (
    init_db,
    get_tool_memory,
    list_tool_memories,
    record_tool_execution,
    seed_default_tool_memories,
    get_events_by_session,
)
from orchestrator.agent import AgentOrchestrator
from fastapi.testclient import TestClient
from orchestrator.server import app


class TestHybridToolSelectorFormula(unittest.TestCase):
    """Verifies the exact mathematical weights and score computations."""

    def test_weights_sum_to_one(self):
        """Assures sum of all 7 dimension weights strictly equals 1.00."""
        total = (
            WEIGHT_SEMANTIC_FIT
            + WEIGHT_CAPABILITY_COVERAGE
            + WEIGHT_ENVIRONMENT_COMPATIBILITY
            + WEIGHT_EXPECTED_SIGNAL
            + WEIGHT_RELIABILITY_HISTORY
            + WEIGHT_EXECUTION_COST
            + WEIGHT_PRIOR_TASK_SUCCESS
        )
        self.assertAlmostEqual(total, 1.0, places=5)
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=5)

    def test_weights_exact_coefficients(self):
        """Assures each dimension has the exact coefficient specified by the architecture."""
        self.assertEqual(WEIGHTS["semantic_fit"], 0.30)
        self.assertEqual(WEIGHTS["capability_coverage"], 0.20)
        self.assertEqual(WEIGHTS["environment_compatibility"], 0.15)
        self.assertEqual(WEIGHTS["expected_signal"], 0.10)
        self.assertEqual(WEIGHTS["reliability_history"], 0.10)
        self.assertEqual(WEIGHTS["execution_cost"], 0.05)
        self.assertEqual(WEIGHTS["prior_task_success"], 0.10)


class TestHybridToolSelectorEngine(unittest.TestCase):
    """Tests the tool selection algorithm, top 3 candidate ranking, and raw signals."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)
        self.selector = HybridToolSelector(db_path=self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_select_returns_top_3_candidates_with_full_breakdown(self):
        """Assures tool selector does NOT silently pick top tool, but returns top 3 with full breakdown."""
        result = self.selector.select(
            intent="Perform stealth port scan and service banner enumeration on target host 192.168.1.50",
            capability="network_scan",
            environment={"os": "linux", "vm_ready": True},
        )

        self.assertIsNotNone(result.selected_tool)
        self.assertGreaterEqual(len(result.candidates), 3)
        self.assertEqual(len(result.candidates), 3)

        # Check rankings
        self.assertEqual(result.candidates[0].rank, 1)
        self.assertEqual(result.candidates[1].rank, 2)
        self.assertEqual(result.candidates[2].rank, 3)

        # Assure monotonic descending order
        self.assertGreaterEqual(
            result.candidates[0].total_score, result.candidates[1].total_score
        )
        self.assertGreaterEqual(
            result.candidates[1].total_score, result.candidates[2].total_score
        )

        # Top candidate for port scan should be nmap
        self.assertIn("nmap", result.selected_tool.tool_id.lower())

    def test_all_seven_dimensions_present_with_raw_signals(self):
        """Assures every candidate contains all 7 labeled dimensions and raw empirical signals."""
        result = self.selector.select(
            intent="Brute-force discover hidden web directories and sensitive files on port 80",
            capability="web_enum",
        )

        for candidate in result.candidates:
            self.assertEqual(len(candidate.dimension_scores), 7)
            dimension_names = [d.name for d in candidate.dimension_scores]
            self.assertIn("semantic_fit", dimension_names)
            self.assertIn("capability_coverage", dimension_names)
            self.assertIn("environment_compatibility", dimension_names)
            self.assertIn("expected_signal", dimension_names)
            self.assertIn("reliability_history", dimension_names)
            self.assertIn("execution_cost", dimension_names)
            self.assertIn("prior_task_success", dimension_names)

            for dim in candidate.dimension_scores:
                self.assertIsNotNone(dim.raw_signal)
                self.assertGreater(len(dim.raw_signal.strip()), 0)
                # Verify weighted_score calculation
                self.assertAlmostEqual(
                    dim.weighted_score, dim.score * dim.weight, places=4
                )

    def test_reliability_history_signal_format(self):
        """Assures reliability_history raw signal outputs empirical run counts (e.g. 'succeeded 23/25 prior runs')."""
        result = self.selector.select(
            intent="Scan subnet for open ports",
            capability="network_scan",
        )

        nmap_cand = next(
            (c for c in result.candidates if "nmap" in c.tool_id), result.candidates[0]
        )
        rel_dim = next(
            d for d in nmap_cand.dimension_scores if d.name == "reliability_history"
        )

        self.assertIn("succeeded", rel_dim.raw_signal.lower())
        self.assertIn("prior runs", rel_dim.raw_signal.lower())


class TestToolMemoryStore(unittest.TestCase):
    """Tests SQLite persistence and dynamic update of Tool Memory store."""

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

    def test_seeded_tool_memories(self):
        """Assures default tool memory baselines are seeded into the SQLite store."""
        memories = list_tool_memories(self.temp_db_path)
        self.assertGreaterEqual(len(memories), 15)

        nmap_mem = get_tool_memory("nmap.network_scan.v1", self.temp_db_path)
        self.assertIsNotNone(nmap_mem)
        self.assertEqual(nmap_mem["tool_id"], "nmap.network_scan.v1")
        self.assertEqual(nmap_mem["total_runs"], 25)
        self.assertEqual(nmap_mem["successful_runs"], 23)
        self.assertAlmostEqual(nmap_mem["reliability_score"], 0.92, places=2)

    def test_record_tool_execution_success_updates_reliability(self):
        """Assures executing a tool increments total runs, successful runs, and recalculates score."""
        tool_id = "test.custom_tool.v1"
        # Record initial execution
        rec1 = record_tool_execution(
            tool_id=tool_id,
            status="success",
            duration_ms=500,
            db_path=self.temp_db_path,
        )
        self.assertEqual(rec1["total_runs"], 1)
        self.assertEqual(rec1["successful_runs"], 1)
        self.assertEqual(rec1["failed_runs"], 0)
        self.assertEqual(rec1["reliability_score"], 1.0)
        self.assertEqual(rec1["last_status"], "success")

        # Record a second execution (failure)
        rec2 = record_tool_execution(
            tool_id=tool_id,
            status="failed",
            duration_ms=300,
            db_path=self.temp_db_path,
        )
        self.assertEqual(rec2["total_runs"], 2)
        self.assertEqual(rec2["successful_runs"], 1)
        self.assertEqual(rec2["failed_runs"], 1)
        self.assertEqual(rec2["reliability_score"], 0.5)
        self.assertEqual(rec2["last_status"], "failed")

    def test_agent_orchestrator_updates_tool_memory_on_execution(self):
        """Assures AgentOrchestrator records execution into Tool Memory and returns tool_selection."""
        agent = AgentOrchestrator(db_path=self.temp_db_path)

        # Check initial runs for whois
        initial_mem = get_tool_memory("whois.lookup.v1", self.temp_db_path)
        initial_runs = initial_mem["total_runs"] if initial_mem else 0

        # Execute a fast task
        res = agent.execute_task(
            message="whois.lookup.v1: domain=example.com",
            session_id="test_session_mem",
            explicit_tool="whois.lookup.v1",
            explicit_args={"domain": "example.com"},
        )

        self.assertIn("tool_selection", res)
        self.assertIsNotNone(res["tool_selection"])
        self.assertIn("candidates", res["tool_selection"])

        # Check updated tool memory
        updated_mem = get_tool_memory("whois.lookup.v1", self.temp_db_path)
        self.assertIsNotNone(updated_mem)
        self.assertEqual(updated_mem["total_runs"], initial_runs + 1)


class TestFastApiToolEndpoints(unittest.TestCase):
    """Tests the HTTP API endpoints in orchestrator/server.py."""

    def setUp(self):
        self.client = TestClient(app)

    def test_post_tools_select_endpoint(self):
        """Tests POST /tools/select returns top 3 candidates and full score breakdown."""
        payload = {
            "intent": "Find hidden directories on target web server",
            "capability": "web_enum",
        }
        resp = self.client.post("/tools/select", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("selected_tool", data)
        self.assertIn("candidates", data)
        self.assertEqual(len(data["candidates"]), 3)
        self.assertIn("selection_reason", data)
        self.assertIn("weights_used", data)

        top_tool = data["selected_tool"]
        self.assertIn("dimension_scores", top_tool)
        self.assertEqual(len(top_tool["dimension_scores"]), 7)

    def test_get_tools_memory_endpoint(self):
        """Tests GET /tools/memory returns seeded tool list."""
        resp = self.client.get("/tools/memory")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tools", data)
        self.assertGreater(data["count"], 0)

    def test_get_single_tool_memory_endpoint(self):
        """Tests GET /tools/memory/{id} returns single tool record."""
        resp = self.client.get("/tools/memory/nmap.network_scan.v1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["tool_id"], "nmap.network_scan.v1")
        self.assertGreaterEqual(data["reliability_score"], 0.9)


if __name__ == "__main__":
    unittest.main()
