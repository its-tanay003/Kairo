"""
Tests for TRL DPO Preference Tuning, 120-Task Benchmark Harness,
and Unnecessary Calls / Hallucinated Success Metric Reductions (Task 6.1).
"""

import json
from pathlib import Path
import pytest
from datasets import Dataset

from training.dpo import KairoPreferenceDataLoader, KairoDPOTrainingPipeline
from lab.tasks import LAB_TASKS, get_lab_task, get_all_lab_tasks
from lab.extended_tasks import EXTENDED_LAB_TASKS
from lab.runner import BenchmarkRunner, TaskBenchmarkResult
from registry.loader import ToolRegistry

ROOT_DIR = Path(__file__).resolve().parent.parent
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class TestDPOPreferenceTuning:
    """Tests for Hugging Face TRL DPO dataset loading and training configuration."""

    def test_preference_dataloader_loads_jsonl(self):
        loader = KairoPreferenceDataLoader()
        pairs = loader.load_pairs()
        assert len(pairs) >= 100, f"Expected at least 100 preference pairs, got {len(pairs)}"

        # Validate structure of first pair
        first = pairs[0]
        assert "prompt" in first
        assert "chosen" in first
        assert "rejected" in first
        assert "metadata" in first
        assert "better_plan_strengths" in first["metadata"]
        assert "worse_plan_flaws" in first["metadata"]

    def test_preference_dataloader_to_hf_dataset(self):
        loader = KairoPreferenceDataLoader()
        train_ds, val_ds = loader.to_hf_dataset()
        assert isinstance(train_ds, Dataset)
        assert isinstance(val_ds, Dataset)
        assert set(train_ds.column_names) == {"prompt", "chosen", "rejected"}
        assert len(train_ds) + len(val_ds) >= 100

    def test_dpo_pipeline_initialization_and_config(self):
        pipeline = KairoDPOTrainingPipeline(
            beta=0.1,
            learning_rate=5e-6,
            max_length=512,
        )
        assert pipeline.beta == 0.1
        assert pipeline.learning_rate == 5e-6
        assert pipeline.max_length == 512

        dpo_config = pipeline.get_dpo_config(epochs=1, batch_size=2)
        assert dpo_config.beta == 0.1
        assert dpo_config.learning_rate == 5e-6
        assert dpo_config.max_length == 512
        assert dpo_config.use_cpu is True

    def test_dpo_checkpoint_meta_exists(self):
        meta_path = ROOT_DIR / "training" / "checkpoints" / "dpo" / "dpo_training_meta.json"
        assert meta_path.exists(), f"DPO metadata file missing at {meta_path}"

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        assert meta.get("beta") == 0.1
        assert "rewards/margins" in meta
        assert meta["rewards/margins"] > 0
        assert "rewards/chosen" in meta
        assert "rewards/rejected" in meta


class TestExtendedBenchmarkSuite:
    """Tests for the 100-300 task suite expansion (120 tasks) covering all 22 tools."""

    def test_task_count_meets_blueprint_requirement(self):
        # Blueprint specifies 100-300 task set
        assert len(LAB_TASKS) >= 100, f"Expected >= 100 tasks, got {len(LAB_TASKS)}"
        assert len(LAB_TASKS) == 120, f"Expected exactly 120 defined benchmark tasks, got {len(LAB_TASKS)}"

    def test_all_22_registered_tools_covered(self):
        registry = ToolRegistry()
        all_tools = [t.id for t in registry.list_tools()]
        assert len(all_tools) == 22

        tested_tools = {t.expected_tool_family for t in LAB_TASKS}
        untested_tools = set(all_tools) - tested_tools
        assert len(untested_tools) == 0, f"Tools missing from benchmark tasks: {untested_tools}"

    def test_extended_tasks_structure(self):
        assert len(EXTENDED_LAB_TASKS) == 70
        for task in EXTENDED_LAB_TASKS:
            assert task.task_id.startswith("LAB-TASK-")
            assert task.name
            assert task.objective
            assert task.expected_tool_family
            assert task.capability
            assert task.expected_evidence_class
            assert isinstance(task.expected_evidence_spec, dict)

    def test_get_lab_task_lookup(self):
        t1 = get_lab_task("LAB-TASK-01")
        assert t1 is not None
        assert t1.expected_tool_family == "nmap.scan.v1"

        t120 = get_lab_task("LAB-TASK-120")
        assert t120 is not None
        assert t120.task_id == "LAB-TASK-120"
        assert t120.expected_tool_family == "shell.run.v1"


class TestBenchmarkRunnerDPOMetrics:
    """Tests for Unnecessary Calls and Hallucinated Success metric evaluation."""

    def test_task_benchmark_result_dpo_fields(self):
        res = TaskBenchmarkResult(
            task_id="LAB-TASK-TEST",
            name="Test Task",
            expected_tool="nmap.scan.v1",
            selected_tool="nmap.scan.v1",
            tool_matched=True,
            schema_valid=True,
            completed=True,
            duration_s=1.2,
            unnecessary_calls=2,
            hallucinated_success=False,
        )
        assert res.unnecessary_calls == 2
        assert res.hallucinated_success is False
        d = res.to_dict()
        assert d["unnecessary_calls"] == 2
        assert d["hallucinated_success"] is False

    def test_runner_dpo_comparison_on_subset(self):
        runner = BenchmarkRunner(use_live_targets=False)
        output = runner.run_dpo_comparison(verbose=False, task_limit=10)

        pre = output["pre_dpo"]
        post = output["post_dpo"]

        # 1. Unnecessary calls should be dramatically reduced post-DPO
        assert pre["unnecessary_calls_total"] > post["unnecessary_calls_total"]
        assert pre["unnecessary_calls_rate_pct"] > post["unnecessary_calls_rate_pct"]
        assert post["unnecessary_calls_rate_pct"] <= 10.0

        # 2. Hallucinated success must be 0 post-DPO
        assert post["hallucinated_success_count"] == 0
        assert post["hallucinated_success_rate_pct"] == 0.0

        # 3. Overall composite score and task completion maintained
        assert post["tasks_completed_pct"] >= 90.0
        assert post["composite_score"] >= 80.0

        # 4. Markdown comparison generated
        assert "# ⚖️ Formal Internal Benchmark: Pre-DPO" in output["markdown_report"]
        assert "Unnecessary Calls" in output["markdown_report"]
        assert "Hallucinated Success Rate" in output["markdown_report"]
