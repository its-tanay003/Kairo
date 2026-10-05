"""
PyTorch SFT Dataset and Data Collator for Kairo Track B Training.
Loads train.jsonl and val.jsonl, tokenizes conversations with prompt masking,
and dynamically collates batches for PyTorch/Hugging Face Trainer.
"""

from typing import Dict, Any, List, Optional
import json
import os
import torch
from torch.utils.data import Dataset
from training.tokenizer import KairoTokenizerManager


class KairoSFTDataset(Dataset):
    """
    PyTorch Dataset loading Kairo SFT conversations from JSONL.
    Each item contains {user_goal, task_graph, tool_call, observation, next_step}
    and multi-turn conversation steps.
    """

    def __init__(
        self,
        jsonl_path: str,
        tokenizer_manager: Optional[KairoTokenizerManager] = None,
        max_length: int = 4096,
        mask_prompt_labels: bool = True,
        max_samples: Optional[int] = None
    ):
        self.jsonl_path = jsonl_path
        self.tokenizer_mgr = tokenizer_manager or KairoTokenizerManager()
        self.max_length = max_length
        self.mask_prompt_labels = mask_prompt_labels
        self.records: List[Dict[str, Any]] = []

        if not os.path.exists(jsonl_path):
            raise FileNotFoundError(f"Dataset file not found: {jsonl_path}")

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.records.append(json.loads(line))
                    if max_samples and len(self.records) >= max_samples:
                        break
                except json.JSONDecodeError:
                    continue

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        record = self.records[idx]
        tokenized = self.tokenizer_mgr.tokenize_example(
            record,
            max_length=self.max_length,
            mask_prompt_labels=self.mask_prompt_labels
        )
        return {
            "input_ids": tokenized["input_ids"],
            "attention_mask": tokenized["attention_mask"],
            "labels": tokenized["labels"],
            "id": record.get("id", f"sample_{idx}"),
            "is_recovery": record.get("metadata", {}).get("is_recovery", False)
        }


class KairoDataCollator:
    """
    Collate function that dynamically pads input_ids, attention_mask, and labels
    to the maximum length within each batch.
    """

    def __init__(self, pad_token_id: int, pad_label_id: int = -100):
        self.pad_token_id = pad_token_id
        self.pad_label_id = pad_label_id

    def __call__(self, batch: List[Dict[str, Any]]) -> Dict[str, torch.Tensor]:
        max_len = max(len(item["input_ids"]) for item in batch)

        batch_input_ids = []
        batch_attention_mask = []
        batch_labels = []

        for item in batch:
            input_ids = item["input_ids"]
            attention_mask = item.get("attention_mask")
            if attention_mask is None:
                attention_mask = [1] * len(input_ids)
            labels = item.get("labels")
            if labels is None:
                labels = list(input_ids)

            pad_len = max_len - len(input_ids)
            padded_input_ids = input_ids + [self.pad_token_id] * pad_len
            padded_attention_mask = attention_mask + [0] * pad_len
            padded_labels = labels + [self.pad_label_id] * pad_len

            batch_input_ids.append(padded_input_ids)
            batch_attention_mask.append(padded_attention_mask)
            batch_labels.append(padded_labels)

        return {
            "input_ids": torch.tensor(batch_input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(batch_attention_mask, dtype=torch.long),
            "labels": torch.tensor(batch_labels, dtype=torch.long)
        }


def load_hf_sft_dataset(
    jsonl_path: str,
    tokenizer_manager: Optional[KairoTokenizerManager] = None,
    max_length: int = 4096,
    mask_prompt_labels: bool = True,
    max_samples: Optional[int] = None
):
    """
    Loads Kairo SFT dataset as a Hugging Face Dataset instance (for TRL SFTTrainer).
    """
    from datasets import Dataset

    raw_ds = KairoSFTDataset(
        jsonl_path=jsonl_path,
        tokenizer_manager=tokenizer_manager,
        max_length=max_length,
        mask_prompt_labels=mask_prompt_labels,
        max_samples=max_samples
    )
    records_list = [raw_ds[i] for i in range(len(raw_ds))]
    hf_ds = Dataset.from_list(records_list)
    # Store raw records for schema validation callbacks
    hf_ds.raw_records = raw_ds.records
    return hf_ds
