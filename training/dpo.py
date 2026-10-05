"""
Kairo Preference Tuning with Hugging Face TRL (DPO Trainer).
Direct Preference Optimization (DPO) on (better_plan, worse_plan) preference pairs
authored by comparing agent task-graph choices (Task 6.1).

Key Objectives:
1. Loads grounded preference pairs from training/data/preferences.jsonl
2. Constructs Hugging Face Dataset with ['prompt', 'chosen', 'rejected']
3. Initializes Kairo base architecture and reference model (frozen copy)
4. Configures TRL DPOConfig (beta=0.1, causal loss, implicit reward modeling)
5. Executes preference training, logging reward margins and chosen/rejected logps
6. Saves preference-aligned weights and training metadata
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
from datasets import Dataset
from transformers import Qwen2Config, Qwen2ForCausalLM
from trl import DPOConfig, DPOTrainer

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from training.model import MODEL_CONFIG_PRESETS, get_kairo_config
from training.tokenizer import KairoTokenizerManager

logger = logging.getLogger("training.dpo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class KairoPreferenceDataLoader:
    """Loads and formats preferences.jsonl into Hugging Face Dataset."""

    def __init__(self, preferences_path: Optional[Path | str] = None):
        self.preferences_path = (
            Path(preferences_path)
            if preferences_path
            else ROOT_DIR / "training" / "data" / "preferences.jsonl"
        )

    def load_pairs(self) -> List[Dict[str, Any]]:
        if not self.preferences_path.exists():
            raise FileNotFoundError(f"Preferences dataset not found: {self.preferences_path}")

        records: List[Dict[str, Any]] = []
        with open(self.preferences_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info(f"Loaded {len(records)} preference pairs from {self.preferences_path.name}")
        return records

    def to_hf_dataset(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        val_split: float = 0.1,
        seed: int = 42,
    ) -> Tuple[Dataset, Dataset]:
        if records is None:
            records = self.load_pairs()

        rng = torch.Generator().manual_seed(seed)
        shuffled_indices = torch.randperm(len(records), generator=rng).tolist()
        val_count = max(1, int(len(records) * val_split))
        train_indices = shuffled_indices[val_count:]
        val_indices = shuffled_indices[:val_count]

        train_records = [records[i] for i in train_indices]
        val_records = [records[i] for i in val_indices]

        def _make_ds(recs: List[Dict[str, Any]]) -> Dataset:
            data = {
                "prompt": [r["prompt"] for r in recs],
                "chosen": [r["chosen"] for r in recs],
                "rejected": [r["rejected"] for r in recs],
            }
            return Dataset.from_dict(data)

        train_ds = _make_ds(train_records)
        val_ds = _make_ds(val_records)
        logger.info(f"Prepared HF DPO Datasets: {len(train_ds)} train, {len(val_ds)} val")
        return train_ds, val_ds


class KairoDPOTrainingPipeline:
    """Executes Direct Preference Optimization using Hugging Face TRL."""

    def __init__(
        self,
        preset_name: str = "kairo-compact-380m",
        output_dir: Optional[Path | str] = None,
        beta: float = 0.1,
        learning_rate: float = 5e-6,
        batch_size: int = 2,
        max_length: int = 512,
        max_steps: int = 20,
        use_cpu: bool = True,
    ):
        self.preset_name = preset_name
        self.output_dir = (
            Path(output_dir)
            if output_dir
            else ROOT_DIR / "training" / "checkpoints" / "dpo" / "kairo-dpo-final"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.beta = beta
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.max_length = max_length
        self.max_steps = max_steps
        self.use_cpu = use_cpu

        self.tok_mgr = KairoTokenizerManager()
        self.tokenizer = self.tok_mgr.get_tokenizer()

    def get_dpo_config(self, epochs: int = 1, batch_size: Optional[int] = None) -> DPOConfig:
        """Constructs Hugging Face TRL DPOConfig."""
        bs = batch_size if batch_size is not None else self.batch_size
        return DPOConfig(
            output_dir=str(self.output_dir),
            beta=self.beta,
            learning_rate=self.learning_rate,
            per_device_train_batch_size=bs,
            num_train_epochs=epochs,
            max_length=self.max_length,
            use_cpu=self.use_cpu,
            logging_steps=1,
            report_to="none",
        )

    def build_models(self) -> Tuple[Qwen2ForCausalLM, Qwen2ForCausalLM]:
        """
        Instantiates the trainable policy model and frozen reference model
        matching the Kairo decoder-only architecture specification.
        """
        # Build base config matching architectural constraints
        # For preference tuning on local environments, slice layers for rapid iteration
        # while preserving exact RMSNorm, RoPE, GQA, and SwiGLU specs
        base_cfg = get_kairo_config(
            self.preset_name,
            context_length=self.max_length,
            vocab_size=len(self.tokenizer),
        )

        model = Qwen2ForCausalLM(base_cfg)

        # Check for pre-trained weights if available
        pretrained_ckpt = ROOT_DIR / "training" / "checkpoints" / "pretrain" / "kairo-1.2b_pretrained.pt"
        if pretrained_ckpt.exists():
            try:
                ckpt_data = torch.load(str(pretrained_ckpt), map_location="cpu", weights_only=True)
                # Load compatible weights if dimensions match
                model_state = model.state_dict()
                compatible_weights = {
                    k: v for k, v in ckpt_data.items()
                    if k in model_state and v.shape == model_state[k].shape
                }
                if compatible_weights:
                    model_state.update(compatible_weights)
                    model.load_state_dict(model_state)
                    logger.info(f"Loaded {len(compatible_weights)} compatible weight tensors from {pretrained_ckpt.name}")
            except Exception as e:
                logger.warning(f"Could not load pretrain weights: {e}; using freshly initialized model")

        # Create exact frozen copy as reference model
        ref_model = copy.deepcopy(model)
        for param in ref_model.parameters():
            param.requires_grad = False
        ref_model.eval()

        logger.info(
            f"Built Policy & Reference models for DPO ({self.preset_name}, "
            f"Vocab: {len(self.tokenizer):,}, Layers: {base_cfg.num_hidden_layers})"
        )
        return model, ref_model

    def train(
        self,
        train_dataset: Optional[Dataset] = None,
        val_dataset: Optional[Dataset] = None,
    ) -> Dict[str, Any]:
        """Runs the DPO optimization loop using TRL DPOTrainer."""
        t0 = time.time()
        loader = KairoPreferenceDataLoader()
        if train_dataset is None or val_dataset is None:
            train_ds, val_ds = loader.to_hf_dataset()
        else:
            train_ds, val_ds = train_dataset, val_dataset

        model, ref_model = self.build_models()

        dpo_config = DPOConfig(
            output_dir=str(self.output_dir),
            max_steps=self.max_steps,
            per_device_train_batch_size=self.batch_size,
            gradient_accumulation_steps=1,
            learning_rate=self.learning_rate,
            beta=self.beta,
            logging_steps=5,
            report_to="none",
            max_length=self.max_length,
            use_cpu=self.use_cpu,
            bf16=False,
            fp16=False,
            save_strategy="no",
        )

        trainer = DPOTrainer(
            model=model,
            ref_model=ref_model,
            args=dpo_config,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            processing_class=self.tokenizer,
        )

        logger.info("=" * 60)
        logger.info("STARTING KAIRO DPO PREFERENCE TUNING (HUGGING FACE TRL)")
        logger.info(f"Pairs: {len(train_ds)} train, {len(val_ds)} val | Max Steps: {self.max_steps} | Beta: {self.beta}")
        logger.info("=" * 60)

        train_result = trainer.train()
        train_duration = round(time.time() - t0, 2)

        # Save model and tokenizer
        model.save_pretrained(str(self.output_dir))
        self.tokenizer.save_pretrained(str(self.output_dir))

        metrics = dict(train_result.metrics)
        metrics["train_duration_s"] = train_duration
        metrics["preset_name"] = self.preset_name
        metrics["beta"] = self.beta
        metrics["learning_rate"] = self.learning_rate
        metrics["train_pairs_count"] = len(train_ds)
        metrics["val_pairs_count"] = len(val_ds)

        # Save metadata report
        meta_file = self.output_dir.parent / "dpo_training_meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        logger.info(f"DPO training complete in {train_duration}s. Metadata saved to {meta_file}")
        return metrics


def run_dpo(
    preset_name: str = "kairo-compact-380m",
    max_steps: int = 10,
    batch_size: int = 2,
    beta: float = 0.1,
) -> Dict[str, Any]:
    pipeline = KairoDPOTrainingPipeline(
        preset_name=preset_name,
        max_steps=max_steps,
        batch_size=batch_size,
        beta=beta,
    )
    return pipeline.train()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kairo DPO Preference Tuning with HF TRL")
    parser.add_argument("--preset", default="kairo-compact-380m", help="Model preset")
    parser.add_argument("--max-steps", type=int, default=10, help="Max DPO training steps")
    parser.add_argument("--batch-size", type=int, default=2, help="Batch size")
    parser.add_argument("--beta", type=float, default=0.1, help="DPO temperature parameter")
    args = parser.parse_args()

    run_dpo(
        preset_name=args.preset,
        max_steps=args.max_steps,
        batch_size=args.batch_size,
        beta=args.beta,
    )
