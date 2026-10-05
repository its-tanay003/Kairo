"""
Kairo SFT Training Pipeline with Hugging Face TRL (Track B).
Implements:
1. First-class tool-call output format training objective
2. Schema-validation reward & filtering data-cleaning step
3. SFTTrainer integration with live schema reward evaluation metrics
"""

from typing import Dict, Any, Optional
import os
import sys
import argparse
import json
from pathlib import Path
import torch
from transformers import TrainerCallback, TrainerControl, TrainerState

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from trl import SFTTrainer, SFTConfig

from training.tokenizer import KairoTokenizerManager
from training.model import (
    initialize_kairo_model,
    get_kairo_config,
    MODEL_CONFIG_PRESETS
)
from training.dataset import KairoSFTDataset, KairoDataCollator, load_hf_sft_dataset
from training.schema_reward import (
    ToolSpecSchemaValidator,
    clean_dataset_with_schema_filter,
    SchemaValidationEvalCallback
)


def run_data_cleaning_filter(
    data_dir: Optional[str] = None,
    min_reward: float = 1.0
) -> Dict[str, Any]:
    """
    Data cleaning step: discards any generated/harvested example that doesn't parse
    or whose tool call is syntactically invalid against registered ToolSpecs.
    """
    base_dir = Path(data_dir) if data_dir else ROOT_DIR / "training" / "data"
    train_in = base_dir / "train.jsonl"
    val_in = base_dir / "val.jsonl"

    train_out = base_dir / "train_cleaned.jsonl"
    val_out = base_dir / "val_cleaned.jsonl"
    report_file = base_dir / "schema_cleaning_report.json"

    validator = ToolSpecSchemaValidator()
    print("=" * 60)
    print("KAIRO DATA PIPELINE: SCHEMA-VALIDATION CLEANING & FILTERING")
    print(f"Registered ToolSpecs loaded: {len(validator.toolspecs)} tools")
    print("=" * 60)

    print(f"[1/2] Filtering training set ({train_in.name})...")
    train_stats = clean_dataset_with_schema_filter(
        str(train_in), str(train_out), min_reward=min_reward, validator=validator
    )
    print(f"      Total: {train_stats['total_records']} | "
          f"Retained: {train_stats['retained_records']} | "
          f"Discarded: {train_stats['discarded_records']} | "
          f"Pass Rate: {train_stats['pass_rate_pct']}% | "
          f"Mean Reward: {train_stats['mean_schema_reward']}")

    print(f"\n[2/2] Filtering validation set ({val_in.name})...")
    val_stats = clean_dataset_with_schema_filter(
        str(val_in), str(val_out), min_reward=min_reward, validator=validator
    )
    print(f"      Total: {val_stats['total_records']} | "
          f"Retained: {val_stats['retained_records']} | "
          f"Discarded: {val_stats['discarded_records']} | "
          f"Pass Rate: {val_stats['pass_rate_pct']}% | "
          f"Mean Reward: {val_stats['mean_schema_reward']}")

    report = {
        "min_reward_threshold": min_reward,
        "tools_evaluated_count": len(validator.toolspecs),
        "train": train_stats,
        "validation": val_stats
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nSaved cleaning report to: {report_file}")
    print("=" * 60)
    return report


def run_trl_smoke_test(preset_name: str = "kairo-base-490m") -> Dict[str, Any]:
    """
    Fast smoke test verifying:
    1. Schema reward validation on positive and negative examples
    2. Data cleaning filter execution
    3. TRL SFTTrainer initialization with Kairo model
    4. Training steps with active gradient backprop
    5. SchemaValidationEvalCallback metric calculation
    """
    print("=" * 60)
    print("KAIRO TRL SFT SMOKE TEST & SCHEMA REWARD VERIFICATION")
    print("=" * 60)

    validator = ToolSpecSchemaValidator()
    print(f"[1/5] Testing schema reward calculation across 18 ToolSpecs...")
    
    # Positive case: valid nikto call
    valid_call = {"tool_id": "nikto.scan.v1", "arguments": {"host": "192.168.1.10", "port": 80}}
    res_pos = validator.validate_tool_call(valid_call)
    assert res_pos.is_valid and res_pos.reward == 1.0, f"Expected 1.0, got {res_pos}"
    print(f"      Positive case (nikto): Reward={res_pos.reward} -> PASS")

    # Negative case: missing required arguments
    invalid_call = {"tool_id": "hydra.brute.v1", "arguments": {"target": "192.168.1.50"}}  # missing protocol
    res_neg = validator.validate_tool_call(invalid_call)
    assert not res_neg.is_valid and res_neg.reward == 0.5, f"Expected 0.5, got {res_neg}"
    print(f"      Negative case (hydra missing protocol): Reward={res_neg.reward} -> PASS")

    # Negative case: unparseable garbage text
    unparseable = "this is not json and has no tool call"
    res_unparse = validator.validate_tool_call(unparseable)
    assert not res_unparse.is_valid and res_unparse.reward == 0.0
    print(f"      Negative case (unparseable): Reward={res_unparse.reward} -> PASS")

    # 2. Run data cleaning filter
    print("\n[2/5] Running schema filter data cleaning step...")
    clean_report = run_data_cleaning_filter(min_reward=1.0)
    assert clean_report["train"]["retained_records"] >= 2000, "Expected >=2000 clean schema-verified examples"
    assert clean_report["train"]["pass_rate_pct"] >= 80.0, "Expected >=80% pass rate under strict schema filter"

    # 3. Initialize Tokenizer & Model
    print("\n[3/5] Loading tokenizer and model slice for TRL SFT...")
    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()
    
    # 2-layer slice for fast CPU smoke test
    cfg = get_kairo_config(preset_name, context_length=512, vocab_size=len(tokenizer), num_hidden_layers=2)
    from transformers import Qwen2ForCausalLM
    model = Qwen2ForCausalLM(cfg)

    # 4. Prepare SFT Datasets
    print("\n[4/5] Binding cleaned SFT datasets to TRL SFTTrainer...")
    data_dir = ROOT_DIR / "training" / "data"
    train_dataset = load_hf_sft_dataset(
        str(data_dir / "train_cleaned.jsonl"),
        tokenizer_manager=tok_mgr,
        max_length=512,
        max_samples=8
    )
    val_dataset = load_hf_sft_dataset(
        str(data_dir / "val_cleaned.jsonl"),
        tokenizer_manager=tok_mgr,
        max_length=512,
        max_samples=4
    )
    collator = KairoDataCollator(pad_token_id=tokenizer.pad_token_id)

    # TRL SFTConfig with use_cpu=True
    output_dir = str(ROOT_DIR / "training" / "trl_smoke_output")
    sft_config = SFTConfig(
        output_dir=output_dir,
        max_steps=2,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        learning_rate=1e-4,
        eval_strategy="steps",
        eval_steps=1,
        use_cpu=True,
        report_to="none"
    )

    eval_callback = SchemaValidationEvalCallback(validator=validator, tokenizer=tokenizer)

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=collator,
        processing_class=tokenizer,
        callbacks=[eval_callback]
    )

    # 5. Execute SFT training steps with live schema eval
    print("\n[5/5] Executing TRL SFTTrainer training loop...")
    train_result = trainer.train()
    eval_result = trainer.evaluate()

    print("\n" + "=" * 60)
    print("TRL SFT SMOKE TEST COMPLETED SUCCESSFULLY!")
    print(f"Final Train Loss: {train_result.training_loss:.4f}")
    print(f"Eval Loss: {eval_result.get('eval_loss', 0.0):.4f}")
    if "eval_schema_reward" in eval_result:
        print(f"Eval Schema Reward: {eval_result['eval_schema_reward']}")
        print(f"Eval Schema Pass Rate: {eval_result.get('eval_schema_pass_rate', 100.0)}%")
    print("=" * 60)

    return {
        "success": True,
        "clean_report": clean_report,
        "training_loss": train_result.training_loss,
        "eval_metrics": eval_result
    }


def train_sft(
    preset_name: str = "kairo-base-490m",
    context_length: int = 4096,
    output_dir: str = "training/checkpoints/trl_sft",
    epochs: int = 3,
    batch_size: int = 2,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 2e-4,
    max_steps: Optional[int] = None
):
    """Full production SFT training run with Hugging Face TRL."""
    print("Starting Kairo SFT training with Hugging Face TRL...")
    clean_report = run_data_cleaning_filter()

    tok_mgr = KairoTokenizerManager()
    tokenizer = tok_mgr.get_tokenizer()

    model, spec = initialize_kairo_model(
        preset_name=preset_name,
        context_length=context_length,
        vocab_size=len(tokenizer)
    )

    data_dir = ROOT_DIR / "training" / "data"
    train_dataset = load_hf_sft_dataset(
        str(data_dir / "train_cleaned.jsonl"),
        tokenizer_manager=tok_mgr,
        max_length=context_length
    )
    val_dataset = load_hf_sft_dataset(
        str(data_dir / "val_cleaned.jsonl"),
        tokenizer_manager=tok_mgr,
        max_length=context_length
    )
    collator = KairoDataCollator(pad_token_id=tokenizer.pad_token_id)

    sft_config = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_steps=100,
        save_total_limit=2,
        max_steps=max_steps if max_steps else -1,
        use_cpu=True,
        report_to="none"
    )

    validator = ToolSpecSchemaValidator()
    eval_callback = SchemaValidationEvalCallback(validator=validator, tokenizer=tokenizer)

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=collator,
        processing_class=tokenizer,
        callbacks=[eval_callback]
    )

    trainer.train()
    final_dir = os.path.join(output_dir, "final_model")
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"SFT model checkpoint saved to: {final_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kairo TRL SFT Runner with Schema Rewards")
    parser.add_argument("--smoke-test", action="store_true", help="Run fast end-to-end smoke test")
    parser.add_argument("--clean-only", action="store_true", help="Run data cleaning filter only")
    parser.add_argument("--preset", default="kairo-base-490m", choices=list(MODEL_CONFIG_PRESETS.keys()))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    if args.clean_only:
        run_data_cleaning_filter()
    elif args.smoke_test or len(sys.argv) == 1:
        run_trl_smoke_test(preset_name=args.preset)
    else:
        train_sft(
            preset_name=args.preset,
            epochs=args.epochs,
            batch_size=args.batch_size,
            max_steps=args.max_steps
        )
