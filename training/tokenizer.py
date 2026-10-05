"""
Kairo Tokenizer Module (Track B).
Manages tokenizer selection and conversation formatting for code/shell/JSON tool-calling SFT.
"""

from typing import Dict, Any, List, Optional
import os
import json
from transformers import AutoTokenizer, PreTrainedTokenizerFast

DEFAULT_TOKENIZER_ID = "Qwen/Qwen2.5-Coder-0.5B"


class KairoTokenizerManager:
    """
    Manages loading and applying the open tokenizer with strong code, shell, and JSON coverage.
    Uses Qwen2.5-Coder tokenizer by default (BPE with byte fallback, vocabulary ~151,665,
    exceptional handling of bash CLI flags, JSON syntax, indentation, and role framing).
    """

    def __init__(self, tokenizer_name_or_path: str = DEFAULT_TOKENIZER_ID):
        self.tokenizer_id = tokenizer_name_or_path
        self._tokenizer: Optional[PreTrainedTokenizerFast] = None

    def get_tokenizer(self) -> PreTrainedTokenizerFast:
        """Loads and returns the tokenizer with appropriate padding/special tokens configured."""
        if self._tokenizer is None:
            # Load tokenizer (will use local cache if previously fetched)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.tokenizer_id,
                trust_remote_code=True,
                use_fast=True
            )
            # Ensure pad token exists (pad with eos if not explicitly set)
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
                self._tokenizer.pad_token_id = self._tokenizer.eos_token_id
            
        return self._tokenizer

    @property
    def vocab_size(self) -> int:
        tok = self.get_tokenizer()
        return len(tok)

    def format_sft_conversation(self, example: Dict[str, Any]) -> str:
        """
        Formats a Kairo SFT conversation record into a standardized training sequence.
        Uses ChatML format (<|im_start|>role ... <|im_end|>) supported natively by Qwen.
        """
        conversation = example.get("conversation", [])
        if not conversation:
            # Fallback format if conversation turns not explicitly provided
            return self._format_raw_5tuple(example)

        formatted_turns = []
        for turn in conversation:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            
            # Format tool calls if present in assistant turns
            if role == "assistant" and "tool_calls" in turn and turn["tool_calls"]:
                tool_calls = turn["tool_calls"]
                call_strs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    call_strs.append(f"<tool_call>\n{json.dumps({'name': fn.get('name'), 'arguments': json.loads(fn.get('arguments', '{}'))}, indent=2)}\n</tool_call>")
                if call_strs:
                    content = (content + "\n" + "\n".join(call_strs)).strip()

            formatted_turns.append(f"<|im_start|>{role}\n{content}<|im_end|>")

        return "\n".join(formatted_turns) + "\n"

    def _format_raw_5tuple(self, example: Dict[str, Any]) -> str:
        """Formats the raw {user_goal, task_graph, tool_call, observation, next_step} 5-tuple."""
        system_prompt = (
            "<|im_start|>system\n"
            "You are Kairo Agent Core, an autonomous security planner and tool execution engine bounded by a strict Scope Contract.\n"
            "Your role: Given a security goal and task graph context, select the optimal tool, generate schema-valid arguments, "
            "execute within scope boundaries, interpret observations, and autonomously recover from failures.<|im_end|>\n"
        )
        user_turn = (
            f"<|im_start|>user\n"
            f"Goal: {example.get('user_goal', '')}\n"
            f"Task Graph Context: {json.dumps(example.get('task_graph', {}))}<|im_end|>\n"
        )
        assistant_turn = (
            f"<|im_start|>assistant\n"
            f"<tool_call>\n{json.dumps(example.get('tool_call', {}), indent=2)}\n</tool_call><|im_end|>\n"
        )
        tool_turn = (
            f"<|im_start|>tool\n"
            f"{example.get('observation', '')}<|im_end|>\n"
        )
        final_assistant = (
            f"<|im_start|>assistant\n"
            f"Proceeding to next step: {example.get('next_step', 'complete')}<|im_end|>\n"
        )
        return system_prompt + user_turn + assistant_turn + tool_turn + final_assistant

    def tokenize_example(
        self,
        example: Dict[str, Any],
        max_length: int = 8192,
        mask_prompt_labels: bool = True
    ) -> Dict[str, List[int]]:
        """
        Tokenizes an SFT example and prepares input_ids, attention_mask, and labels.
        If mask_prompt_labels is True, loss is only computed on assistant responses.
        """
        tok = self.get_tokenizer()
        conversation = example.get("conversation", [])
        
        if not mask_prompt_labels or not conversation:
            full_text = self.format_sft_conversation(example)
            enc = tok(full_text, max_length=max_length, truncation=True, return_tensors=None)
            enc["labels"] = list(enc["input_ids"])
            return enc

        # Prompt-masked tokenization: label is -100 for system/user/tool turns,
        # and actual token ids for assistant turns.
        input_ids: List[int] = []
        labels: List[int] = []
        
        for turn in conversation:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "assistant" and "tool_calls" in turn and turn["tool_calls"]:
                tool_calls = turn["tool_calls"]
                call_strs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    call_strs.append(f"<tool_call>\n{json.dumps({'name': fn.get('name'), 'arguments': json.loads(fn.get('arguments', '{}'))}, indent=2)}\n</tool_call>")
                if call_strs:
                    content = (content + "\n" + "\n".join(call_strs)).strip()

            turn_text = f"<|im_start|>{role}\n{content}<|im_end|>\n"
            turn_ids = tok.encode(turn_text, add_special_tokens=False)

            input_ids.extend(turn_ids)
            if role == "assistant":
                # Compute loss on assistant's response tokens
                # We mask the header "<|im_start|>assistant\n" so loss is on content only
                header_ids = tok.encode("<|im_start|>assistant\n", add_special_tokens=False)
                num_header = len(header_ids)
                turn_labels = [-100] * min(num_header, len(turn_ids)) + turn_ids[num_header:]
                labels.extend(turn_labels)
            else:
                # Mask out system, user, tool observation turns from loss calculation
                labels.extend([-100] * len(turn_ids))

        # Truncate if exceeding max_length
        if len(input_ids) > max_length:
            input_ids = input_ids[:max_length]
            labels = labels[:max_length]

        attention_mask = [1] * len(input_ids)
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels
        }
