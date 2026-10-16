"""
Unit and Integration Tests for Tier C Conservative Model Scaling & pretrain_scale Training Pipeline.

Verifies:
1. models.yaml contains kairo-scale-2b targeting conservative Tier C scaling (1.5B-2B range).
2. kairo-2b architecture preset complies with RMSNorm + RoPE + GQA + SwiGLU + 16k context.
3. training_manager.start_training_job(job_type="pretrain_scale") executes across the 4 stages:
   [Domain Continuation -> TRL SFT -> DPO -> GRPO] initialized from Task B.1 datasets.
4. Checkpoints for all stages are saved at the paths configured in models.yaml.
"""

import json
import os
from pathlib import Path
import time
import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.model_center import ModelCenter
from orchestrator.training_manager import training_manager, CHECKPOINTS_DIR, DATA_DIR
from training.model import (
    get_kairo_config,
    verify_architecture_spec,
    MODEL_CONFIG_PRESETS,
)


def test_models_yaml_contains_kairo_scale_2b():
    """Verifies models.yaml catalog includes the new Tier C conservative scaled entry."""
    models_path = ROOT_DIR / "models.yaml"
    assert models_path.exists(), "models.yaml must exist"

    with open(models_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = cfg.get("models", [])
    model_ids = [m.get("model_id") for m in models]
    assert "kairo-scale-2b" in model_ids, "kairo-scale-2b must be in models.yaml"

    scale_2b = next(m for m in models if m.get("model_id") == "kairo-scale-2b")
    assert scale_2b["runtime"] == "transformers"
    assert scale_2b["quantization"] == "FP32"
    assert scale_2b["context_length"] == 16384
    assert scale_2b["role"] == "primary-custom-scaled-tier-c"
    assert "training/checkpoints/pretrain" in scale_2b["path"]
    assert "kairo-2b" in scale_2b["path"]
    assert "Task B.1" in scale_2b["description"] or "Tier C" in scale_2b["description"]


def test_kairo_2b_architecture_compliance():
    """Verifies that kairo-2b conforms to blueprint requirements and 1.5B-2B conservative sizing."""
    import torch
    from transformers import Qwen2ForCausalLM

    assert "kairo-2b" in MODEL_CONFIG_PRESETS, "kairo-2b preset must be registered in MODEL_CONFIG_PRESETS"
    cfg = get_kairo_config("kairo-2b")

    with torch.device("meta"):
        meta_model = Qwen2ForCausalLM(cfg)
        total_params = sum(p.numel() for p in meta_model.parameters())

    params_billions = total_params / 1e9
    assert 1.5 <= params_billions <= 2.2, f"Expected 1.5B-2.2B parameters, got {params_billions:.2f}B"

    spec = verify_architecture_spec(cfg, total_params)
    assert spec["all_passed"] is True, f"Architecture verification failed: {spec}"
    assert spec["has_rmsnorm"] is True
    assert spec["has_rope"] is True
    assert spec["has_gqa"] is True
    assert spec["has_swiglu"] is True
    assert spec["context_valid_8k_16k"] is True
    assert spec["context_length"] == 16384
    assert spec["params_in_1_5b_2b_range"] is True


def test_pretrain_scale_job_execution_and_telemetry():
    """
    Tests starting a pretrain_scale job, inspecting its Task B.1 asset initialization,
    and verifying progress across the 4 stages (pretrain, trl_sft, dpo, grpo).
    """
    # Verify Task B.1 datasets exist
    assert (DATA_DIR / "train_cleaned.jsonl").exists()
    assert (DATA_DIR / "preferences.jsonl").exists()
    assert (DATA_DIR / "security_corpus.txt").exists()

    job = training_manager.start_training_job(
        job_type="pretrain_scale",
        preset="kairo-2b",
        epochs=1,
        learning_rate=3e-5,
        batch_size=2,
        max_steps=8,  # 2 steps per stage for fast deterministic test execution
    )

    assert isinstance(job, dict)
    job_id = job["id"]
    assert job["job_type"] == "pretrain_scale"
    assert job["preset"] == "kairo-2b"
    assert job["pipeline_stages"] == ["pretrain", "trl_sft", "dpo", "grpo"]
    assert "Task B.1" in job["dataset_source"]

    # Poll until completion or timeout
    start_time = time.time()
    completed = False
    while time.time() - start_time < 20:
        time.sleep(0.3)
        polled = training_manager.get_training_job(job_id)
        if polled and polled["status"] == "completed":
            completed = True
            break

    assert completed is True, f"Job {job_id} did not complete in time"
    final_job = training_manager.get_training_job(job_id)
    assert final_job["status"] == "completed"
    assert final_job["progress_pct"] == 100.0
    assert final_job["current_step"] == 8
    assert len(final_job["metrics_history"]) == 8

    # Verify stage progression in metrics history
    stages_seen = set(m.get("stage") for m in final_job["metrics_history"])
    assert stages_seen == {"pretrain", "trl_sft", "dpo", "grpo"}

    # Verify logs mention all 4 stages
    log_text = " ".join(final_job["logs"])
    assert "Domain-Continuation Pretraining" in log_text
    assert "Supervised Fine-Tuning" in log_text
    assert "Direct Preference Optimization" in log_text
    assert "Group Relative Policy Optimization" in log_text

    # Verify checkpoints and metadata saved per models.yaml paths
    pretrain_meta = CHECKPOINTS_DIR / "pretrain" / "kairo-2b_meta.json"
    pretrain_pt = CHECKPOINTS_DIR / "pretrain" / "kairo-2b_pretrained.pt"
    sft_model = CHECKPOINTS_DIR / "trl_sft" / "final_model"
    dpo_final = CHECKPOINTS_DIR / "dpo" / "kairo-dpo-final"
    grpo_final = CHECKPOINTS_DIR / "grpo" / "kairo-grpo-final"

    assert pretrain_meta.exists()
    assert pretrain_pt.exists()
    assert (sft_model / "config.json").exists()
    assert (dpo_final / "training_meta.json").exists()
    assert (grpo_final / "training_meta.json").exists()


def test_pretrain_scale_stop_cancellation():
    """Verifies that an operator can cancel a running pretrain_scale job."""
    job = training_manager.start_training_job(
        job_type="pretrain_scale",
        preset="kairo-2b",
        max_steps=50,
    )
    job_id = job["id"]
    time.sleep(0.2)

    stopped = training_manager.stop_training_job(job_id)
    assert stopped is True

    time.sleep(0.4)
    polled = training_manager.get_training_job(job_id)
    assert polled["status"] in ("cancelled", "completed")
