"""
Unit and Integration Tests for Model Evolution Controller.

Tests:
1. Policy YAML parsing and hot-reloading.
2. Rule 1: SFT Refresh proposal when new_examples >= 2000 and schema_pass >= 90%.
3. Rule 2: Tier Scaling proposal when 3 consecutive runs show <1% gain.
4. Rule 3: Regression Rollback proposal on >5% metric drop (never a retrain).
5. Cost and compute duration estimation from historical job records.
6. Event Store integration and proposal persistence.
7. Strict proposal-only safety: controller never auto-executes training jobs.
8. Background worker thread start/stop lifecycle.
"""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest
import yaml

from events.db import init_db, get_connection
from orchestrator.model_evolution_controller import ModelEvolutionController


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_policy_file(temp_dir):
    policy_path = temp_dir / "evolution_policy.yaml"
    policy_content = {
        "controller": {
            "polling_interval_seconds": 1,
            "enabled": True,
            "active_model_id": "kairo-scale-2b-grpo",
            "baseline_model_id": "kairo-scale-1.2b",
            "event_session_id": "test-evolution-session",
        },
        "rules": {
            "sft_refresh": {
                "enabled": True,
                "min_new_examples": 2000,
                "min_schema_pass_rate": 0.90,
                "target_job_type": "trl_sft",
                "target_preset": "kairo-scale-2b",
                "action": "propose_sft_refresh",
            },
            "tier_scaling": {
                "enabled": True,
                "plateau_consecutive_runs": 3,
                "plateau_accuracy_delta_max": 0.01,
                "metric": "tool_accuracy_pct",
                "target_job_type": "pretrain_scale",
                "next_tier_preset": "kairo-3b",
                "action": "propose_tier_scaling",
            },
            "regression_rollback": {
                "enabled": True,
                "max_tolerable_regression_pct": 0.05,
                "critical_metrics": [
                    "schema_pass_pct",
                    "tool_accuracy_pct",
                    "recovery_rate_pct",
                    "composite_score",
                ],
                "action": "propose_rollback",
                "fallback_checkpoint": "kairo-scale-1.2b",
            },
        },
    }
    with open(policy_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(policy_content, f)
    return policy_path


class MockTrainingManager:
    """Mock TrainingManager tracking jobs and dataset metrics."""

    def __init__(self, total_examples=5200, pass_rate=96.5):
        self.stats = {
            "total_examples": total_examples,
            "train_cleaned_count": total_examples - 300,
            "validation_pass_rate_pct": pass_rate,
            "recovery_examples_count": 800,
        }
        self.jobs = [
            {
                "id": "job_trl_sft_hist_1",
                "job_type": "trl_sft",
                "status": "completed",
                "started_at": "2026-10-15T10:00:00+00:00",
                "finished_at": "2026-10-15T10:05:20+00:00",  # 320 seconds
            },
            {
                "id": "job_trl_sft_hist_2",
                "job_type": "trl_sft",
                "status": "completed",
                "started_at": "2026-10-16T10:00:00+00:00",
                "finished_at": "2026-10-16T10:05:00+00:00",  # 300 seconds
            },
            {
                "id": "job_pretrain_hist_1",
                "job_type": "pretrain_scale",
                "status": "completed",
                "started_at": "2026-10-14T08:00:00+00:00",
                "finished_at": "2026-10-14T08:30:00+00:00",  # 1800 seconds
            },
        ]
        self.started_job_count = 0

    def get_dataset_stats(self):
        return self.stats

    def get_training_jobs(self):
        return self.jobs

    def list_checkpoints(self):
        return [
            {
                "stage": "trl_sft",
                "train_runtime_s": 310.0,
                "preset_name": "kairo-scale-2b",
            }
        ]

    def start_training_job(self, *args, **kwargs):
        self.started_job_count += 1
        return {"id": "mock_started_job"}


class MockBenchmarkManager:
    """Mock BenchmarkManager returning leaderboard sweeps."""

    def __init__(self, custom_sweeps=None):
        self.sweeps = custom_sweeps or [
            {
                "sweep_id": "sweep_alpha",
                "models": [
                    {
                        "model_id": "kairo-scale-2b-grpo",
                        "tool_accuracy_pct": 99.2,
                        "schema_pass_pct": 100.0,
                        "recovery_rate_pct": 100.0,
                        "composite_score": 98.2,
                        "timestamp": "2026-10-16T12:00:00+00:00",
                    },
                    {
                        "model_id": "kairo-scale-1.2b",
                        "tool_accuracy_pct": 98.3,
                        "schema_pass_pct": 100.0,
                        "recovery_rate_pct": 100.0,
                        "composite_score": 96.4,
                        "timestamp": "2026-10-15T12:00:00+00:00",
                    },
                ],
            }
        ]

    def get_leaderboard_data(self):
        return {"sweeps": self.sweeps}

    def get_sweep_comparison(self, sweep_id=None):
        return {"comparison": "mock_comparison"}


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

def test_policy_load_and_reload(sample_policy_file, temp_dir):
    """Verifies that policy YAML is parsed accurately and can be hot-reloaded."""
    proposals_path = temp_dir / "proposals.json"
    state_path = temp_dir / "state.json"

    controller = ModelEvolutionController(
        policy_path=sample_policy_file,
        proposals_path=proposals_path,
        state_path=state_path,
    )
    assert controller.policy["controller"]["polling_interval_seconds"] == 1
    assert controller.policy["rules"]["sft_refresh"]["min_new_examples"] == 2000

    # Modify policy on disk and hot reload
    with open(sample_policy_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["rules"]["sft_refresh"]["min_new_examples"] = 3500
    with open(sample_policy_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)

    reloaded = controller.reload_policy()
    assert reloaded["rules"]["sft_refresh"]["min_new_examples"] == 3500


def test_rule1_sft_refresh_triggered(sample_policy_file, temp_dir):
    """
    Rule 1: If new_examples_since_last_run >= 2000 AND schema_validity_pass_rate >= 0.9:
    propose an SFT refresh job.
    """
    mock_tm = MockTrainingManager(total_examples=5500, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()
    proposals_path = temp_dir / "proposals.json"
    state_path = temp_dir / "state.json"

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=proposals_path,
        state_path=state_path,
    )

    # Initialize state with 3000 examples, so new_examples = 2500 (>= 2000)
    controller.state["last_run_example_count"] = 3000

    res = controller.run_cycle()
    proposals = res["proposals_generated"]

    assert len(proposals) == 1
    sft_prop = proposals[0]
    assert sft_prop["action"] == "propose_sft_refresh"
    assert sft_prop["rule_name"] == "sft_refresh"
    assert sft_prop["job_type"] == "trl_sft"
    assert sft_prop["status"] == "PROPOSED"
    assert "2500 new validated examples" in sft_prop["rationale"]
    assert sft_prop["trigger_metrics"]["new_examples_since_last_run"] == 2500
    assert sft_prop["trigger_metrics"]["schema_validity_pass_rate"] == 0.95

    # Verify SAFETY: TrainingManager.start_training_job was NEVER called
    assert mock_tm.started_job_count == 0


def test_rule1_sft_refresh_not_triggered_when_insufficient_data(sample_policy_file, temp_dir):
    """Rule 1 should NOT trigger if new examples < 2000 or pass rate < 90%."""
    mock_tm = MockTrainingManager(total_examples=3500, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    # Only 500 new examples accumulated since last run
    controller.state["last_run_example_count"] = 3000

    res = controller.run_cycle()
    assert len(res["proposals_generated"]) == 0

    # Test pass rate below 0.90 (e.g. 85%) with sufficient examples
    res_low_pass = controller.run_cycle(
        dataset_stats_override={
            "total_examples": 6000,
            "new_examples_since_last_run": 3000,
            "validation_pass_rate_pct": 85.0,  # Below 90%
        }
    )
    assert len(res_low_pass["proposals_generated"]) == 0


def test_rule2_tier_scaling_on_accuracy_plateau(sample_policy_file, temp_dir):
    """
    Rule 2: If three consecutive SFT refreshes show <1% accuracy gain on the
    benchmark sweep: propose scaling to the next parameter tier instead of
    continuing to retrain at the same size.
    """
    # 4 consecutive SFT runs showing 0.2%, 0.3%, 0.1% gains
    runs = [
        {"model_id": "kairo-sft-run1", "tool_accuracy_pct": 94.0, "timestamp": "2026-10-10T10:00:00+00:00"},
        {"model_id": "kairo-sft-run2", "tool_accuracy_pct": 94.2, "timestamp": "2026-10-11T10:00:00+00:00"},
        {"model_id": "kairo-sft-run3", "tool_accuracy_pct": 94.5, "timestamp": "2026-10-12T10:00:00+00:00"},
        {"model_id": "kairo-sft-run4", "tool_accuracy_pct": 94.6, "timestamp": "2026-10-13T10:00:00+00:00"},
    ]
    mock_bm = MockBenchmarkManager(custom_sweeps=[{"sweep_id": "sweep_plateau", "models": runs}])
    mock_tm = MockTrainingManager(total_examples=3000, pass_rate=95.0)

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    controller.state["last_run_example_count"] = 3000  # 0 new examples, so SFT won't trigger

    res = controller.run_cycle()
    proposals = res["proposals_generated"]

    assert len(proposals) == 1
    scale_prop = proposals[0]
    assert scale_prop["action"] == "propose_tier_scaling"
    assert scale_prop["rule_name"] == "tier_scaling"
    assert scale_prop["target_preset"] == "kairo-3b"
    assert scale_prop["job_type"] == "pretrain_scale"
    assert "consecutive SFT refreshes showed marginal accuracy gains" in scale_prop["rationale"]
    assert "saturated" in scale_prop["rationale"]
    assert scale_prop["status"] == "PROPOSED"
    assert mock_tm.started_job_count == 0


def test_rule3_regression_rollback_never_retrain(sample_policy_file, temp_dir):
    """
    Rule 3: If a benchmark sweep shows the active model regressed on any metric
    by more than a defined threshold (5%) vs. its own last sweep: propose a
    rollback to the last known-good checkpoint, never a fresh retrain.
    """
    # Active model dropped from 98.0% to 91.0% (7% drop > 5% threshold)
    runs = [
        {
            "model_id": "kairo-scale-2b-grpo",
            "tool_accuracy_pct": 98.0,
            "schema_pass_pct": 100.0,
            "recovery_rate_pct": 100.0,
            "composite_score": 98.0,
            "timestamp": "2026-10-14T10:00:00+00:00",
        },
        {
            "model_id": "kairo-scale-2b-grpo",
            "tool_accuracy_pct": 91.0,  # 7.0% drop!
            "schema_pass_pct": 100.0,
            "recovery_rate_pct": 100.0,
            "composite_score": 91.5,
            "timestamp": "2026-10-16T10:00:00+00:00",
        },
    ]
    mock_bm = MockBenchmarkManager(custom_sweeps=[{"sweep_id": "sweep_regression", "models": runs}])
    # Set sufficient examples that WOULD have triggered SFT refresh if not for regression
    mock_tm = MockTrainingManager(total_examples=6000, pass_rate=98.0)

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    controller.state["last_run_example_count"] = 3000  # 3000 new examples

    res = controller.run_cycle()
    proposals = res["proposals_generated"]

    # Only rollback must be proposed; SFT refresh must be suppressed during regression
    assert len(proposals) == 1
    rollback_prop = proposals[0]
    assert rollback_prop["action"] == "propose_rollback"
    assert rollback_prop["rule_name"] == "regression_rollback"
    assert rollback_prop["target_preset"] == "kairo-scale-1.2b"
    assert "regressed on critical metric" in rollback_prop["rationale"]
    assert "NEVER a fresh retrain" in rollback_prop["rationale"]
    assert rollback_prop["trigger_metrics"]["regression_drop_pct"] == 7.0
    assert rollback_prop["status"] == "PROPOSED"
    assert mock_tm.started_job_count == 0


def test_cost_estimation_pulls_historical_records(sample_policy_file, temp_dir):
    """Verifies that cost estimation queries past TrainingManager jobs."""
    mock_tm = MockTrainingManager()
    controller = ModelEvolutionController(
        training_manager=mock_tm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )

    cost_sft = controller.estimate_cost("trl_sft", "kairo-scale-2b")
    assert cost_sft["expected_duration_seconds"] == pytest.approx(310.0, abs=15.0)
    assert "historical" in cost_sft["historical_basis"].lower()
    assert cost_sft["estimated_gpu_hours"] > 0

    cost_scale = controller.estimate_cost("pretrain_scale", "kairo-3b")
    assert cost_scale["expected_duration_seconds"] == pytest.approx(1800.0, abs=50.0)

    cost_rollback = controller.estimate_cost("rollback", "kairo-scale-1.2b")
    assert cost_rollback["expected_duration_seconds"] < 10.0
    assert "Zero training compute" in cost_rollback["historical_basis"]


def test_event_store_and_file_persistence(sample_policy_file, temp_dir):
    """Verifies that proposals are written to the SQLite Event Store and JSON file."""
    mock_tm = MockTrainingManager(total_examples=6000, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()
    proposals_file = temp_dir / "test_proposals.json"
    state_file = temp_dir / "test_state.json"

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=proposals_file,
        state_path=state_file,
    )
    controller.state["last_run_example_count"] = 3000

    res = controller.run_cycle()
    assert len(res["proposals_generated"]) == 1
    proposal = res["proposals_generated"][0]

    # Verify JSON persistence
    assert proposals_file.exists()
    with open(proposals_file, "r", encoding="utf-8") as f:
        saved_proposals = json.load(f)
    assert len(saved_proposals) >= 1
    assert saved_proposals[-1]["proposal_id"] == proposal["proposal_id"]

    # Verify Event Store record
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT task_id, actor, tool_id, result_summary FROM events WHERE session_id = 'test-evolution-session' ORDER BY id DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == proposal["proposal_id"]
    assert row[1] == "ModelEvolutionController"
    assert row[2] == "evolution_policy_engine"
    assert "SFT refresh condition satisfied" in row[3]


def test_background_thread_lifecycle(sample_policy_file, temp_dir):
    """Tests starting, running, and stopping the background controller thread."""
    mock_tm = MockTrainingManager(total_examples=3000, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )

    assert not controller.is_running()
    start_res = controller.start()
    assert start_res["status"] == "started"
    assert controller.is_running()

    # Allow worker thread to execute at least one cycle
    time.sleep(0.3)
    status = controller.get_status()
    assert status["running"] is True
    assert status["cycle_count"] >= 1

    stop_res = controller.stop()
    assert stop_res["status"] == "stopping"
    time.sleep(0.2)
    assert not controller.is_running()
