"""
Kairo Group Relative Policy Optimization (GRPO) Training Pipeline.
Executes preference and policy optimization using verifiable rewards:
1. schema_validity_reward: Verifiable JSON syntax, ToolSpec compliance, and Scope Contract validity.
2. task_completion_reward: Verifiable tool selection, target resolution, and parameter completeness.

Adheres to the blueprint's training pipeline for reinforcement learning with verifiable reward signals.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
from datasets import Dataset
from transformers import PreTrainedTokenizer, Qwen2Config, Qwen2ForCausalLM
from trl import GRPOConfig, GRPOTrainer

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lab.tasks import LAB_TASKS, LabTask
from registry.loader import ToolRegistry
from training.model import MODEL_CONFIG_PRESETS, get_kairo_config
from training.schema_reward import ToolSpecSchemaValidator
from training.tokenizer import KairoTokenizerManager

logger = logging.getLogger("training.grpo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class VerifiableRewardEngine:
    """
    Computes verifiable rewards for GRPO group rollouts:
    1. Schema Validity: Programmatic validation of JSON syntax, parameter types, and Scope Contract boundaries.
    2. Task Completion: Verification of correct tool selection, target resolution, and required parameter population.
    """

    def __init__(
        self,
        validator: Optional[ToolSpecSchemaValidator] = None,
        registry: Optional[ToolRegistry] = None,
    ):
        self.validator = validator or ToolSpecSchemaValidator()
        self.registry = registry or ToolRegistry()

    def schema_validity_reward_fn(
        self,
        prompts: List[str],
        completions: List[str],
        **kwargs: Any,
    ) -> List[float]:
        """
        Verifiable reward function for ToolSpec schema validity.
        Returns a float in [0.0, 1.0] for each completion.
        """
        rewards: List[float] = []
        for completion in completions:
            text = completion if isinstance(completion, str) else str(completion)
            val_res = self.validator.validate_tool_call(text)
            rewards.append(float(val_res.reward))
        return rewards

    def task_completion_reward_fn(
        self,
        prompts: List[str],
        completions: List[str],
        expected_tool: Optional[List[str]] = None,
        expected_target: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[float]:
        """
        Verifiable reward function for task completion and goal fulfillment.
        Checks tool match (+0.5), target match (+0.3), and required parameter completeness (+0.2).
        """
        rewards: List[float] = []
        exp_tools = expected_tool or [""] * len(completions)
        exp_targets = expected_target or [""] * len(completions)

        for i, completion in enumerate(completions):
            text = completion if isinstance(completion, str) else str(completion)
            target_tool = exp_tools[i] if i < len(exp_tools) else ""
            target_host = exp_targets[i] if i < len(exp_targets) else ""

            tool_id, args, ok, _ = self.validator.extract_tool_call(text)
            if not ok or not tool_id:
                rewards.append(0.0)
                continue

            score = 0.0

            # 1. Tool Selection Match (+0.5)
            if target_tool:
                # Direct match or alias
                if tool_id == target_tool or target_tool in tool_id or tool_id.split(".")[0] in target_tool:
                    score += 0.5
                else:
                    score += 0.0
            else:
                score += 0.3 if tool_id in self.validator.registered_tool_ids else 0.0

            # 2. Target Resolution Match (+0.3)
            args_str = json.dumps(args or {})
            if target_host and target_host in args_str:
                score += 0.3
            elif args and any(k in args for k in ["target", "url", "host", "ip", "interface"]):
                score += 0.2

            # 3. Parameter Completeness & Non-empty payload (+0.2)
            if args and len(args) >= 1:
                has_non_empty = any(v not in ("", None, [], {}) for v in args.values())
                if has_non_empty:
                    score += 0.2

            rewards.append(min(1.0, max(0.0, score)))

        return rewards


class KairoGRPODataLoader:
    """
    Constructs training prompts with ground-truth verifiable metadata
    sourced from the versioned benchmark task set and execution traces.
    """

    def __init__(self, tasks: Optional[List[LabTask]] = None):
        self.tasks = tasks or list(LAB_TASKS)

    def build_dataset(self) -> Dataset:
        """
        Builds a Hugging Face Dataset with:
        ['prompt', 'expected_tool', 'expected_target', 'task_id']
        """
        prompts: List[str] = []
        expected_tools: List[str] = []
        expected_targets: List[str] = []
        task_ids: List[str] = []

        for task in self.tasks:
            prompt_text = (
                f"<|im_start|>system\n"
                f"You are Kairo, an autonomous cyber-agent. Select the optimal tool and emit a schema-validated tool-call JSON.<|im_end|>\n"
                f"<|im_start|>user\n"
                f"Objective: {task.objective}\n"
                f"Target: {task.target}\n"
                f"Capability: {task.capability}\n"
                f"Scope Contract: Target '{task.target}' authorized under Tier 1-3.<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )
            prompts.append(prompt_text)
            expected_tools.append(task.expected_tool_family)
            expected_targets.append(task.target)
            task_ids.append(task.task_id)

        data = {
            "prompt": prompts,
            "expected_tool": expected_tools,
            "expected_target": expected_targets,
            "task_id": task_ids,
        }
        dataset = Dataset.from_dict(data)
        logger.info(f"Built GRPO Dataset with {len(dataset)} task prompts across {len(self.tasks)} benchmark tasks")
        return dataset


class KairoGRPOTrainingPipeline:
    """
    Orchestrates Group Relative Policy Optimization (GRPO) with Hugging Face TRL.
    """

    def __init__(
        self,
        preset_name: str = "kairo-compact-380m",
        output_dir: Optional[Path | str] = None,
        beta: float = 0.04,
        learning_rate: float = 2e-6,
        num_generations: int = 2,
        max_completion_length: int = 128,
        max_steps: int = 10,
        use_cpu: bool = True,
    ):
        self.preset_name = preset_name
        self.output_dir = (
            Path(output_dir)
            if output_dir
            else ROOT_DIR / "training" / "checkpoints" / "grpo" / "kairo-grpo-final"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.beta = beta
        self.learning_rate = learning_rate
        self.num_generations = num_generations
        self.max_completion_length = max_completion_length
        self.max_steps = max_steps
        self.use_cpu = use_cpu

        self.tok_mgr = KairoTokenizerManager()
        self.tokenizer = self.tok_mgr.get_tokenizer()
        self.reward_engine = VerifiableRewardEngine()

    def get_grpo_config(self, epochs: int = 1, batch_size: Optional[int] = None) -> GRPOConfig:
        """Constructs Hugging Face TRL GRPOConfig."""
        bs = batch_size if batch_size is not None else self.num_generations
        return GRPOConfig(
            output_dir=str(self.output_dir),
            beta=self.beta,
            learning_rate=self.learning_rate,
            num_generations=self.num_generations,
            max_completion_length=self.max_completion_length,
            per_device_train_batch_size=bs,
            num_train_epochs=epochs,
            max_steps=self.max_steps,
            use_cpu=self.use_cpu,
            logging_steps=1,
            report_to="none",
        )

    def build_model(self) -> Qwen2ForCausalLM:
        """Instantiates policy model with weights from SFT/DPO checkpoint if available."""
        base_cfg = get_kairo_config(
            self.preset_name,
            context_length=512,
            vocab_size=len(self.tokenizer),
        )
        model = Qwen2ForCausalLM(base_cfg)

        # Load weights from DPO checkpoint or SFT checkpoint
        candidates = [
            ROOT_DIR / "training" / "checkpoints" / "dpo" / "kairo-dpo-final",
            ROOT_DIR / "training" / "checkpoints" / "trl_sft" / "final_model",
        ]
        ckpt_path = None
        for ckpt in candidates:
            if ckpt.exists() and (ckpt / "config.json").exists():
                ckpt_path = ckpt
                break

        if ckpt_path:
            model = Qwen2ForCausalLM.from_pretrained(str(ckpt_path))
            model.config.name_or_path = str(ckpt_path)
            model.config._name_or_path = str(ckpt_path)
            logger.info(f"Loaded starting weights from checkpoint: {ckpt_path.name}")
        else:
            base_cfg = get_kairo_config(
                self.preset_name,
                context_length=512,
                vocab_size=len(self.tokenizer),
            )
            model = Qwen2ForCausalLM(base_cfg)
            temp_path = self.output_dir / "init_base"
            temp_path.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(temp_path))
            model.config.name_or_path = str(temp_path)
            model.config._name_or_path = str(temp_path)
            logger.info(f"Initialized base model and saved config to {temp_path.name}")

        return model

    def train(self, dataset: Optional[Dataset] = None) -> Dict[str, Any]:
        """Executes calibrated GRPO optimization pass with verifiable reward functions."""
        if dataset is None:
            loader = KairoGRPODataLoader()
            dataset = loader.build_dataset()

        model = self.build_model()
        grpo_config = self.get_grpo_config(epochs=1)

        reward_funcs = [
            self.reward_engine.schema_validity_reward_fn,
            self.reward_engine.task_completion_reward_fn,
        ]

        logger.info(
            f"Initializing GRPOTrainer (Generations: {self.num_generations}, "
            f"Beta: {self.beta}, Steps: {self.max_steps}, CPU: {self.use_cpu})"
        )

        trainer = GRPOTrainer(
            model=model,
            reward_funcs=reward_funcs,
            args=grpo_config,
            train_dataset=dataset,
            processing_class=self.tokenizer,
        )

        start_time = time.time()
        train_result = trainer.train()
        duration_s = round(time.time() - start_time, 2)

        # Save model and artifacts
        trainer.save_model(str(self.output_dir))
        self.tokenizer.save_pretrained(str(self.output_dir))

        meta = {
            "framework": "Hugging Face TRL (GRPOTrainer)",
            "algorithm": "Group Relative Policy Optimization (GRPO)",
            "preset_name": self.preset_name,
            "beta": self.beta,
            "learning_rate": self.learning_rate,
            "num_generations": self.num_generations,
            "max_completion_length": self.max_completion_length,
            "max_steps": self.max_steps,
            "training_samples": len(dataset),
            "train_duration_s": duration_s,
            "metrics": train_result.metrics if hasattr(train_result, "metrics") else {},
            "verifiable_rewards": [
                "schema_validity_reward (ToolSpec JSON syntax, typing, scope)",
                "task_completion_reward (tool selection, target matching, params)",
            ],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        meta_file = self.output_dir.parent / "grpo_training_meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        logger.info(f"GRPO Training Complete! Saved model and metadata to {self.output_dir}")
        return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Kairo GRPO Training with Verifiable Rewards")
    parser.add_argument("--steps", type=int, default=5, help="Number of GRPO training steps")
    parser.add_argument("--generations", type=int, default=2, help="Group rollout candidate count (G)")
    parser.add_argument("--beta", type=float, default=0.04, help="KL penalty beta coefficient")
    parser.add_argument("--lr", type=float, default=2e-6, help="Learning rate")
    args = parser.parse_args()

    pipeline = KairoGRPOTrainingPipeline(
        max_steps=args.steps,
        num_generations=args.generations,
        beta=args.beta,
        learning_rate=args.lr,
    )
    pipeline.train()


if __name__ == "__main__":
    main()
