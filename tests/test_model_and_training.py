"""
Tests for Kairo Track B Model & Training Loop.
Verifies:
1. Open tokenizer loading with code/shell/JSON coverage
2. Decoder-only Transformer architecture (RMSNorm + RoPE + GQA + SwiGLU)
3. Parameter count strictly within 350M - 700M target range
4. Context target size 8k - 16k
5. PyTorch SFT Dataset and dynamic Data Collator with prompt-loss masking
6. PyTorch forward and backward passes with active gradient updates
"""

import os
import pytest
import torch
from transformers import PreTrainedTokenizerFast

from training.tokenizer import KairoTokenizerManager
from training.model import (
    get_kairo_config,
    verify_architecture_spec,
    MODEL_CONFIG_PRESETS
)
from training.dataset import KairoSFTDataset, KairoDataCollator


def test_open_tokenizer_coverage():
    """Verify tokenizer is an open tokenizer with code/shell/JSON coverage."""
    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()
    assert isinstance(tokenizer, PreTrainedTokenizerFast)
    assert len(tokenizer) >= 150000, "Expected large code-capable vocabulary"
    assert tokenizer.pad_token_id is not None

    # Test shell command with pipes and flags
    shell_cmd = "nmap -sV -sC -p 22,80,443 -oX output.xml 192.168.1.50 | tee scan.log"
    tokens = tokenizer.encode(shell_cmd)
    assert len(tokens) > 5

    # Test JSON structure
    json_str = '{"tool_id": "nikto.scan.v1", "arguments": {"host": "192.168.1.10", "port": 80}}'
    json_tokens = tokenizer.encode(json_str)
    assert len(json_tokens) > 5

    # Test chat formatting
    example = {
        "user_goal": "Scan host",
        "task_graph": {"plan_id": "p1"},
        "tool_call": {"tool_id": "system_ping", "arguments": {}},
        "observation": "alive",
        "next_step": "complete"
    }
    formatted = tok_mgr.format_sft_conversation(example)
    assert "<|im_start|>" in formatted
    assert "<|im_end|>" in formatted


def test_decoder_only_transformer_architecture():
    """
    Verify the architecture incorporates:
    - RMSNorm
    - RoPE
    - GQA
    - SwiGLU
    - Context size 8k - 16k
    """
    config = get_kairo_config("kairo-base-490m", context_length=8192)
    assert config.model_type == "qwen2", "Decoder-only CausalLM architecture"
    assert config.rms_norm_eps == 1e-6, "Must use RMSNorm with eps=1e-6"
    assert config.hidden_act == "silu", "Must use SwiGLU (silu activation)"
    assert config.num_key_value_heads < config.num_attention_heads, "Must use GQA"
    assert config.num_attention_heads == 14
    assert config.num_key_value_heads == 2
    assert config.max_position_embeddings == 8192, "Modest context target 8k"


def test_parameter_sizing_in_350m_to_700m():
    """Verify parameters for all presets fall strictly within 350M - 700M range."""
    from transformers import Qwen2ForCausalLM

    for preset_name in ["kairo-compact-380m", "kairo-base-490m", "kairo-plus-650m"]:
        cfg = get_kairo_config(preset_name)
        with torch.device("meta"):
            meta_model = Qwen2ForCausalLM(cfg)
            total_params = sum(p.numel() for p in meta_model.parameters())

        spec = verify_architecture_spec(cfg, total_params)
        assert spec["all_passed"] is True, f"Spec failed for {preset_name}: {spec}"
        assert 350_000_000 <= total_params <= 700_000_000, (
            f"Preset {preset_name} has {total_params / 1e6:.2f}M params, expected 350M - 700M"
        )


def test_sft_dataset_and_collator():
    """Verify loading from train.jsonl and dynamic batch collation with prompt-loss masking."""
    train_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "training", "data", "train.jsonl")
    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()

    dataset = KairoSFTDataset(
        train_path,
        tokenizer_manager=tok_mgr,
        max_length=512,
        max_samples=10,
        mask_prompt_labels=True
    )
    assert len(dataset) == 10

    sample = dataset[0]
    assert "input_ids" in sample
    assert "attention_mask" in sample
    assert "labels" in sample

    # Check collator
    collator = KairoDataCollator(pad_token_id=tokenizer.pad_token_id)
    batch = collator([dataset[0], dataset[1]])

    assert batch["input_ids"].shape[0] == 2
    assert batch["attention_mask"].shape[0] == 2
    assert batch["labels"].shape[0] == 2

    # Check prompt masking: prompt tokens must have label -100
    has_masked = (batch["labels"] == -100).any().item()
    has_unmasked = (batch["labels"] != -100).any().item()
    assert has_masked, "Prompt tokens should be masked with -100"
    assert has_unmasked, "Assistant response tokens should have valid target IDs"


def test_pytorch_optimization_step():
    """Verify forward + backward pass and active gradient computation with PyTorch."""
    from transformers import Qwen2ForCausalLM

    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()

    # Use a small 2-layer slice of the identical architecture for fast gradient test
    cfg = get_kairo_config("kairo-base-490m", context_length=256, num_hidden_layers=2)
    model = Qwen2ForCausalLM(cfg)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

    train_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "training", "data", "train.jsonl")
    dataset = KairoSFTDataset(train_path, tokenizer_manager=tok_mgr, max_length=128, max_samples=2)
    collator = KairoDataCollator(pad_token_id=tokenizer.pad_token_id)
    batch = collator([dataset[0], dataset[1]])

    model.train()
    optimizer.zero_grad()
    outputs = model(**batch)
    loss = outputs.loss
    assert loss is not None
    assert torch.isfinite(loss).item()

    loss.backward()

    # Verify gradients computed across layers
    grads = [p.grad for p in model.parameters() if p.grad is not None]
    assert len(grads) > 0
    assert all(torch.isfinite(g).all().item() for g in grads)

    optimizer.step()
