# /training - Kairo LLM Pretraining, Alignment & Fine-Tuning Engine

The `/training` subsystem implements the specialized machine learning lifecycle for Kairo's domain-specific Small Language Models (SLMs). Ranging from **380M parameters** up to **2.0B parameters**, these models are engineered specifically for deterministic tool selection, schema-compliant JSON/XML argument generation, self-healing error recovery, and strict CIDR scope boundary adherence.

---

## Subsystem Architecture & Data Flow

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Raw Domain Corpus & Telemetry                   │
│  - /events/events.db operational logs (20-field SQLite schema)         │
│  - /registry ToolSpecs (16-field YAML blueprints)                      │
│  - Domain security corpus (manpages, CVE reports, penetration logs)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Harvesting & Synthesis                          │
│  - harvest.py: Extracts golden trajectories & recovery chains          │
│  - synthesizer.py: Generates synthetic task graphs & corner cases      │
│  - dataset_expansion.py: Expands to 10k+ multi-turn dialogues         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Stage 1: Domain Pretraining (pretrain.py)            │
│  - Custom Decoder-Only Transformer (RMSNorm + RoPE + GQA + SwiGLU)     │
│  - Byte-level BPE Tokenizer with specialized security & tool tokens    │
│  - Checkpoints: kairo-380m, kairo-700m, kairo-1.2b, kairo-2b           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│              Stage 2: Supervised Fine-Tuning (trl_sft.py)              │
│  - Hugging Face TRL SFTTrainer with schema-cleaning verification       │
│  - Multi-turn tool calling, XML thought tagging, JSON schemas          │
│  - Output: training/checkpoints/trl_sft/final_model                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Stage 3: Direct Preference Optimization (dpo.py)           │
│  - Pairwise alignment: Chosen (safe, minimal) vs Rejected (overscoped) │
│  - Prevents CIDR boundary expansion and destructive command execution │
│  - Output: training/checkpoints/dpo/final_model                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Stage 4: Group Relative Policy Optimization (grpo.py)      │
│  - Verifiable mathematical reward signals (schema_reward.py):          │
│    • Schema Validity Reward (+1.0 valid JSON, -1.0 malformed)          │
│    • Tool Registry Membership (+1.0 known tool, -1.5 hallucinated)     │
│    • Scope Boundary Compliance (+1.0 within CIDR, -3.0 violation)      │
│    • Task Goal Completion (+2.0 target reached, -0.5 failed)           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## File & Module Index

| File | Purpose & Responsibilities |
| :--- | :--- |
| [`model.py`](model.py) | Custom PyTorch Decoder-Only Transformer architecture. Implements RMSNorm, Rotary Positional Embeddings (RoPE), Grouped Query Attention (GQA), and SwiGLU activation. |
| [`tokenizer.py`](tokenizer.py) | Open Byte-level BPE tokenizer supporting specialized tool delimiters (`<|tool_call|>`, `</|tool_call|>`, `<|thought|>`, `<|observation|>`). |
| [`pretrain.py`](pretrain.py) | Autoregressive domain pre-training engine with cosine learning rate schedule, gradient accumulation, and loss checkpointing. |
| [`trl_sft.py`](trl_sft.py) | Supervised Fine-Tuning pipeline using Hugging Face TRL `SFTTrainer` and dataset collator with automated schema validation. |
| [`dpo.py`](dpo.py) | Direct Preference Optimization loop aligning models against negative preferences (e.g., unauthorized scanning, syntax errors). |
| [`grpo.py`](grpo.py) | Group Relative Policy Optimization engine sampling multiple generation candidates and weighting policy updates by verifiable reward scores. |
| [`schema_reward.py`](schema_reward.py) | Rule-based verifiable reward computation scoring schema validity, argument types, CIDR containment, and task success. |
| [`harvest.py`](harvest.py) | Automated operational telemetry extractor mining past `/events/events.db` sessions into high-quality training pairs. |
| [`synthesizer.py`](synthesizer.py) | Synthetic task and execution trajectory generator creating diverse multi-step penetration scenarios. |
| [`dataset_expansion.py`](dataset_expansion.py) | Systematic dataset expansion generating diverse adversarial and defensive scenarios across 28+ registered tools. |
| [`preferences.py`](preferences.py) | DPO preference dataset builder creating `(prompt, chosen, rejected)` triplets from execution metrics. |
| [`dataset.py`](dataset.py) | PyTorch Dataset and DataLoader abstractions with token length masking and pad tokens. |
| [`pipeline.py`](pipeline.py) | Unified end-to-end orchestration runner executing sequential Pretrain -> SFT -> DPO -> GRPO workflows. |

---

## Model Architecture & Sizing Presets

Defined in [`model.py`](model.py) and configured via [`models.yaml`](../models.yaml):

| Parameter Tier | Target Model ID | Hidden Dim | Layers | Heads | KV Heads | Context Window | Parameter Count | Primary Deployment Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 0** | `Kairo-Base-380M` | 1024 | 16 | 16 | 4 | 4,096 | 380 Million | CPU edge triage, low-power appliances |
| **Tier A** | `kairo-custom-model` | 1280 | 20 | 20 | 4 | 8,192 | 490 Million | Real-time tool selection & argument linting |
| **Tier B** | `kairo-scale-700m` | 1536 | 24 | 24 | 6 | 8,192 | 720 Million | Full DAG decomposition and reasoning |
| **Tier B.1** | `kairo-scale-1.2b` | 2048 | 24 | 32 | 8 | 8,192 | 1.18 Billion | Intermediate autonomous penetration agent |
| **Tier C** | `kairo-scale-2b` | 2560 | 32 | 32 | 8 | 16,384 | 1.98 Billion | Flagship autonomous cyber defense model |

---

## Operational Workflows

### 1. Generating Training Data from Telemetry
```bash
# Harvest real execution traces and successful recovery loops from SQLite
python -m training.harvest --db events/events.db --output training/data/harvested_sft.jsonl

# Expand dataset with synthetic boundary and corner cases
python -m training.dataset_expansion --count 5000 --output training/data/train_cleaned.jsonl
```

### 2. Running Supervised Fine-Tuning (SFT)
```bash
python -m training.trl_sft \
  --train_file training/data/train_cleaned.jsonl \
  --val_file training/data/val_cleaned.jsonl \
  --output_dir training/checkpoints/trl_sft/v2 \
  --epochs 3 \
  --batch_size 4 \
  --lr 2e-5
```

### 3. Running Preference Tuning (DPO)
```bash
python -m training.dpo \
  --model_path training/checkpoints/trl_sft/v2 \
  --preference_file training/data/preferences.jsonl \
  --output_dir training/checkpoints/dpo/v2 \
  --beta 0.1
```

### 4. Running Reinforcement Learning (GRPO)
```bash
python -m training.grpo \
  --model_path training/checkpoints/dpo/v2 \
  --reward_fn schema_validity,task_completion \
  --num_generations 4 \
  --output_dir training/checkpoints/grpo/v2
```

---

## Verifiable Reward System (`schema_reward.py`)

GRPO training relies on strict mathematical rewards rather than subjective human feedback:

$$R_{\text{total}} = w_1 R_{\text{schema}} + w_2 R_{\text{tool\_exist}} + w_3 R_{\text{scope}} + w_4 R_{\text{task}}$$

- $R_{\text{schema}} \in \{-1.0, +1.0\}$: Verifies output parses as valid JSON and conforms to ToolSpec schema inputs.
- $R_{\text{tool\_exist}} \in \{-1.5, +1.0\}$: Verifies called `tool_id` exists in `registry/tools/`.
- $R_{\text{scope}} \in \{-3.0, +1.0\}$: Verifies target parameter strictly resides within active CIDR scope.
- $R_{\text{task}} \in \{-0.5, +2.0\}$: Verifies desired objective (e.g., port discovery, vulnerability validation) was accomplished.
