# /models - Model Registry & Local Inference Weights

The `/models` directory stores quantized model weights, checkpoint links, and inference configuration for Kairo's local-first language model fleet. Model definitions, context windows, quantization schemes, and active deployment roles are managed via [`models.yaml`](../models.yaml).

---

## Model Registry Overview (`models.yaml`)

Kairo operates a tiered multi-model architecture combining fast edge triage, high-capacity coding models, and domain-specialized custom Transformers:

| Model ID | Runtime | Quantization | Context Window | Parameter Count | Primary Role | Source / Checkpoint Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`kairo-grpo-final`** | Transformers (PyTorch) | Safetensors FP32/BF16 | 16,384 tokens | 1.54 GB weights | Primary Custom Cybersecurity Model | `training/checkpoints/grpo/kairo-grpo-final` |
| **`kairo-scale-2b`** | Transformers | FP32 / BF16 | 16,384 tokens | 1.98 Billion | Flagship Pretrained Base | `training/checkpoints/pretrain/kairo-2b_pretrained.pt` |
| **`kairo-scale-1.2b`** | Transformers | FP32 / BF16 | 8,192 tokens | 1.18 Billion | Intermediate Scaled SLM | `training/checkpoints/pretrain/kairo-1.2b_pretrained.pt` |
| **`kairo-custom-model`** | Transformers | FP32 | 8,192 tokens | 490 Million | Tool Selector & Linter | `training/checkpoints/trl_sft/final_model` |
| **`Qwen2.5-0.5B-Instruct`** | `llama.cpp` (GGUF) | Q4_K_M | 4,096 tokens | 491 MB GGUF | Local High-Speed Fallback | `models/qwen2.5-0.5b-instruct-q4_k_m.gguf` |

---

## Canonical Model Runtime Architecture (`orchestrator/model_runtime.py`)

KAIRO enforces a strict **Local-Only Inference Invariant**: all model inference runs on local hardware. Cloud-based LLM APIs (such as OpenAI, Anthropic, or Bedrock) are strictly prohibited and never used as fallbacks.

The `ModelRuntimeManager` oversees the complete model lifecycle:

1. **`TransformersLocalRuntime`**:
   - Manages PyTorch-native Causal Language Models (e.g. `training/checkpoints/grpo/kairo-grpo-final`).
   - Loads model weights and tokenizers locally with CPU/CUDA device mapping.
   - Evaluates genuine readiness: validates checkpoint existence, architecture compatibility, tokenizer generation, and structured JSON output.
2. **`LlamaCppLocalRuntime`**:
   - Manages local GGUF models via `llama-server.exe` on port `8080`.
   - Health checks endpoint readiness with live generation probes before declaring `READY`.
3. **Truthful Execution Provenance**:
   - Every inference response records the exact model name, runtime backend, generation latency, and token count.
   - Rule-based emergency fallbacks are clearly labeled as `rule_fallback` in audit logs—never masquerading as neural inference.

---

## Local Inference Setup

### 1. Primary Custom Model (PyTorch Safetensors)

The primary model is pre-packaged at `training/checkpoints/grpo/kairo-grpo-final`. The orchestrator loads it automatically when `prefer_llm` is enabled.

### 2. Local Fallback Server (`llama.cpp`)

To launch the local GGUF server for high-speed fallback inference:

```bash
llama-server.exe -m models/qwen2.5-0.5b-instruct-q4_k_m.gguf --port 8080 --ctx-size 4096
```

---

## Model Center & Failover Router

Model switching and health monitoring are handled dynamically by the Orchestrator without restarting services:

- **Model Center (`orchestrator/model_center.py`)**:
  - Exposes REST routes (`GET /api/models/active`, `POST /api/models/switch`).
  - Monitors real-time VRAM, RAM, CPU utilization, and generation latency.
  - Broadcasts live telemetry over WebSocket to the UI top-bar.
- **Failover Router (`orchestrator/failover_router.py`)**:
  - Implements automated failover between verified local models.
  - If the primary model encounters consecutive inference timeouts or schema errors exceeding threshold ($N \ge 3$), execution diverts to the verified local GGUF fallback.
  - Seamlessly returns to primary when health signals normalize.
  - Never falls back to cloud providers.
