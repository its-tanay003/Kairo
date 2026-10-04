# /models

Directory for storing quantized GGUF weights for local inference via `llama-server`.

## Initial Model (Task 0.3 Plumbing Verification)
- **Model**: `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` (quantized 0.5B, ~468MB)
- **Download Command**:
  ```bash
  curl -L "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" -o "models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
  ```

## Production Model (Task 0.4 Hardening)
- **Target**: `Qwen3-Coder-30B-A3B-Instruct`
- Once the loop is verified, swap the model file path in `orchestrator/llama_manager.py` or specify via `-m models/<target>.gguf`.
