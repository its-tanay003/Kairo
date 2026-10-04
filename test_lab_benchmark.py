"""
Unit and integration tests for the Kairo Lab Environment, 10-Task Specification,
and Benchmark Runner (Evaluation Framework).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from lab.version import LAB_VERSION, LAB_SPEC_VERSION, ENVIRONMENT_NAME
from lab.tasks import LAB_TASKS, LabTask, get_task_by_id, list_tasks
from lab.targets import lab_targets, MiniDVWAHandler, MiniMetasploitableServer
from lab.runner import BenchmarkRunner, TaskBenchmarkResult
from orchestrator.evidence_store import EvidenceClass, NetworkEvidence, CommandEvidence, FileEvidence, AnalyticEvidence


class TestLabSpecifications(unittest.TestCase):
    """Verifies that the lab environment and task definitions meet the exact blueprint specs."""

    def test_version_metadata(self):
        self.assertEqual(LAB_VERSION, "1.0.0")
        self.assertEqual(LAB_SPEC_VERSION, "2026.1")
        self.assertTrue(len(ENVIRONMENT_NAME) > 0)

    def test_exactly_ten_tasks(self):
        self.assertEqual(len(LAB_TASKS), 10, "Lab environment must contain exactly 10 tasks.")

    def test_unique_task_ids(self):
        task_ids = [t.task_id for t in LAB_TASKS]
        self.assertEqual(len(task_ids), len(set(task_ids)), "All task IDs must be unique.")
        for idx in range(1, 11):
            expected_id = f"LAB-TASK-{idx:02d}"
            self.assertIn(expected_id, task_ids)

    def test_mandatory_blueprint_fields_per_task(self):
        """Each task must have: objective, expected tool family, expected evidence, success condition."""
        for t in LAB_TASKS:
            self.assertTrue(bool(t.task_id), f"{t} missing task_id")
            self.assertTrue(bool(t.name), f"{t} missing name")
            self.assertTrue(bool(t.objective), f"{t.task_id} missing objective")
            self.assertTrue(bool(t.expected_tool_family), f"{t.task_id} missing expected_tool_family")
            self.assertIsInstance(t.expected_evidence_class, EvidenceClass, f"{t.task_id} missing expected_evidence_class")
            self.assertTrue(bool(t.expected_evidence_spec), f"{t.task_id} missing expected_evidence_spec")
            self.assertTrue(callable(t.evaluate_success), f"{t.task_id} missing evaluate_success predicate")
            self.assertTrue(bool(t.simulated_raw_output), f"{t.task_id} missing simulated_raw_output")

    def test_task_retrieval_helpers(self):
        t1 = get_task_by_id("LAB-TASK-01")
        self.assertIsNotNone(t1)
        self.assertEqual(t1.task_id, "LAB-TASK-01")

        all_tasks = list_tasks()
        self.assertEqual(len(all_tasks), 10)

    def test_task_ten_is_failure_aware_recovery_challenge(self):
        t10 = get_task_by_id("LAB-TASK-10")
        self.assertIsNotNone(t10)
        self.assertTrue(t10.recovery_challenge)
        self.assertIsNotNone(t10.recovery_trigger)
        self.assertIn("attempt_1_tool", t10.recovery_trigger)
        self.assertIn("attempt_2_tool", t10.recovery_trigger)


class TestTaskEvaluationPredicates(unittest.TestCase):
    """Tests the evaluation functions for tool selection, evidence completeness, and success conditions."""

    def test_tool_selection_evaluation(self):
        t1 = get_task_by_id("LAB-TASK-01")
        self.assertTrue(t1.evaluate_tool_selection("nmap.scan.v1"))
        self.assertFalse(t1.evaluate_tool_selection("gobuster.dir.v1"))

    def test_evidence_completeness_calculation(self):
        t1 = get_task_by_id("LAB-TASK-01")
        ev = NetworkEvidence(
            evidence_id="ev_test",
            title="test",
            task_id="LAB-TASK-01",
            session_id="s1",
            protocol="tcp",
            host="127.0.0.1",
        )
        # Class match + matching port fact
        facts = {"ports": [21, 22, 80], "hosts": ["127.0.0.1"]}
        score = t1.evaluate_evidence_completeness(facts, [ev])
        self.assertGreaterEqual(score, 0.80)


class TestBenchmarkRunner(unittest.TestCase):
    """Integration test executing the full 10-task benchmark runner in a temporary environment."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_events.db")
        self.history_path = os.path.join(self.test_dir, "history.json")
        self.report_path = os.path.join(self.test_dir, "report.md")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_benchmark_runner_executes_all_ten_tasks(self):
        runner = BenchmarkRunner(
            db_path=self.db_path,
            history_path=self.history_path,
            report_path=self.report_path,
            use_live_targets=False,
        )

        report = runner.run_all(verbose=False)

        # Verify Report structure
        self.assertIsInstance(report, dict)
        self.assertIn("summary", report)
        self.assertIn("results", report)
        self.assertIn("markdown_report", report)

        summary = report["summary"]
        results = report["results"]
        self.assertEqual(summary["total_tasks"], 10)
        self.assertEqual(summary["tasks_completed"], 10)
        self.assertEqual(len(results), 10)

        # Verify Evaluation Framework metrics
        self.assertEqual(summary["tasks_completed_pct"], 100.0)
        self.assertEqual(summary["tool_accuracy_pct"], 100.0)
        self.assertEqual(summary["recovery_count"], 1)
        self.assertEqual(summary["recovery_successes"], 1)
        self.assertEqual(summary["recovery_rate_pct"], 100.0)
        self.assertGreaterEqual(summary["evidence_completeness_pct"], 80.0)
        self.assertGreaterEqual(summary["composite_score"], 80.0)
        self.assertEqual(summary["status"], "PASS")

        # Verify persistent history file
        self.assertTrue(os.path.exists(self.history_path))
        with open(self.history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["run_id"], summary["run_id"])
        self.assertEqual(history[0]["composite_score"], summary["composite_score"])

        # Verify Markdown report generated
        self.assertTrue(os.path.exists(self.report_path))
        with open(self.report_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        self.assertIn("Kairo Benchmark Score Report", md_content)
        self.assertIn("Evaluation Framework Metrics Table", md_content)
        self.assertIn("Per-Task Execution Breakdown", md_content)

    def test_benchmark_score_history_accumulation(self):
        """Verifies score over time tracking accumulates runs across changes."""
        runner = BenchmarkRunner(
            db_path=self.db_path,
            history_path=self.history_path,
            report_path=self.report_path,
            use_live_targets=False,
        )

        # Run 1
        r1 = runner.run_all(verbose=False)
        # Run 2
        r2 = runner.run_all(verbose=False)

        history = runner.get_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["run_id"], r1["summary"]["run_id"])
        self.assertEqual(history[1]["run_id"], r2["summary"]["run_id"])


if __name__ == "__main__":
    unittest.main()
