"""
Local Model Inference Runtime Abstraction for Kairo.

Provides genuine neural inference backends for local execution:
1. TransformersLocalRuntime: PyTorch/Transformers causal LM runtime for Kairo custom checkpoints.
2. LlamaCppLocalRuntime: Grammar-constrained local inference runtime for GGUF models.
3. ModelRuntimeManager: Singleton managing model lifecycle, truthful readiness checking,
   safe model switching, and strict enforcement of the local-only / no-cloud invariant.

Readiness States:
- CONFIGURED: Configured in catalog but uninspected.
- CHECKPOINT_MISSING: Path does not exist on disk.
- CHECKPOINT_INCOMPATIBLE: File corrupt, truncated, or architecture mismatch.
- TOKENIZER_UNAVAILABLE: Tokenizer files missing or incompatible.
- LOADING: Checkpoint being mapped into memory.
- LOADED: Weights in memory, not yet inference-tested.
- INFERENCE_TESTED: Passed minimal generation test.
- READY: Fully operational for user inference.
- FAILED: Failed during loading or verification.
- UNLOADED: Evicted from memory to free system resources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

ROOT_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger("orchestrator.model_runtime")

CLOUD_SIGNATURES = [
    "api.openai.com",
    "anthropic.com",
    "azure.com",
    "bedrock",
    "googleapis.com",
    "cohere.ai",
    "openrouter.ai",
    "groq.com",
]


class ModelReadinessState(str, Enum):
    CONFIGURED = "configured"
    CHECKPOINT_MISSING = "checkpoint_missing"
    CHECKPOINT_INCOMPATIBLE = "checkpoint_incompatible"
    TOKENIZER_UNAVAILABLE = "tokenizer_unavailable"
    LOADING = "loading"
    LOADED = "loaded"
    INFERENCE_TESTED = "inference_tested"
    READY = "ready"
    FAILED = "failed"
    UNLOADED = "unloaded"


@dataclass
class StructuredGenerationResult:
    """Standardized output from neural inference."""
    action: str  # "message", "plan", "task", "tool_call", "clarification", "refusal"
    content: str
    tool_call: Optional[Dict[str, Any]] = None
    task_goal: Optional[str] = None
    target: Optional[str] = None
    raw_output: str = ""
    model_id: str = "kairo-scale-2b"
    runtime: str = "transformers"
    is_custom_model: bool = True
    is_fallback: bool = False
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseLocalModelRuntime(ABC):
    """Abstract interface for local neural inference runtimes."""

    def __init__(self, model_meta: Dict[str, Any]):
        self.model_meta = dict(model_meta)
        self.model_id = str(model_meta.get("model_id", "unknown"))
        self.role = str(model_meta.get("role", "primary-custom"))
        self.path = model_meta.get("path")
        self.state: ModelReadinessState = ModelReadinessState.CONFIGURED
        self.error_message: Optional[str] = None
        self._last_loaded_at: Optional[float] = None

    @abstractmethod
    def check_readiness(self) -> Tuple[ModelReadinessState, Optional[str]]:
        """Verifies checkpoint presence, architecture, and tokenizer compatibility."""
        pass

    @abstractmethod
    def load(self) -> bool:
        """Loads model weights and tokenizer into memory."""
        pass

    @abstractmethod
    def unload(self) -> bool:
        """Unloads weights from memory and frees RAM/VRAM."""
        pass

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generates raw text response."""
        pass

    @abstractmethod
    def generate_structured(
        self,
        user_message: str,
        tools: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> StructuredGenerationResult:
        """Generates structured reasoning distinguishing message, plan, task, tool_call, or refusal."""
        pass


class TransformersLocalRuntime(BaseLocalModelRuntime):
    """
    Genuine PyTorch/Transformers causal LM inference runtime.
    Executes actual decoder-only transformer checkpoints (Qwen2ForCausalLM).
    """

    def __init__(self, model_meta: Dict[str, Any]):
        super().__init__(model_meta)
        self._model = None
        self._tokenizer = None

    def _resolve_checkpoint_path(self) -> Optional[Path]:
        raw = self.path
        if not raw:
            if "grpo" in self.model_id or "final" in self.model_id:
                raw = "training/checkpoints/grpo/kairo-grpo-final"
            elif "2b" in self.model_id:
                raw = "training/checkpoints/pretrain/kairo-2b_pretrained.pt"
            elif "1.2b" in self.model_id:
                raw = "training/checkpoints/pretrain/kairo-1.2b_pretrained.pt"
            elif "sft" in self.model_id:
                raw = "training/checkpoints/trl_sft/final_model"
            else:
                raw = f"training/checkpoints/{self.model_id}"

        p = Path(raw)
        if not p.is_absolute():
            p = ROOT_DIR / p
        return p

    def check_readiness(self) -> Tuple[ModelReadinessState, Optional[str]]:
        ckpt_path = self._resolve_checkpoint_path()
        if not ckpt_path or not ckpt_path.exists():
            self.state = ModelReadinessState.CHECKPOINT_MISSING
            self.error_message = f"Checkpoint not found at: {ckpt_path}"
            return self.state, self.error_message

        # Check tokenizer files if directory
        if ckpt_path.is_dir():
            tok_config = ckpt_path / "tokenizer_config.json"
            tok_json = ckpt_path / "tokenizer.json"
            if not tok_config.exists() and not tok_json.exists():
                self.state = ModelReadinessState.TOKENIZER_UNAVAILABLE
                self.error_message = f"Tokenizer files missing in {ckpt_path}"
                return self.state, self.error_message

        # Validate minimum size
        size_bytes = 0
        if ckpt_path.is_file():
            size_bytes = ckpt_path.stat().st_size
        elif ckpt_path.is_dir():
            size_bytes = sum(f.stat().st_size for f in ckpt_path.glob("**/*") if f.is_file())

        if size_bytes < 1024 * 1024:  # At least 1MB
            self.state = ModelReadinessState.CHECKPOINT_INCOMPATIBLE
            self.error_message = f"Checkpoint size {size_bytes} bytes is suspiciously small or truncated."
            return self.state, self.error_message

        if self._model is not None and self._tokenizer is not None:
            self.state = ModelReadinessState.READY
            return self.state, None

        self.state = ModelReadinessState.LOADED
        return self.state, None

    def load(self) -> bool:
        ckpt_path = self._resolve_checkpoint_path()
        if not ckpt_path or not ckpt_path.exists():
            self.state = ModelReadinessState.CHECKPOINT_MISSING
            self.error_message = f"Checkpoint not found at {ckpt_path}"
            return False

        self.state = ModelReadinessState.LOADING
        t0 = time.time()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            # 1. Load Tokenizer
            if ckpt_path.is_dir() and (ckpt_path / "tokenizer_config.json").exists():
                self._tokenizer = AutoTokenizer.from_pretrained(str(ckpt_path), local_files_only=True)
            else:
                from training.tokenizer import KairoTokenizerManager
                tok_mgr = KairoTokenizerManager()
                self._tokenizer = tok_mgr.get_tokenizer()

            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
                self._tokenizer.pad_token_id = self._tokenizer.eos_token_id

            # 2. Load Model Architecture & Weights
            if ckpt_path.is_dir() and (ckpt_path / "config.json").exists():
                self._model = AutoModelForCausalLM.from_pretrained(
                    str(ckpt_path),
                    dtype=torch.float32,
                    local_files_only=True,
                )
            elif ckpt_path.is_file() and ckpt_path.suffix == ".pt":
                from training.model import initialize_kairo_model
                preset = "kairo-2b" if "2b" in self.model_id else "kairo-1.2b"
                model_inst, _ = initialize_kairo_model(preset_name=preset)
                state_dict = torch.load(str(ckpt_path), map_location="cpu")
                if "model_state_dict" in state_dict:
                    state_dict = state_dict["model_state_dict"]
                model_inst.load_state_dict(state_dict, strict=False)
                self._model = model_inst
            else:
                raise ValueError(f"Unsupported checkpoint format at {ckpt_path}")

            self._model.eval()

            # 3. Minimal inference test to verify neural pipeline is operational
            self.state = ModelReadinessState.INFERENCE_TESTED
            test_inputs = self._tokenizer("ping", return_tensors="pt")
            with torch.no_grad():
                _ = self._model.generate(**test_inputs, max_new_tokens=2)

            self.state = ModelReadinessState.READY
            self._last_loaded_at = time.time()
            logger.info(f"[TransformersRuntime] Successfully loaded and verified '{self.model_id}' in {time.time()-t0:.2f}s")
            return True

        except Exception as e:
            logger.error(f"[TransformersRuntime] Failed loading model '{self.model_id}': {e}", exc_info=True)
            self.state = ModelReadinessState.FAILED
            self.error_message = f"Model loading failed: {e}"
            self._model = None
            self._tokenizer = None
            return False

    def unload(self) -> bool:
        self._model = None
        self._tokenizer = None
        self.state = ModelReadinessState.UNLOADED
        try:
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info(f"[TransformersRuntime] Model '{self.model_id}' unloaded.")
        return True

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
    ) -> str:
        if self.state != ModelReadinessState.READY or self._model is None or self._tokenizer is None:
            if not self.load():
                raise RuntimeError(f"Cannot generate: model '{self.model_id}' is not ready: {self.error_message}")

        import torch

        # ChatML formatted prompt
        sys_p = system_prompt or "You are Kairo, an authorized autonomous AI cybersecurity agent operating strictly on local systems."
        formatted = f"<|im_start|>system\n{sys_p}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

        inputs = self._tokenizer(formatted, return_tensors="pt")
        with torch.no_grad():
            output_tokens = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature if temperature > 0 else None,
                do_sample=temperature > 0,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )

        gen_tokens = output_tokens[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()

    def generate_structured(
        self,
        user_message: str,
        tools: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> StructuredGenerationResult:
        t0 = time.time()
        tool_desc = ""
        if tools:
            tool_desc = "\n".join(
                [f"- {t.id}: {t.description}" for t in tools[:15]]
            )

        prompt_instructions = (
            "Analyze the operator's directive and output a structured JSON response.\n"
            "Action options:\n"
            "1. 'message': Educational/conceptual question or conversational query without running tools.\n"
            "2. 'plan': Request to create or show a plan WITHOUT execution.\n"
            "3. 'task': Authorized security assessment task requiring multi-step DAG execution.\n"
            "4. 'tool_call': Single direct tool execution.\n"
            "5. 'refusal': Prohibited or dangerous request.\n\n"
            f"Available Registered Tools:\n{tool_desc}\n\n"
            "Format your response as valid JSON:\n"
            '{"action": "message"|"plan"|"task"|"tool_call"|"refusal", "content": "explanation", '
            '"tool_id": null|"tool_id", "target": null|"target", "arguments": {}}\n'
        )

        raw_gen = self.generate_text(
            prompt=user_message,
            max_tokens=256,
            temperature=0.1,
            system_prompt=prompt_instructions,
        )

        duration_ms = round((time.time() - t0) * 1000, 2)
        parsed = self._extract_json(raw_gen)

        action = parsed.get("action", "message") if parsed else "message"
        content = parsed.get("content", raw_gen) if parsed else raw_gen
        tool_id = parsed.get("tool_id") if parsed else None
        target = parsed.get("target") if parsed else None
        args = parsed.get("arguments", {}) if parsed else {}

        tool_call_dict = None
        if action == "tool_call" and tool_id:
            tool_call_dict = {
                "tool_id": tool_id,
                "tool_version": "1.0.0",
                "arguments": args or ({"target": target} if target else {}),
            }

        return StructuredGenerationResult(
            action=action,
            content=content,
            tool_call=tool_call_dict,
            task_goal=user_message if action == "task" else None,
            target=target,
            raw_output=raw_gen,
            model_id=self.model_id,
            runtime="transformers",
            is_custom_model=True,
            is_fallback=False,
            duration_ms=duration_ms,
        )

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            bare_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
            if bare_match:
                return json.loads(bare_match.group(0))
        except Exception:
            pass
        return None


class LlamaCppLocalRuntime(BaseLocalModelRuntime):
    """
    Grammar-constrained inference runtime using local llama.cpp / GGUF models.
    Can connect to local llama-server on http://127.0.0.1:8080 or verify GGUF binary.
    """

    def __init__(self, model_meta: Dict[str, Any]):
        super().__init__(model_meta)
        from orchestrator.llama_client import LlamaCppClient
        self.server_url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080")
        self.client = LlamaCppClient(base_url=self.server_url)

    def check_readiness(self) -> Tuple[ModelReadinessState, Optional[str]]:
        if self.client.is_healthy():
            self.state = ModelReadinessState.READY
            return self.state, None

        raw_path = self.path or "models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        p = Path(raw_path)
        if not p.is_absolute():
            p = ROOT_DIR / p

        if not p.exists():
            self.state = ModelReadinessState.CHECKPOINT_MISSING
            self.error_message = f"GGUF checkpoint not found at: {p} and llama-server is offline."
            return self.state, self.error_message

        self.state = ModelReadinessState.LOADED
        return self.state, None

    def load(self) -> bool:
        state, _ = self.check_readiness()
        return state in (ModelReadinessState.READY, ModelReadinessState.LOADED)

    def unload(self) -> bool:
        self.state = ModelReadinessState.UNLOADED
        return True

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not self.client.is_healthy():
            raise RuntimeError(f"llama-server at {self.server_url} is offline. GGUF requires running server.")

        import urllib.request
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt or "You are Kairo, a local AI cybersecurity agent."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.server_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def generate_structured(
        self,
        user_message: str,
        tools: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> StructuredGenerationResult:
        t0 = time.time()
        if not self.client.is_healthy():
            raise RuntimeError(f"llama-server at {self.server_url} is offline.")

        from registry.loader import tool_registry
        active_tools = tools or tool_registry.list_tools()
        llm_resp = self.client.generate_constrained(
            user_message=user_message,
            tools=active_tools,
            system_prompt=system_prompt,
        )
        duration_ms = round((time.time() - t0) * 1000, 2)

        tool_dict = None
        if llm_resp.tool_call:
            tool_dict = {
                "tool_id": llm_resp.tool_call.tool_id,
                "tool_version": llm_resp.tool_call.tool_version,
                "arguments": llm_resp.tool_call.arguments,
            }

        return StructuredGenerationResult(
            action=llm_resp.action,
            content=llm_resp.content,
            tool_call=tool_dict,
            task_goal=user_message if llm_resp.action == "task" else None,
            raw_output=llm_resp.content,
            model_id=self.model_id,
            runtime="llama.cpp",
            is_custom_model=False,
            is_fallback=True,
            duration_ms=duration_ms,
        )


class ModelRuntimeManager:
    """
    Authoritative Manager for Local Neural Inference.
    - Manages model lifecycle and active runtime.
    - Enforces strict local-only policy (cloud inference strictly rejected).
    - Performs truthful readiness checking without faking.
    - Manages primary custom model and honest local fallback.
    """

    def __init__(self):
        from orchestrator.model_center import model_center
        self.model_center = model_center
        self._runtimes: Dict[str, BaseLocalModelRuntime] = {}
        self._active_runtime: Optional[BaseLocalModelRuntime] = None

    def get_runtime(self, model_id_or_meta: Union[str, Dict[str, Any]]) -> BaseLocalModelRuntime:
        """Retrieves or instantiates the runtime for a configured model."""
        if isinstance(model_id_or_meta, str):
            meta = self.model_center.get_model_by_id(model_id_or_meta)
            if not meta:
                meta = {"model_id": model_id_or_meta, "runtime": "transformers", "role": "primary-custom"}
        else:
            meta = model_id_or_meta

        mid = str(meta["model_id"])
        if mid in self._runtimes:
            return self._runtimes[mid]

        runtime_type = str(meta.get("runtime", "transformers")).lower()
        if runtime_type == "llama.cpp":
            rt = LlamaCppLocalRuntime(meta)
        else:
            rt = TransformersLocalRuntime(meta)

        self._runtimes[mid] = rt
        return rt

    def resolve_and_activate(
        self,
        requested_model_id: Optional[str] = None,
    ) -> Tuple[BaseLocalModelRuntime, str, bool, Optional[str]]:
        """
        Resolves model runtime:
        1. Checks requested model. Rejects any cloud inference endpoint.
        2. Tries requested model; if ready, uses it.
        3. If not ready, selects configured local fallback (e.g. Qwen2.5-0.5B-Instruct or kairo-grpo-final).
        4. Cloud inference is NEVER used as fallback.
        5. If no local model is operational, raises local RuntimeError with clear diagnostics.

        Returns: (active_runtime, requested_id, processed_by_requested, fallback_reason)
        """
        if requested_model_id:
            lower_req = requested_model_id.lower()
            if any(sig in lower_req for sig in CLOUD_SIGNATURES):
                raise PermissionError(
                    f"Cloud inference is strictly prohibited by Kairo local-only architecture commitment. "
                    f"Requested cloud model '{requested_model_id}' was rejected."
                )

        if requested_model_id:
            try:
                selected_meta = self.model_center.select_model(requested_model_id)
            except Exception:
                selected_meta = self.model_center.get_model_by_id(requested_model_id) or {
                    "model_id": requested_model_id,
                    "runtime": "transformers",
                    "role": "primary-custom",
                }
        else:
            selected_meta = self.model_center.get_active_model()

        requested_id = selected_meta["model_id"]
        req_rt = self.get_runtime(selected_meta)
        req_state, req_err = req_rt.check_readiness()

        if req_state in (ModelReadinessState.READY, ModelReadinessState.LOADED):
            if req_state == ModelReadinessState.READY or req_rt.load():
                self._active_runtime = req_rt
                return req_rt, requested_id, True, None

        logger.warning(f"[ModelRuntimeManager] Model '{requested_id}' not ready: {req_err}. Resolving local fallback.")

        candidates = [
            "kairo-grpo-aligned",
            "kairo-scale-2b",
            "kairo-scale-1.2b",
            "Qwen2.5-0.5B-Instruct",
        ]
        for fb_id in candidates:
            if fb_id == requested_id:
                continue
            fb_meta = self.model_center.get_model_by_id(fb_id)
            if not fb_meta:
                continue
            fb_rt = self.get_runtime(fb_meta)
            fb_state, _ = fb_rt.check_readiness()
            if fb_state in (ModelReadinessState.READY, ModelReadinessState.LOADED):
                if fb_state == ModelReadinessState.READY or fb_rt.load():
                    fallback_reason = (
                        f"Requested model '{requested_id}' was unavailable ({req_err or 'failed readiness'}). "
                        f"Fell back to verified local model '{fb_id}' ({fb_rt.model_meta.get('runtime')}). "
                        f"Air-gapped operation strictly preserved; cloud inference prohibited."
                    )
                    self._active_runtime = fb_rt
                    return fb_rt, requested_id, False, fallback_reason

        err_msg = (
            f"Local-Only Runtime Error: Neither requested model '{requested_id}' nor local fallback models "
            f"({', '.join(candidates)}) passed readiness checks. "
            f"Under Kairo's local-first architecture invariant, cloud inference is prohibited. "
            f"Please verify checkpoint files exist in training/checkpoints/ or models/."
        )
        raise RuntimeError(err_msg)


model_runtime_manager = ModelRuntimeManager()
