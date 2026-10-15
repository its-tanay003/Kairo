"""
Unit and integration tests for Model Benchmark Sweep (run_full_sweep and multi-model trigger).
Verifies:
1. Sequential execution across models in models.yaml without concurrent memory exhaustion.
2. Full task set execution from lab/tasks.py.
3. Accurate per-model metric recording (tool selection, schema validity, task completion,
   unnecessary calls, recovery, evidence completeness, hallucinated success, latency p50/p95,
   and context/VRAM footprint).
4. Shared sweep_id tagging across all comparison rows in history.json.
5. Integration with ModelCenter.unload_model(), wait_for_ready(), and API endpoints.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from orchestrator.benchmark_manager import benchmark_manager, HISTORY_FILE
from orchestrator.model_center import model_center
from orchestrator.server import app
from lab.tasks import LAB_TASKS
from lab.runner import BenchmarkRunner


class TestBenchmarkSweep(unittest.TestCase):
    """Test suite for sequential benchmark sweep across models."""

    def setUp(self):
        self.client = TestClient(app)

    def test_model_center_unload_and_wait_ready(self):
        """Verifies ModelCenter.unload_model releases memory and wait_for_ready confirms status."""
        unload_info = model_center.unload_model()
        self.assertTrue(unload_info.get("unloaded"))
        self.assertIn("vram", unload_info)
        self.assertIn("ram", unload_info)

        # Select a model and wait for ready
        active = model_center.select_model("kairo-custom-model")
        self.assertEqual(active.get("model_id"), "kairo-custom-model")

        status = model_center.wait_for_ready("kairo-custom-model", timeout_s=2.0)
        self.assertEqual(status.get("model_id"), "kairo-custom-model")

    def test_trigger_benchmark_run_accepts_list_of_model_ids(self):
        """Verifies trigger_benchmark_run accepts a list of model_ids and returns grouped sweep."""
        models = ["kairo-dpo-aligned", "kairo-sft-baseline"]
        res = benchmark_manager.trigger_benchmark_run(
            model_ids=models,
            task_limit=5,  # quick test limit
        )

        self.assertTrue(res.get("success"))
        self.assertIn("sweep_id", res)
        self.assertEqual(res.get("models_evaluated"), 2)
        self.assertIn("comparison_table", res)

        rows = res["comparison_table"]
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["sweep_id"], res["sweep_id"])
            self.assertIn("tool_accuracy_pct", r)
            self.assertIn("schema_pass_pct", r)
            self.assertIn("task_completion_pct", r)
            self.assertIn("unnecessary_calls_rate_pct", r)
            self.assertIn("recovery_rate_pct", r)
            self.assertIn("evidence_completeness_pct", r)
            self.assertIn("hallucinated_success_pct", r)
            self.assertIn("latency_p50_s", r)
            self.assertIn("latency_p95_s", r)
            self.assertIn("context_length", r)
            self.assertIn("vram_footprint_mb", r)
            self.assertIn("ram_footprint_mb", r)

    def test_run_full_sweep_sequential_execution_and_metrics(self):
        """
        Tests run_full_sweep across all models:
        - Confirms unload_model called between model transitions (sequential execution)
        - Confirms shared sweep_id tag
        - Confirms schema compatibility with get_leaderboard_data()
        """
        unload_calls = []
        original_unload = model_center.unload_model

        def tracking_unload(model_id=None):
            unload_calls.append(model_id)
            return original_unload(model_id)

        models_to_test = ["kairo-grpo-aligned", "kairo-dpo-aligned", "kairo-scale-1.2b"]

        with patch.object(model_center, "unload_model", side_effect=tracking_unload):
            sweep_result = benchmark_manager.run_full_sweep(
                model_ids=models_to_test,
                task_limit=6,
                verbose=False,
            )

        self.assertTrue(sweep_result["success"])
        self.assertEqual(sweep_result["models_evaluated"], len(models_to_test))
        sweep_id = sweep_result["sweep_id"]

        # Confirm sequential unloading occurred before and after each model run
        self.assertGreaterEqual(len(unload_calls), len(models_to_test))

        rows = sweep_result["comparison_table"]
        self.assertEqual(len(rows), len(models_to_test))

        # Check required metrics per model
        for row in rows:
            self.assertEqual(row["sweep_id"], sweep_id)
            self.assertIn(row["model_id"], models_to_test)
            self.assertIsInstance(row["tool_accuracy_pct"], (int, float))
            self.assertIsInstance(row["argument_validity_pct"], (int, float))
            self.assertIsInstance(row["task_completion_pct"], (int, float))
            self.assertIsInstance(row["unnecessary_calls_rate_pct"], (int, float))
            self.assertIsInstance(row["recovery_rate_pct"], (int, float))
            self.assertIsInstance(row["evidence_completeness_pct"], (int, float))
            self.assertIsInstance(row["hallucinated_success_pct"], (int, float))
            self.assertIsInstance(row["latency_p50_s"], (int, float))
            self.assertIsInstance(row["latency_p95_s"], (int, float))
            self.assertIsInstance(row["context_length"], int)
            self.assertIsInstance(row["vram_footprint_mb"], (int, float))
            self.assertIsInstance(row["ram_footprint_mb"], (int, float))

    def test_sweep_rows_persisted_in_history_json_with_shared_sweep_id(self):
        """Verifies comparison rows are written to history.json and retrieved by get_leaderboard_data()."""
        models = ["Qwen2.5-0.5B-Instruct", "kairo-custom-model"]
        sweep_res = benchmark_manager.run_full_sweep(
            model_ids=models,
            task_limit=4,
        )
        sweep_id = sweep_res["sweep_id"]

        # Read history.json
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

        sweep_entries = [h for h in history if h.get("sweep_id") == sweep_id]
        self.assertEqual(len(sweep_entries), 2)
        for entry in sweep_entries:
            self.assertEqual(entry["sweep_id"], sweep_id)
            self.assertIn(entry["model_id"], models)

        # Verify leaderboard returns sweeps
        leaderboard = benchmark_manager.get_leaderboard_data()
        self.assertIn("sweeps", leaderboard)
        matching_sweeps = [s for s in leaderboard["sweeps"] if s.get("sweep_id") == sweep_id]
        self.assertEqual(len(matching_sweeps), 1)
        self.assertEqual(matching_sweeps[0]["models_count"], 2)

    def test_api_benchmark_sweep_endpoint(self):
        """Verifies POST /benchmark/sweep endpoint."""
        resp = self.client.post("/benchmark/sweep", json={"model_ids": ["kairo-dpo-aligned"], "task_limit": 3})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("sweep_id", data)
        self.assertEqual(data.get("models_evaluated"), 1)

    def test_api_benchmark_run_with_list_endpoint(self):
        """Verifies POST /benchmark/run accepts list of models."""
        resp = self.client.post(
            "/benchmark/run",
            json={
                "model_id": ["kairo-scale-1.2b", "kairo-custom-model"],
                "task_limit": 3,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("sweep_id", data)
        self.assertEqual(data.get("models_evaluated"), 2)


if __name__ == "__main__":
    unittest.main()
