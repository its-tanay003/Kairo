"""
Tests for Kairo TRL SFT Training, Schema Validation Rewards, and Data Filtering (Track B).
Verifies:
1. ToolSpec schema rewards across positive, negative, and out-of-scope targets
2. Dataset cleaning step discarding invalid/unparseable records
3. Hugging Face TRL SFTTrainer integration with live schema validation eval callback
"""

import os
import json
import pytest
from pathlib import Path

from training.schema_reward import (
    ToolSpecSchemaValidator,
    clean_dataset_with_schema_filter,
    SchemaValidationEvalCallback
)
from training.dataset import load_hf_sft_dataset, KairoDataCollator
from training.tokenizer import KairoTokenizerManager
from training.model import get_kairo_config
from training.trl_sft import run_data_cleaning_filter


def test_schema_reward_validation_levels():
    """Verify granular reward scoring: 1.0, 0.7, 0.5, 0.2, 0.0."""
    validator = ToolSpecSchemaValidator()
    assert len(validator.toolspecs) == 18

    # 1.0: Perfect valid schema (nikto on authorized target)
    pos_res = validator.validate_tool_call({
        "tool_id": "nikto.scan.v1",
        "arguments": {"host": "192.168.1.10", "port": 80}
    })
    assert pos_res.is_valid is True
    assert pos_res.reward == 1.0
    assert pos_res.scope_valid is True
    assert len(pos_res.errors) == 0

    # 0.7: Valid schema, but target is out of Scope Contract
    out_scope_res = validator.validate_tool_call({
        "tool_id": "nikto.scan.v1",
        "arguments": {"host": "8.8.8.8", "port": 80}
    })
    assert out_scope_res.is_valid is False
    assert out_scope_res.reward == 0.7
    assert out_scope_res.scope_valid is False

    # 0.5: Recognized tool, but missing required inputs (hydra missing protocol)
    missing_req_res = validator.validate_tool_call({
        "tool_id": "hydra.brute.v1",
        "arguments": {"target": "192.168.1.50"}
    })
    assert missing_req_res.is_valid is False
    assert missing_req_res.reward == 0.5

    # 0.2: Valid JSON, but unregistered tool name
    unregistered_res = validator.validate_tool_call({
        "tool_id": "nonexistent_scanner_v99",
        "arguments": {"target": "192.168.1.10"}
    })
    assert unregistered_res.is_valid is False
    assert unregistered_res.reward == 0.2

    # 0.0: Failed JSON parsing / corrupt text
    unparseable_res = validator.validate_tool_call("MALFORMED_OUTPUT_NOT_JSON")
    assert unparseable_res.is_valid is False
    assert unparseable_res.reward == 0.0
    assert unparseable_res.parse_success is False


def test_xml_and_markdown_tool_call_extraction():
    """Verify tool-call extraction from ChatML tags and markdown blocks."""
    validator = ToolSpecSchemaValidator()

    # ChatML <tool_call>...</tool_call>
    chatml_text = (
        "I will now run Nmap port scan.\n"
        "<tool_call>\n"
        '{\n  "name": "nmap.scan.v1",\n  "arguments": {\n    "target": "192.168.1.20"\n  }\n}\n'
        "</tool_call>"
    )
    res_chatml = validator.validate_tool_call(chatml_text)
    assert res_chatml.parse_success is True
    assert res_chatml.tool_id == "nmap.scan.v1"
    assert res_chatml.is_valid is True
    assert res_chatml.reward == 1.0

    # Markdown json block
    md_text = (
        "Here is the invocation:\n"
        "```json\n"
        '{\n  "tool_id": "whois.lookup.v1",\n  "arguments": {"target": "target.local"}\n}\n'
        "```"
    )
    res_md = validator.validate_tool_call(md_text)
    assert res_md.parse_success is True
    assert res_md.tool_id == "whois.lookup.v1"
    assert res_md.is_valid is True
    assert res_md.reward == 1.0


def test_schema_cleaning_filter_execution(tmp_path):
    """Verify dataset cleaning discards corrupt/invalid examples."""
    validator = ToolSpecSchemaValidator()

    sample_file = tmp_path / "raw_samples.jsonl"
    clean_file = tmp_path / "clean_samples.jsonl"

    valid_record = {
        "id": "valid_01",
        "tool_call": {"tool_id": "system_ping", "arguments": {"echo_token": "ping1"}},
        "user_goal": "Ping host",
        "task_graph": {},
        "observation": "ok",
        "next_step": "done"
    }
    invalid_record = {
        "id": "invalid_01",
        "tool_call": {"tool_id": "nikto.scan.v1", "arguments": {"port": 80}},  # missing required 'host'
        "user_goal": "Scan host",
        "task_graph": {},
        "observation": "fail",
        "next_step": "done"
    }
    unparseable_record = "CORRUPT_JSON_LINE"

    with open(sample_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(valid_record) + "\n")
        f.write(json.dumps(invalid_record) + "\n")
        f.write(unparseable_record + "\n")

    stats = clean_dataset_with_schema_filter(
        str(sample_file), str(clean_file), min_reward=1.0, validator=validator
    )

    assert stats["total_records"] == 3
    assert stats["retained_records"] == 1
    assert stats["discarded_records"] == 2
    assert stats["pass_rate_pct"] == 33.33

    # Check clean output
    with open(clean_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    assert len(lines) == 1
    assert lines[0]["id"] == "valid_01"
    assert lines[0]["metadata"]["schema_reward"] == 1.0
    assert lines[0]["metadata"]["schema_validated"] is True


def test_trl_sft_trainer_integration(tmp_path):
    """Verify Hugging Face TRL SFTTrainer + SFTConfig and SchemaValidationEvalCallback."""
    from trl import SFTTrainer, SFTConfig
    from transformers import Qwen2ForCausalLM

    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()

    # Create a tiny 2-sample dataset
    sample_file = tmp_path / "tiny_sft.jsonl"
    records = [
        {
            "id": "sample_1",
            "user_goal": "Ping check",
            "task_graph": {},
            "tool_call": {"tool_id": "system_ping", "arguments": {"echo_token": "p1"}},
            "observation": "ok",
            "next_step": "complete",
            "conversation": [
                {"role": "user", "content": "Ping target.local"},
                {"role": "assistant", "content": "Executing ping", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "system_ping", "arguments": '{"echo_token": "p1"}'}}
                ]}
            ]
        },
        {
            "id": "sample_2",
            "user_goal": "DNS check",
            "task_graph": {},
            "tool_call": {"tool_id": "dig.lookup.v1", "arguments": {"domain": "target.local"}},
            "observation": "ok",
            "next_step": "complete",
            "conversation": [
                {"role": "user", "content": "Lookup DNS for target.local"},
                {"role": "assistant", "content": "Querying DNS", "tool_calls": [
                    {"id": "c2", "type": "function", "function": {"name": "dig.lookup.v1", "arguments": '{"domain": "target.local"}'}}
                ]}
            ]
        }
    ]
    with open(sample_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    hf_ds = load_hf_sft_dataset(str(sample_file), tokenizer_manager=tok_mgr, max_length=128)
    collator = KairoDataCollator(pad_token_id=tokenizer.pad_token_id)

    cfg = get_kairo_config("kairo-base-490m", context_length=128, vocab_size=len(tokenizer), num_hidden_layers=2)
    model = Qwen2ForCausalLM(cfg)

    sft_config = SFTConfig(
        output_dir=str(tmp_path / "out"),
        max_steps=1,
        per_device_train_batch_size=2,
        learning_rate=1e-4,
        use_cpu=True,
        report_to="none"
    )

    validator = ToolSpecSchemaValidator()
    eval_callback = SchemaValidationEvalCallback(validator=validator, tokenizer=tokenizer)

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=hf_ds,
        eval_dataset=hf_ds,
        data_collator=collator,
        processing_class=tokenizer,
        callbacks=[eval_callback]
    )

    train_res = trainer.train()
    assert train_res.training_loss is not None
    assert train_res.global_step == 1
