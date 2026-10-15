"""
Correctness Test Suite for Orchestrator FailoverRouter Safety Mechanism.

Verifies:
1. Exercise FailoverRouter across EVERY custom model pair against both configured fallbacks:
   - Custom Models: kairo-custom-model, kairo-scale-1.2b, kairo-sft-baseline, kairo-dpo-aligned, kairo-grpo-aligned
   - Fallback Models: Qwen2.5-0.5B-Instruct (ultra-low latency fallback) and Qwen3-Coder-30B-A3B-Instruct (high-capacity fallback)
   (All 10 combinations tested).
2. Forcing N consecutive schema-invalid tool calls from each custom model.
3. Confirming FailoverRouter correctly fails over to the configured fallback every time.
4. Confirming failover events are audited and logged in SQLite EventStore with full metadata.
5. Confirming clean recovery when the primary model is reselected, resetting counters and accepting valid tool calls.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pytest
import yaml

from events.db import init_db, get_connection
from orchestrator.failover_router import FailoverRouter, FailoverEventRecord
from orchestrator.model_center import ModelCenter


# Catalog of Custom Models and Configured Fallbacks
CUSTOM_MODELS = [
    {"model_id": "kairo-custom-model", "role": "primary-custom"},
    {"model_id": "kairo-scale-1.2b", "role": "primary-custom-scaled"},
    {"model_id": "kairo-sft-baseline", "role": "sft-baseline"},
    {"model_id": "kairo-dpo-aligned", "role": "dpo-aligned"},
    {"model_id": "kairo-grpo-aligned", "role": "grpo-aligned"},
]

FALLBACK_MODELS = [
    {"model_id": "Qwen2.5-0.5B-Instruct", "role": "fallback"},
    {"model_id": "Qwen3-Coder-30B-A3B-Instruct", "role": "primary"},
]

# Diverse schema-invalid payloads for testing
SCHEMA_INVALID_TOOL_CALLS = [
    {"tool_id": "nmap.scan.v1", "arguments": {}},  # missing required 'target'
    {"tool_id": "ffuf.fuzz.v1", "arguments": {"wordlist": "common.txt"}},  # missing required 'url'
    {"tool_id": "whatweb.scan.v1", "arguments": {"threads": 10}},  # missing required 'url'
    {"tool_id": "hydra.brute.v1", "arguments": {"target": 12345}},  # wrong type for 'target' (int instead of str)
    {"tool_id": "unregistered.dummy.tool.v1", "arguments": {"payload": "test"}},  # unknown tool ID
]


def make_test_models_yaml(dest_path: Path) -> Dict[str, Any]:
    """Generates an isolated models.yaml catalog containing all test models."""
    cfg = {
        "active_model": "kairo-grpo-aligned",
        "models": [
            {
                "model_id": "Qwen3-Coder-30B-A3B-Instruct",
                "runtime": "llama.cpp",
                "quantization": "Q4_K_M",
                "context_length": 32768,
                "role": "primary",
            },
            {
                "model_id": "Qwen2.5-0.5B-Instruct",
                "runtime": "llama.cpp",
                "quantization": "Q4_K_M",
                "context_length": 4096,
                "role": "fallback",
            },
            {
                "model_id": "kairo-custom-model",
                "runtime": "transformers",
                "quantization": "FP32",
                "context_length": 8192,
                "role": "primary-custom",
            },
            {
                "model_id": "kairo-scale-1.2b",
                "runtime": "transformers",
                "quantization": "FP32",
                "context_length": 8192,
                "role": "primary-custom-scaled",
            },
            {
                "model_id": "kairo-sft-baseline",
                "runtime": "transformers",
                "quantization": "FP32",
                "context_length": 8192,
                "role": "sft-baseline",
            },
            {
                "model_id": "kairo-dpo-aligned",
                "runtime": "transformers",
                "quantization": "FP32",
                "context_length": 8192,
                "role": "dpo-aligned",
            },
            {
                "model_id": "kairo-grpo-aligned",
                "runtime": "transformers",
                "quantization": "FP32",
                "context_length": 8192,
                "role": "grpo-aligned",
            },
        ],
    }
    with open(dest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return cfg


class TestFailoverRouterModelPairs(unittest.TestCase):
    """
    Correctness test suite verifying the FailoverRouter safety mechanism
    across every custom model and fallback model pair.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_events.db")
        self.config_path = os.path.join(self.test_dir, "test_models.yaml")
        init_db(self.db_path)
        make_test_models_yaml(Path(self.config_path))
        self.model_center = ModelCenter(config_path=self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _query_failover_events_from_db(self) -> List[Dict[str, Any]]:
        """Queries logged MODEL_FAILOVER events from the test SQLite database."""
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, session_id, task_id, actor, tool_id, exit_code, result_summary, network_context
                FROM events
                WHERE actor = 'failover_router' OR tool_id = 'circuit_breaker.failover'
                ORDER BY id ASC
                """
            )
            rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        for r in rows:
            if isinstance(r.get("network_context"), str):
                r["network_context"] = json.loads(r["network_context"])
        return rows

    def test_all_ten_model_pairs_failover_and_recovery(self):
        """
        Exercises all 10 model pairs:
        5 Custom Models x 2 Fallbacks (Qwen2.5-0.5B and Qwen3-Coder).
        Forces N=2 consecutive schema-invalid tool calls from each,
        confirms failover to fallback, checks EventStore audit log,
        and verifies clean recovery when the primary model is reselected.
        """
        failure_threshold = 2

        for custom in CUSTOM_MODELS:
            custom_id = custom["model_id"]
            custom_role = custom["role"]

            for fallback in FALLBACK_MODELS:
                fallback_id = fallback["model_id"]
                fallback_role = fallback["role"]

                with self.subTest(custom_model=custom_id, fallback_model=fallback_id):
                    # 1. Initialize isolated router with specific pair
                    router = FailoverRouter(
                        failure_threshold=failure_threshold,
                        primary_role=custom_id,
                        fallback_role=fallback_id,
                        db_path=self.db_path,
                        model_center_instance=self.model_center,
                    )
                    # Select the primary custom model
                    router.reset(restore_role=custom_id)
                    self.assertEqual(self.model_center.get_active_model()["model_id"], custom_id)
                    self.assertFalse(router.failover_active)
                    self.assertEqual(router.consecutive_schema_failures, 0)

                    # 2. Force Failure #1 (below threshold)
                    bad_call_1 = SCHEMA_INVALID_TOOL_CALLS[0]
                    res1 = router.handle_tool_call_output(
                        tool_id=bad_call_1["tool_id"],
                        arguments=bad_call_1["arguments"],
                        session_id=f"sess_{custom_id}_{fallback_id}",
                        task_id="TASK-FAIL-1",
                    )
                    self.assertFalse(res1["valid"], "First invalid call must report valid=False")
                    self.assertFalse(res1["failover_triggered"], "Threshold not reached; failover must NOT trigger yet")
                    self.assertFalse(router.failover_active)
                    self.assertEqual(router.consecutive_schema_failures, 1)
                    self.assertEqual(
                        self.model_center.get_active_model()["model_id"],
                        custom_id,
                        "Active model must still be primary after 1 failure",
                    )

                    # 3. Force Failure #2 (reaches threshold N=2 -> MUST trigger failover)
                    bad_call_2 = SCHEMA_INVALID_TOOL_CALLS[1]
                    res2 = router.handle_tool_call_output(
                        tool_id=bad_call_2["tool_id"],
                        arguments=bad_call_2["arguments"],
                        session_id=f"sess_{custom_id}_{fallback_id}",
                        task_id="TASK-FAIL-2",
                    )
                    self.assertFalse(res2["valid"])
                    self.assertTrue(res2["failover_triggered"], "Failover must trigger on Nth consecutive failure")
                    self.assertTrue(router.failover_active)
                    self.assertEqual(res2["failed_model"], custom_id)
                    self.assertEqual(res2["fallback_model"], fallback_id)
                    self.assertEqual(res2["consecutive_failures"], failure_threshold)

                    # 4. Verify Active Model switched in ModelCenter
                    active_after_failover = self.model_center.get_active_model()
                    self.assertEqual(
                        active_after_failover["model_id"],
                        fallback_id,
                        f"ModelCenter active model must be fallback '{fallback_id}'",
                    )

                    # 5. Verify Failover Event logged in SQLite EventStore
                    db_events = self._query_failover_events_from_db()
                    matching = [
                        e for e in db_events
                        if e["session_id"] == f"sess_{custom_id}_{fallback_id}"
                    ]
                    self.assertGreaterEqual(len(matching), 1, "Failover event must be logged in SQLite")
                    latest_evt = matching[-1]
                    self.assertEqual(latest_evt["actor"], "failover_router")
                    self.assertEqual(latest_evt["tool_id"], "circuit_breaker.failover")
                    self.assertEqual(latest_evt["exit_code"], 1)

                    net_ctx = latest_evt["network_context"]
                    self.assertEqual(net_ctx["event_type"], "MODEL_FAILOVER")
                    self.assertEqual(net_ctx["from_model"], custom_id)
                    self.assertEqual(net_ctx["to_model"], fallback_id)
                    self.assertEqual(net_ctx["consecutive_failures"], failure_threshold)
                    self.assertEqual(net_ctx["trigger_tool"], bad_call_2["tool_id"])

                    # 6. Verify Clean Recovery when primary model is reselected
                    recovery_res = router.reselect_primary(custom_id)
                    self.assertTrue(recovery_res["reselected"])
                    self.assertEqual(recovery_res["active_model_id"], custom_id)
                    self.assertFalse(router.failover_active, "Failover active flag must reset to False")
                    self.assertEqual(router.consecutive_schema_failures, 0, "Counter must reset to 0")

                    # Confirm primary model can now issue valid schema calls without issue
                    valid_call = router.handle_tool_call_output(
                        tool_id="nmap.scan.v1",
                        arguments={"target": "127.0.0.1"},
                        session_id=f"sess_{custom_id}_{fallback_id}",
                        task_id="TASK-RECOVERED",
                    )
                    self.assertTrue(valid_call["valid"], "Valid tool call must succeed after recovery")
                    self.assertFalse(valid_call["failover_triggered"])
                    self.assertFalse(router.failover_active)
                    self.assertEqual(router.consecutive_schema_failures, 0)
                    self.assertEqual(self.model_center.get_active_model()["model_id"], custom_id)

    def test_variable_failure_thresholds(self):
        """Tests that FailoverRouter enforces arbitrary failure thresholds N=1, 3, 5."""
        for n in [1, 3, 5]:
            with self.subTest(threshold_n=n):
                router = FailoverRouter(
                    failure_threshold=n,
                    primary_role="kairo-grpo-aligned",
                    fallback_role="Qwen2.5-0.5B-Instruct",
                    db_path=self.db_path,
                    model_center_instance=self.model_center,
                )
                router.reset(restore_role="kairo-grpo-aligned")

                for step in range(1, n):
                    bad_call = SCHEMA_INVALID_TOOL_CALLS[step % len(SCHEMA_INVALID_TOOL_CALLS)]
                    res = router.handle_tool_call_output(
                        tool_id=bad_call["tool_id"],
                        arguments=bad_call["arguments"],
                        session_id=f"sess_thresh_{n}",
                        task_id=f"TASK-STEP-{step}",
                    )
                    self.assertFalse(res["valid"])
                    self.assertFalse(res["failover_triggered"])
                    self.assertFalse(router.failover_active)
                    self.assertEqual(router.consecutive_schema_failures, step)

                # Nth call triggers failover
                final_bad = SCHEMA_INVALID_TOOL_CALLS[n % len(SCHEMA_INVALID_TOOL_CALLS)]
                final_res = router.handle_tool_call_output(
                    tool_id=final_bad["tool_id"],
                    arguments=final_bad["arguments"],
                    session_id=f"sess_thresh_{n}",
                    task_id=f"TASK-STEP-{n}",
                )
                self.assertTrue(final_res["failover_triggered"])
                self.assertTrue(router.failover_active)
                self.assertEqual(self.model_center.get_active_model()["model_id"], "Qwen2.5-0.5B-Instruct")

    def test_intermittent_success_resets_counter_preventing_failover(self):
        """
        Verifies that non-consecutive failures do not accumulate:
        Invalid -> Valid -> Invalid -> Valid never triggers failover.
        """
        router = FailoverRouter(
            failure_threshold=2,
            primary_role="kairo-scale-1.2b",
            fallback_role="Qwen3-Coder-30B-A3B-Instruct",
            db_path=self.db_path,
            model_center_instance=self.model_center,
        )
        router.reset(restore_role="kairo-scale-1.2b")

        for cycle in range(5):
            # Invalid call: count becomes 1
            res_bad = router.handle_tool_call_output(
                tool_id="ffuf.fuzz.v1",
                arguments={},  # invalid
                task_id=f"TASK-BAD-{cycle}",
            )
            self.assertFalse(res_bad["valid"])
            self.assertFalse(res_bad["failover_triggered"])
            self.assertEqual(router.consecutive_schema_failures, 1)

            # Valid call: count resets to 0
            res_good = router.handle_tool_call_output(
                tool_id="whatweb.scan.v1",
                arguments={"url": "http://127.0.0.1:8000"},  # valid
                task_id=f"TASK-GOOD-{cycle}",
            )
            self.assertTrue(res_good["valid"])
            self.assertEqual(router.consecutive_schema_failures, 0)
            self.assertFalse(router.failover_active)
            self.assertEqual(self.model_center.get_active_model()["model_id"], "kairo-scale-1.2b")

    def test_multiple_sequential_failover_recovery_cycles(self):
        """
        Verifies state machine stability across multiple repeated failover-and-recovery cycles:
        primary -> failover -> fallback -> reselect -> repeat.
        """
        router = FailoverRouter(
            failure_threshold=2,
            primary_role="kairo-dpo-aligned",
            fallback_role="Qwen2.5-0.5B-Instruct",
            db_path=self.db_path,
            model_center_instance=self.model_center,
        )

        for cycle in range(3):
            router.reset(restore_role="kairo-dpo-aligned")
            self.assertEqual(self.model_center.get_active_model()["model_id"], "kairo-dpo-aligned")

            # 2 consecutive failures
            router.handle_tool_call_output(
                tool_id="nmap.scan.v1", arguments={}, task_id=f"CYCLE-{cycle}-1"
            )
            res = router.handle_tool_call_output(
                tool_id="nmap.scan.v1", arguments={}, task_id=f"CYCLE-{cycle}-2"
            )
            self.assertTrue(res["failover_triggered"])
            self.assertEqual(self.model_center.get_active_model()["model_id"], "Qwen2.5-0.5B-Instruct")

            # Clean recovery
            router.reselect_primary("kairo-dpo-aligned")
            self.assertEqual(self.model_center.get_active_model()["model_id"], "kairo-dpo-aligned")
            self.assertFalse(router.failover_active)

        self.assertEqual(len(router.failover_history), 3)


if __name__ == "__main__":
    unittest.main()
