"""
Comprehensive Test Suite for Task 2.7 Benchmark Expansion (50 Tasks),
Primary-Custom Model Wiring, Automatic Failover Router, and Model Memory Persistence.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lab.tasks import LAB_TASKS, LabTask, get_task_by_id, list_tasks
from orchestrator.model_center import model_center
from orchestrator.failover_router import FailoverRouter
from events.db import init_db, record_model_memory, get_model_memory_records, get_latest_model_memory, get_connection
from orchestrator.evidence_store import EvidenceClass


class TestBenchmarkExpansion(unittest.TestCase):
    """Verifies that the formal benchmark harness contains 50 tasks covering 18 tools."""

    def test_task_count_is_fifty(self):
        self.assertEqual(len(LAB_TASKS), 50, "Benchmark must contain 50 tasks (blueprint MVP 50-100 target).")

    def test_unique_sequential_ids(self):
        task_ids = [t.task_id for t in LAB_TASKS]
        self.assertEqual(len(task_ids), len(set(task_ids)), "Task IDs must be strictly unique.")
        for i in range(1, 51):
            expected = f"LAB-TASK-{i:02d}"
            self.assertIn(expected, task_ids)

    def test_all_eighteen_tools_covered(self):
        tool_families = {t.expected_tool_family.split(".")[0].lower() for t in LAB_TASKS}
        expected_lab_tools = {
            "nmap", "system_ping", "gobuster", "ffuf", "whatweb", "nikto",
            "sqlmap", "searchsploit", "metasploit", "hydra", "exiftool",
            "hashid", "dig", "whois", "tcpdump", "shell"
        }
        for tool in expected_lab_tools:
            self.assertIn(tool, tool_families, f"Tool '{tool}' must be covered by at least one task.")

    def test_failure_aware_recovery_challenges(self):
        recovery_tasks = [t for t in LAB_TASKS if t.recovery_challenge]
        self.assertEqual(len(recovery_tasks), 4, "Must have 4 failure-aware recovery challenge tasks.")
        recovery_ids = {t.task_id for t in recovery_tasks}
        self.assertEqual(recovery_ids, {"LAB-TASK-10", "LAB-TASK-16", "LAB-TASK-28", "LAB-TASK-36"})

        for t in recovery_tasks:
            self.assertIsNotNone(t.recovery_trigger)
            self.assertIn("attempt_1_tool", t.recovery_trigger)
            self.assertIn("attempt_2_tool", t.recovery_trigger)

    def test_all_tasks_have_evaluation_predicates(self):
        for t in LAB_TASKS:
            self.assertTrue(bool(t.task_id))
            self.assertTrue(bool(t.name))
            self.assertTrue(bool(t.objective))
            self.assertTrue(bool(t.expected_tool_family))
            self.assertIsInstance(t.expected_evidence_class, EvidenceClass)
            self.assertTrue(callable(t.evaluate_success))


class TestModelCenterWiring(unittest.TestCase):
    """Verifies that the custom model is wired as role=primary-custom and selectable."""

    def test_primary_custom_model_registered(self):
        status = model_center.get_status()
        catalog = status["models_catalog"]
        primary_custom = next((m for m in catalog if m.get("role") == "primary-custom"), None)
        self.assertIsNotNone(primary_custom, "primary-custom model must exist in catalog.")
        self.assertEqual(primary_custom["model_id"], "kairo-custom-model")
        self.assertEqual(primary_custom["runtime"], "transformers")
        self.assertEqual(primary_custom["context_length"], 8192)

    def test_select_model_by_role_primary_custom(self):
        selected = model_center.select_model("primary-custom")
        self.assertEqual(selected["role"], "primary-custom")
        self.assertEqual(selected["model_id"], "kairo-custom-model")

        active = model_center.get_active_model()
        self.assertEqual(active["model_id"], "kairo-custom-model")

    def test_select_model_by_role_fallback(self):
        selected = model_center.select_model("fallback")
        self.assertEqual(selected["role"], "fallback")
        self.assertEqual(selected["model_id"], "Qwen2.5-0.5B-Instruct")

        active = model_center.get_active_model()
        self.assertEqual(active["model_id"], "Qwen2.5-0.5B-Instruct")


class TestAutomaticFailoverRouter(unittest.TestCase):
    """Tests consecutive schema validation failures, thresholding, and automatic fallback failover."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_failover.db")
        init_db(self.db_path)
        # Ensure we start with primary-custom
        model_center.select_model("primary-custom")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_failure_does_not_trigger_failover(self):
        router = FailoverRouter(failure_threshold=2, db_path=self.db_path)
        router.reset(restore_role="primary-custom")

        # Record 1 failure (invalid arguments missing required url)
        res = router.handle_tool_call_output(
            tool_id="ffuf.fuzz.v1",
            arguments={"wordlist": "common.txt"},  # missing required url
            session_id="test_session",
            task_id="LAB-TASK-01",
        )
        self.assertFalse(res["valid"])
        self.assertFalse(res["failover_triggered"])
        self.assertFalse(router.failover_active)
        self.assertEqual(router.consecutive_schema_failures, 1)
        self.assertEqual(model_center.get_active_model()["role"], "primary-custom")

    def test_consecutive_failures_reach_threshold_triggers_failover(self):
        router = FailoverRouter(failure_threshold=2, db_path=self.db_path)
        router.reset(restore_role="primary-custom")

        # Failure 1
        res1 = router.handle_tool_call_output(
            tool_id="ffuf.fuzz.v1",
            arguments={"wordlist": "common.txt"},
            task_id="LAB-TASK-01",
        )
        self.assertFalse(res1["valid"])
        self.assertFalse(router.failover_active)

        # Failure 2 (triggers threshold >= 2)
        res2 = router.handle_tool_call_output(
            tool_id="whatweb.scan.v1",
            arguments={},  # missing required url
            task_id="LAB-TASK-02",
        )
        self.assertFalse(res2["valid"])
        self.assertTrue(res2["failover_triggered"])
        self.assertTrue(router.failover_active)
        self.assertEqual(res2["failed_model"], "kairo-custom-model")
        self.assertEqual(res2["fallback_model"], "Qwen2.5-0.5B-Instruct")
        self.assertEqual(res2["consecutive_failures"], 2)

        # Active model in ModelCenter must now be fallback
        active = model_center.get_active_model()
        self.assertEqual(active["role"], "fallback")
        self.assertEqual(active["model_id"], "Qwen2.5-0.5B-Instruct")

    def test_success_resets_consecutive_failures(self):
        router = FailoverRouter(failure_threshold=2, db_path=self.db_path)
        router.reset(restore_role="primary-custom")

        # Failure 1
        router.handle_tool_call_output(
            tool_id="ffuf.fuzz.v1",
            arguments={"wordlist": "common.txt"},
            task_id="LAB-TASK-01",
        )
        self.assertEqual(router.consecutive_schema_failures, 1)

        # Success resets count
        res_ok = router.handle_tool_call_output(
            tool_id="nmap.scan.v1",
            arguments={"target": "127.0.0.1"},
            task_id="LAB-TASK-02",
        )
        self.assertTrue(res_ok["valid"])
        self.assertEqual(router.consecutive_schema_failures, 0)
        self.assertFalse(router.failover_active)


class TestModelMemoryPersistence(unittest.TestCase):
    """Verifies model_memory record creation, querying, and schema compliance."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_memory.db")
        init_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_and_retrieve_model_memory(self):
        record_id = record_model_memory(
            model_id="kairo-custom-model",
            version="v1.0.0-sft",
            prompt_format="chatml",
            adapter="none-full-sft",
            benchmark_score=95.7,
            metrics={"tool_accuracy": 98.0, "schema_validity": 100.0, "recovery_rate": 100.0},
            metadata={"run_id": "bench_test_001", "commit": "29dc57b"},
            db_path=self.db_path,
        )
        self.assertGreater(record_id, 0)

        # Retrieve records
        records = get_model_memory_records("kairo-custom-model", db_path=self.db_path)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["model_id"], "kairo-custom-model")
        self.assertEqual(rec["version"], "v1.0.0-sft")
        self.assertEqual(rec["prompt_format"], "chatml")
        self.assertEqual(rec["adapter"], "none-full-sft")
        self.assertEqual(rec["benchmark_score"], 95.7)
        self.assertIn("tool_accuracy", rec["metrics"])
        self.assertEqual(rec["metrics"]["tool_accuracy"], 98.0)

        # Retrieve latest record
        latest = get_latest_model_memory("kairo-custom-model", db_path=self.db_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["id"], record_id)
        self.assertEqual(latest["benchmark_score"], 95.7)


if __name__ == "__main__":
    unittest.main()
