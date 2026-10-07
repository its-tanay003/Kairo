"""
Unit tests for Kairo GRPO Reinforcement Learning Pipeline and Verifiable Rewards.
Verifies:
1. Schema-validity verifiable reward calculations.
2. Task-completion verifiable reward calculations.
3. GRPO dataset generation and formatting across benchmark tasks.
4. GRPO configuration constraints (batch divisibility, beta penalty, generation count).
"""

import json
import pytest
from datasets import Dataset

from lab.tasks import LAB_TASKS, LabTask
from training.grpo import (
    VerifiableRewardEngine,
    KairoGRPODataLoader,
    KairoGRPOTrainingPipeline,
)
from training.schema_reward import ToolSpecSchemaValidator


@pytest.fixture
def reward_engine() -> VerifiableRewardEngine:
    return VerifiableRewardEngine()


def test_schema_validity_reward_valid_call(reward_engine: VerifiableRewardEngine):
    """Verifies that fully valid schema tool calls receive maximum reward."""
    valid_call = json.dumps({
        "tool": "nmap.scan.v1",
        "parameters": {
            "target": "192.168.1.10",
            "ports": "22,80,443",
            "scan_type": "sS"
        }
    })
    rewards = reward_engine.schema_validity_reward_fn(
        prompts=["test prompt"],
        completions=[valid_call],
    )
    assert len(rewards) == 1
    assert rewards[0] == 1.0


def test_schema_validity_reward_malformed_json(reward_engine: VerifiableRewardEngine):
    """Verifies that non-parseable JSON completions receive 0.0 reward."""
    malformed = "I will now scan the network using nmap target 192.168.1.10"
    rewards = reward_engine.schema_validity_reward_fn(
        prompts=["test prompt"],
        completions=[malformed],
    )
    assert len(rewards) == 1
    assert rewards[0] == 0.0


def test_schema_validity_reward_unregistered_tool(reward_engine: VerifiableRewardEngine):
    """Verifies that tool calls citing non-existent tools receive penalized reward (0.2)."""
    fake_tool = json.dumps({
        "tool": "nonexistent.fake_scanner",
        "parameters": {"target": "192.168.1.10"}
    })
    rewards = reward_engine.schema_validity_reward_fn(
        prompts=["test prompt"],
        completions=[fake_tool],
    )
    assert len(rewards) == 1
    assert rewards[0] == 0.2


def test_task_completion_reward_exact_match(reward_engine: VerifiableRewardEngine):
    """Verifies task completion reward when tool, target, and parameters match."""
    completion = json.dumps({
        "tool": "network.nmap_scan",
        "parameters": {
            "target": "10.0.0.5",
            "ports": "80,443"
        }
    })
    rewards = reward_engine.task_completion_reward_fn(
        prompts=["scan 10.0.0.5"],
        completions=[completion],
        expected_tool=["network.nmap_scan"],
        expected_target=["10.0.0.5"],
    )
    assert len(rewards) == 1
    # 0.5 (tool match) + 0.3 (target match) + 0.2 (params populated) = 1.0
    assert rewards[0] == pytest.approx(1.0, 0.01)


def test_task_completion_reward_mismatched_tool(reward_engine: VerifiableRewardEngine):
    """Verifies penalty when an incorrect tool family is chosen."""
    completion = json.dumps({
        "tool": "web.sqlmap_scan",
        "parameters": {
            "target": "10.0.0.5",
        }
    })
    rewards = reward_engine.task_completion_reward_fn(
        prompts=["scan 10.0.0.5 with nmap"],
        completions=[completion],
        expected_tool=["network.nmap_scan"],
        expected_target=["10.0.0.5"],
    )
    assert len(rewards) == 1
    # 0.0 (tool mismatch) + 0.3 (target match) + 0.2 (params) = 0.5
    assert rewards[0] == pytest.approx(0.5, 0.01)


def test_task_completion_reward_non_json(reward_engine: VerifiableRewardEngine):
    """Verifies task completion reward is 0.0 for conversational output."""
    completion = "Sure, I can scan 10.0.0.5 using network.nmap_scan for you!"
    rewards = reward_engine.task_completion_reward_fn(
        prompts=["scan 10.0.0.5 with nmap"],
        completions=[completion],
        expected_tool=["network.nmap_scan"],
        expected_target=["10.0.0.5"],
    )
    assert len(rewards) == 1
    assert rewards[0] == 0.0


def test_grpo_data_loader_builds_benchmark_dataset():
    """Verifies that KairoGRPODataLoader formats all 120 benchmark tasks."""
    loader = KairoGRPODataLoader()
    dataset = loader.build_dataset()

    assert isinstance(dataset, Dataset)
    assert len(dataset) == len(LAB_TASKS)
    assert len(dataset) == 120
    assert "prompt" in dataset.column_names
    assert "expected_tool" in dataset.column_names
    assert "expected_target" in dataset.column_names
    assert "task_id" in dataset.column_names

    sample = dataset[0]
    assert "<|im_start|>system" in sample["prompt"]
    assert "<|im_start|>user" in sample["prompt"]
    assert "<|im_start|>assistant" in sample["prompt"]
    assert len(sample["expected_tool"]) > 0
    assert len(sample["expected_target"]) > 0


def test_grpo_pipeline_configuration():
    """Verifies GRPO hyperparameters and batch size divisibility constraint."""
    pipeline = KairoGRPOTrainingPipeline(
        num_generations=2,
        beta=0.04,
        max_steps=2,
        use_cpu=True,
    )
    config = pipeline.get_grpo_config()

    assert config.num_generations == 2
    assert config.beta == 0.04
    assert config.max_steps == 2
    assert config.use_cpu is True
    # per_device_train_batch_size must be >= num_generations and divisible
    assert config.per_device_train_batch_size >= config.num_generations
    assert config.per_device_train_batch_size % config.num_generations == 0
