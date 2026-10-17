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
            "auto_evaluation": {
                "enabled": True,
                "tolerance_pct": 0.01,
                "tracked_metrics": [
                    "tool_accuracy_pct",
                    "schema_pass_pct",
                    "recovery_rate_pct",
                    "composite_score",
                ],
                "require_overall_improvement": True,
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

    def trigger_benchmark_run(self, model_id, benchmark_type="golden"):
        return {
            "success": True,
            "run": {
                "model_id": model_id,
                "tool_accuracy_pct": 99.4,
                "schema_pass_pct": 100.0,
                "recovery_rate_pct": 100.0,
                "composite_score": 98.6,
                "timestamp": "2026-10-17T00:00:00+00:00",
            },
        }


class MockModelCenter:
    """Mock ModelCenter tracking active model and set_active_model calls."""

    def __init__(self, active_model_id="kairo-scale-1.2b"):
        self.active_model_id = active_model_id
        self.promotions = []
        self.models = [
            {"model_id": "kairo-scale-1.2b", "role": "primary-custom-scaled"},
            {"model_id": "kairo-scale-2b-grpo", "role": "primary-custom-scaled-grpo"},
            {"model_id": "kairo-scale-2b-sft", "role": "primary-custom-scaled-sft"},
        ]

    def get_active_model(self):
        return {"model_id": self.active_model_id}

    def get_model_by_id(self, model_id):
        return next((m for m in self.models if m["model_id"] == model_id), None)

    def set_active_model(self, model_id):
        self.active_model_id = model_id
        self.promotions.append(model_id)
        return {"model_id": model_id, "status": "active"}

    def load_config(self):
        return {"active_model": self.active_model_id, "models": list(self.models)}

    def save_config(self, cfg):
        if "active_model" in cfg:
            self.active_model_id = cfg["active_model"]
        if "models" in cfg:
            self.models = list(cfg["models"])


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


def test_proposal_plain_language_summary(sample_policy_file, temp_dir):
    """
    Verifies that the generated proposal contains the plain-language summary
    matching the required format:
    'Propose: retrain kairo-scale-1.2b on 2,340 new examples (last run 11 days ago, validity 94%). Estimated time: ~3.5 hours on this hardware.'
    """
    mock_tm = MockTrainingManager(total_examples=5340, pass_rate=94.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    # 5340 - 3000 = 2340 new examples
    controller.state["last_run_example_count"] = 3000
    # Simulate last run 11 days ago
    eleven_days_ago = time.time() - (11 * 86400)
    import datetime as dt
    controller.state["last_run_timestamp"] = dt.datetime.fromtimestamp(eleven_days_ago, dt.timezone.utc).isoformat()

    res = controller.run_cycle()
    proposals = res["proposals_generated"]
    assert len(proposals) == 1

    prop = proposals[0]
    plain = prop.get("plain_language_summary", "")
    assert "Propose: retrain" in plain
    assert "2,340 new examples" in plain
    assert "last run 11 days ago" in plain
    assert "validity 94%" in plain
    assert "Estimated time:" in plain


def test_human_in_the_loop_approval_checkpoint(sample_policy_file, temp_dir):
    """
    CRITICAL HUMAN-IN-THE-LOOP CHECKPOINT:
    1. The controller's decision loop (run_cycle) generates a proposal but NEVER calls start_training_job().
    2. Only when the operator explicitly calls approve_proposal() is TrainingManager.start_training_job() called.
    3. The proposal transitions to 'APPROVED' and state['last_run_example_count'] is updated.
    4. An audit event is logged into the Event Store.
    """
    mock_tm = MockTrainingManager(total_examples=5500, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    controller.state["last_run_example_count"] = 3000

    # 1. Run decision loop
    res = controller.run_cycle()
    proposals = res["proposals_generated"]
    assert len(proposals) == 1
    prop = proposals[0]
    prop_id = prop["proposal_id"]

    # Verify checkpoint: NEVER called by decision loop
    assert mock_tm.started_job_count == 0
    assert prop["status"] == "PROPOSED"

    # 2. Operator calls approve_proposal
    approve_res = controller.approve_proposal(prop_id, operator="admin_user")
    assert approve_res["success"] is True
    assert approve_res["proposal"]["status"] == "APPROVED"
    assert approve_res["proposal"]["approved_by"] == "admin_user"

    # Verify that now and ONLY now was start_training_job() called
    assert mock_tm.started_job_count == 1

    # 3. Baseline example count is updated to prevent immediate re-trigger
    assert controller.state["last_run_example_count"] == 5500

    # 4. Verify human approval event in Event Store
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT actor, tool_id, result_summary FROM events WHERE task_id = ? AND actor = 'admin_user'",
        (prop_id,),
    )
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "admin_user"
    assert row[1] == "human_approval_gate"
    assert "approved evolution proposal" in row[2]


def test_dismiss_proposal_never_starts_job(sample_policy_file, temp_dir):
    """
    Dismissing a proposal transitions it to 'DISMISSED' and NEVER starts a training job.
    """
    mock_tm = MockTrainingManager(total_examples=5500, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    controller.state["last_run_example_count"] = 3000

    res = controller.run_cycle()
    prop_id = res["proposals_generated"][0]["proposal_id"]

    # Dismiss proposal
    dismiss_res = controller.dismiss_proposal(prop_id, operator="reviewer", reason="Compute budget reserved")
    assert dismiss_res["success"] is True
    assert dismiss_res["proposal"]["status"] == "DISMISSED"
    assert dismiss_res["proposal"]["dismissed_by"] == "reviewer"
    assert dismiss_res["proposal"]["dismiss_reason"] == "Compute budget reserved"

    # Confirm training job was NEVER called
    assert mock_tm.started_job_count == 0


def test_approve_dismissed_or_approved_fails(sample_policy_file, temp_dir):
    """Cannot re-approve an already approved or dismissed proposal."""
    mock_tm = MockTrainingManager(total_examples=5500, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
    )
    controller.state["last_run_example_count"] = 3000

    res = controller.run_cycle()
    prop_id = res["proposals_generated"][0]["proposal_id"]

    # Dismiss first
    controller.dismiss_proposal(prop_id, operator="admin")

    # Attempt approve
    err_res = controller.approve_proposal(prop_id, operator="admin")
    assert err_res["success"] is False
    assert "already DISMISSED" in err_res["error"]
    assert mock_tm.started_job_count == 0


def test_auto_evaluation_promotes_when_all_metrics_meet_or_beat(sample_policy_file, temp_dir):
    """
    Task C.3: Evaluating a completed job auto-promotes when every tracked metric
    meets or beats the currently active model's last sweep.
    """
    mock_tm = MockTrainingManager()
    # Simulate a completed training job that produced checkpoint 'kairo-scale-2b-grpo'
    mock_tm.jobs = [
        {
            "id": "job_completed_grpo_101",
            "job_type": "grpo",
            "preset": "kairo-scale-2b",
            "status": "completed",
            "output_dir": "training/checkpoints/grpo/v2",
        }
    ]
    # Active model baseline in leaderboard: 98.3% accuracy, 96.4% composite
    mock_bm = MockBenchmarkManager()
    mock_mc = MockModelCenter(active_model_id="kairo-scale-1.2b")

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        model_center=mock_mc,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
        evaluations_path=temp_dir / "evaluations.json",
    )

    # Sweep for new checkpoint: 99.5% accuracy, 100% schema, 100% recovery, 98.8% composite (beats all!)
    new_checkpoint_sweep = {
        "model_id": "kairo-scale-2b-grpo",
        "tool_accuracy_pct": 99.5,
        "schema_pass_pct": 100.0,
        "recovery_rate_pct": 100.0,
        "composite_score": 98.8,
    }

    evals = controller.evaluate_completed_jobs(
        jobs_override=mock_tm.jobs,
        active_model_override="kairo-scale-1.2b",
        benchmark_run_override=new_checkpoint_sweep,
    )

    assert len(evals) == 1
    ev = evals[0]
    assert ev["decision"] == "PROMOTED"
    assert ev["promoted"] is True
    assert ev["checkpoint_model_id"] == "kairo-scale-2b-grpo"
    assert "Auto-promoted kairo-scale-2b-grpo to active model" in ev["plain_language_notice"]

    # Verify ModelCenter.set_active_model was called!
    assert mock_mc.active_model_id == "kairo-scale-2b-grpo"
    assert "kairo-scale-2b-grpo" in mock_mc.promotions

    # Verify job marked as evaluated so it won't re-run
    assert "job_completed_grpo_101" in controller.state["evaluated_jobs"]

    # Verify event logged in Event Store
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT actor, tool_id, result_summary FROM events WHERE task_id = 'eval_job_completed_grpo_101'"
    )
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "ModelEvolutionController"
    assert row[1] == "auto_promotion_gate"
    assert "Auto-promoted" in row[2]


def test_auto_evaluation_promotes_within_tolerance_with_improvements(sample_policy_file, temp_dir):
    """
    Task C.3: Auto-promotes when single metric is within configured tolerance
    (e.g., 0.2% drop <= 1.0% tolerance) while clearly improving on others.
    """
    mock_tm = MockTrainingManager()
    mock_tm.jobs = [
        {
            "id": "job_completed_scale_202",
            "job_type": "pretrain_scale",
            "preset": "kairo-scale-2b",
            "status": "completed",
        }
    ]
    # Active baseline: 98.3% accuracy, 100% schema, 96.4% composite
    mock_bm = MockBenchmarkManager()
    mock_mc = MockModelCenter(active_model_id="kairo-scale-1.2b")

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        model_center=mock_mc,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
        evaluations_path=temp_dir / "evaluations.json",
    )

    # Tool accuracy dropped 0.2% (98.1 vs 98.3 - within 1% tolerance), but composite gained (+1.6%)
    sweep = {
        "model_id": "kairo-scale-2b-grpo",
        "tool_accuracy_pct": 98.1,
        "schema_pass_pct": 100.0,
        "recovery_rate_pct": 100.0,
        "composite_score": 98.0,
    }

    evals = controller.evaluate_completed_jobs(
        jobs_override=mock_tm.jobs,
        active_model_override="kairo-scale-1.2b",
        benchmark_run_override=sweep,
    )

    assert len(evals) == 1
    assert evals[0]["decision"] == "PROMOTED"
    assert mock_mc.active_model_id == "kairo-scale-2b-grpo"


def test_auto_evaluation_guards_rollback_on_regression_never_deletes(sample_policy_file, temp_dir):
    """
    Task C.3: If any metric regresses beyond tolerance:
    - Do NOT promote (leaves previous model active).
    - NEVER delete the completed checkpoint.
    - Surface plain-language notice:
      "New checkpoint trained but not promoted — regressed on <metric> by <amount>. Still available in Model Center if you want to activate it manually."
    """
    mock_tm = MockTrainingManager()
    mock_tm.jobs = [
        {
            "id": "job_regressed_run_303",
            "job_type": "sft",
            "preset": "kairo-scale-2b",
            "status": "completed",
            "output_dir": "training/checkpoints/trl_sft/v2",
        }
    ]
    # Active baseline is at 98.3% accuracy, 100% recovery
    mock_bm = MockBenchmarkManager()
    mock_mc = MockModelCenter(active_model_id="kairo-scale-1.2b")

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        model_center=mock_mc,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
        evaluations_path=temp_dir / "evaluations.json",
    )

    # Regressed on tool_accuracy_pct: 94.0% vs 98.3% (4.3% regression > 1% tolerance)
    regressed_sweep = {
        "model_id": "kairo-scale-2b-sft",
        "tool_accuracy_pct": 94.0,
        "schema_pass_pct": 99.0,
        "recovery_rate_pct": 95.0,
        "composite_score": 92.5,
    }

    evals = controller.evaluate_completed_jobs(
        jobs_override=mock_tm.jobs,
        active_model_override="kairo-scale-1.2b",
        benchmark_run_override=regressed_sweep,
    )

    assert len(evals) == 1
    ev = evals[0]
    assert ev["decision"] == "NOT_PROMOTED"
    assert ev["promoted"] is False

    # Previous model remains active — no promotion call
    assert mock_mc.active_model_id == "kairo-scale-1.2b"
    assert len(mock_mc.promotions) == 0

    # Plain language notice matches exact requirement:
    notice = ev["plain_language_notice"]
    assert "New checkpoint trained but not promoted" in notice
    assert "regressed on tool_accuracy_pct by 4.3%" in notice
    assert "Still available in Model Center if you want to activate it manually." in notice

    # Event logged into Event Store
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tool_id, result_summary FROM events WHERE task_id = 'eval_job_regressed_run_303'"
    )
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "auto_promotion_gate"
    assert "New checkpoint trained but not promoted" in row[1]


def test_auto_evaluation_runs_in_controller_cycle(sample_policy_file, temp_dir):
    """Verifies that run_cycle automatically evaluates finished jobs without human trigger."""
    mock_tm = MockTrainingManager(total_examples=3000, pass_rate=95.0)
    mock_bm = MockBenchmarkManager()
    mock_mc = MockModelCenter(active_model_id="kairo-scale-1.2b")

    controller = ModelEvolutionController(
        training_manager=mock_tm,
        benchmark_manager=mock_bm,
        model_center=mock_mc,
        policy_path=sample_policy_file,
        proposals_path=temp_dir / "proposals.json",
        state_path=temp_dir / "state.json",
        evaluations_path=temp_dir / "evaluations.json",
    )
    controller.state["last_run_example_count"] = 3000

    # Add newly completed job that finishes while controller is running
    mock_tm.jobs.append({
        "id": "job_auto_cycle_404",
        "job_type": "grpo",
        "preset": "kairo-scale-2b",
        "status": "completed",
    })

    cycle_res = controller.run_cycle()
    assert "evaluations_performed" in cycle_res
    assert len(cycle_res["evaluations_performed"]) == 1
    eval_rec = cycle_res["evaluations_performed"][0]
    assert eval_rec["job_id"] == "job_auto_cycle_404"
    assert eval_rec["decision"] == "PROMOTED"
    assert mock_mc.active_model_id == "kairo-scale-2b-grpo"


