# /models - Model Registry & Local Inference Weights

The `/models` directory stores quantized model weights, checkpoint links, and inference configuration for Kairo's local-first language model fleet. Model definitions, context windows, quantization schemes, and active deployment roles are managed via [`models.yaml`](../models.yaml).

---

## Model Registry Overview (`models.yaml`)

Kairo operates a tiered multi-model architecture combining fast edge triage, high-capacity coding models, and domain-specialized custom Transformers:

| Model ID | Runtime | Quantization | Context Window | Parameter Count | Primary Role | Source / Checkpoint Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`kairo-scale-2b`** | Transformers | FP32 / BF16 | 16,384 tokens | 1.98 Billion | Flagship Custom Model | `training/checkpoints/pretrain/kairo-2b_pretrained.pt` |
| **`kairo-scale-1.2b`** | Transformers | FP32 / BF16 | 8,192 tokens | 1.18 Billion | Intermediate Scaled SLM | `training/checkpoints/pretrain/kairo-1.2b_pretrained.pt` |
| **`kairo-custom-model`** | Transformers | FP32 | 8,192 tokens | 490 Million | Tool Selector & Linter | `training/checkpoints/trl_sft/final_model` |
| **`Qwen3-Coder-30B-A3B`** | `llama.cpp` | Q4_K_M | 32,768 tokens | 30B (3.3B active MoE) | Primary Complex Reasoning | `models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` |
| **`Qwen2.5-0.5B-Instruct`** | `llama.cpp` | Q4_K_M | 4,096 tokens | 490 Million | Low-Latency Fallback | `models/qwen2.5-0.5b-instruct-q4_k_m.gguf` |

---

## Downloading Baseline GGUF Models

For local execution via `llama-server`:

### 1. Ultra-Low Latency Fallback Model (Qwen2.5-0.5B)

```bash
curl -L "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  -o "models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
```

### 2. High-Capacity Primary Baseline (Qwen3-Coder-30B-A3B)

```bash
curl -L "https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF/resolve/main/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" \
  -o "models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
```

---

## Model Center & Failover Router

Model switching and health monitoring are handled dynamically by the Orchestrator without restarting services:

- **Model Center (`orchestrator/model_center.py`)**:
  - Exposes REST routes (`GET /api/models/active`, `POST /api/models/switch`).
  - Monitors real-time VRAM, RAM, CPU utilization, and generation latency.
  - Broadcasts live telemetry over WebSocket to the UI top-bar.
- **Failover Router (`orchestrator/failover_router.py`)**:
  - Implements automated failover across all model pairs.
  - If the active primary model encounters consecutive inference timeouts or schema errors exceeding threshold ($N \ge 3$), the router immediately diverts execution to the designated fallback model.
  - Seamlessly returns to primary when health signals normalize.
