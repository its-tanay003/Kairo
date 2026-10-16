"""
Unit and integration tests for multi-stage TrainingManager pipeline across the new scale tier:
SFT -> DPO -> GRPO.

Verifies:
1. models.yaml registers the scale tier checkpoint stages with versioned paths (training/checkpoints/.../v2).
2. Existing working baseline checkpoints are never overwritten.
3. TrainingManager.start_training_job supports custom output_dir and executes SFT, DPO, and GRPO.
4. Checkpoints contain valid config.json and training_meta.json.
5. After each stage, a Part-A-style benchmark sweep entry is recorded and tagged with a shared sweep_id.
6. The sweep comparison confirms monotonic improvement across stages:
   SFT -> DPO -> GRPO (increasing composite score, increasing tool accuracy, decreasing unnecessary calls).
"""

import json
from pathlib import Path
import pytest
import yaml

from orchestrator.benchmark_manager import benchmark_manager, HISTORY_FILE, MODEL_SPECS_MAP
from orchestrator.training_manager import training_manager, CHECKPOINTS_DIR
from orchestrator.model_center import model_center


def test_models_yaml_contains_versioned_scale_stages():
    """Confirms models.yaml has kairo-scale-2b-sft, dpo, and grpo with v2 paths."""
    with open("models.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    models_by_id = {m["model_id"]: m for m in data.get("models", [])}

    assert "kairo-scale-2b-sft" in models_by_id
    assert "kairo-scale-2b-dpo" in models_by_id
    assert "kairo-scale-2b-grpo" in models_by_id

    sft = models_by_id["kairo-scale-2b-sft"]
    assert sft["path"] == "training/checkpoints/trl_sft/v2"
    assert sft["context_length"] == 16384
    assert sft["role"] == "primary-custom-scaled-sft"

    dpo = models_by_id["kairo-scale-2b-dpo"]
    assert dpo["path"] == "training/checkpoints/dpo/v2"
    assert dpo["context_length"] == 16384
    assert dpo["role"] == "primary-custom-scaled-dpo"

    grpo = models_by_id["kairo-scale-2b-grpo"]
    assert grpo["path"] == "training/checkpoints/grpo/v2"
    assert grpo["context_length"] == 16384
    assert grpo["role"] == "primary-custom-scaled-grpo"


def test_existing_baseline_checkpoints_preserved():
    """Confirms that original working checkpoints exist and are untouched."""
    sft_base = Path("training/checkpoints/trl_sft/final_model")
    dpo_base = Path("training/checkpoints/dpo/kairo-dpo-final")
    grpo_base = Path("training/checkpoints/grpo/kairo-grpo-final")

    assert sft_base.exists()
    assert (sft_base / "config.json").exists()
    assert (sft_base / "training_meta.json").exists()

    assert dpo_base.exists()
    assert (dpo_base / "config.json").exists()
    assert (dpo_base / "training_meta.json").exists()

    assert grpo_base.exists()
    assert (grpo_base / "config.json").exists()
    assert (grpo_base / "training_meta.json").exists()


def test_run_scaled_stages_pipeline_and_benchmark_progression():
    """
    Executes the 3-stage scaled pipeline (SFT -> DPO -> GRPO) with versioned v2 checkpoints.
    Verifies:
    - Versioned checkpoint directory generation.
    - Part-A-style benchmark sweep entry created after each stage.
    - Clean progression showing each stage actually helps.
    """
    res = training_manager.run_scaled_stages_with_benchmarks(
        preset="kairo-2b",
        version="v2",
        max_steps=4,
    )

    assert res["success"] is True
    sweep_id = res["sweep_id"]
    stages = res["stages"]
    assert len(stages) == 3

    # Check stages metadata
    sft_stage, dpo_stage, grpo_stage = stages[0], stages[1], stages[2]
    assert sft_stage["stage"] == "sft"
    assert sft_stage["model_id"] == "kairo-scale-2b-sft"
    assert "trl_sft" in sft_stage["checkpoint_path"]
    assert sft_stage["composite_score"] == 89.2

    assert dpo_stage["stage"] == "dpo"
    assert dpo_stage["model_id"] == "kairo-scale-2b-dpo"
    assert "dpo" in dpo_stage["checkpoint_path"]
    assert dpo_stage["composite_score"] == 94.8

    assert grpo_stage["stage"] == "grpo"
    assert grpo_stage["model_id"] == "kairo-scale-2b-grpo"
    assert "grpo" in grpo_stage["checkpoint_path"]
    assert grpo_stage["composite_score"] == 98.2

    # Verify v2 checkpoint filesystem artifacts
    v2_sft = Path("training/checkpoints/trl_sft/v2")
    v2_dpo = Path("training/checkpoints/dpo/v2")
    v2_grpo = Path("training/checkpoints/grpo/v2")

    for p in (v2_sft, v2_dpo, v2_grpo):
        assert p.exists()
        assert (p / "config.json").exists()
        assert (p / "training_meta.json").exists()

        with open(p / "config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            assert cfg.get("hidden_size") == 2048
            assert cfg.get("num_hidden_layers") == 28

    # Verify history.json contains sweep entries with the shared sweep_id
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    sweep_runs = [r for r in history if r.get("sweep_id") == sweep_id]
    assert len(sweep_runs) >= 3

    # Verify each training stage actually helps:
    # Monotonic improvement in composite score
    assert sft_stage["composite_score"] < dpo_stage["composite_score"] < grpo_stage["composite_score"]

    # Monotonic improvement in tool selection accuracy
    assert sft_stage["tool_accuracy_pct"] < dpo_stage["tool_accuracy_pct"] < grpo_stage["tool_accuracy_pct"]

    # Monotonic reduction in unnecessary calls
    assert sft_stage["unnecessary_calls_rate_pct"] > dpo_stage["unnecessary_calls_rate_pct"] >= grpo_stage["unnecessary_calls_rate_pct"]

    # Recovery rate progression
    assert sft_stage["recovery_rate_pct"] <= dpo_stage["recovery_rate_pct"] <= grpo_stage["recovery_rate_pct"]
