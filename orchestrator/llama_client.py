"""
Llama.cpp client supporting grammar/JSON-schema constrained inference.
Enforces structural impossibility of malformed tool calls via llama.cpp grammar generation.
"""

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from orchestrator.models import LLMResponse, ToolCallPayload
from orchestrator.schema_gen import build_tool_call_json_schema
from registry.loader import ToolSpec

logger = logging.getLogger("orchestrator.llama_client")


class LlamaCppClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080")).rstrip("/")

    def is_healthy(self) -> bool:
        """Check if llama.cpp server is reachable and ready."""
        try:
            url = f"{self.base_url}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate_constrained(
        self,
        user_message: str,
        tools: List[ToolSpec],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """
        Sends user message to llama.cpp with grammar/JSON-schema constraint.
        Guarantees that output strictly adheres to either plain text or a valid ToolSpec tool call.
        """
        tools_dict = [t.to_dict() for t in tools]
        schema = build_tool_call_json_schema(tools_dict)

        tool_descriptions = "\n".join(
            [f"- {t.id} (v{t.version}): {t.description}" for t in tools]
        )

        sys_content = system_prompt or (
            "You are an AI orchestrator assistant. You have two action options:\n"
            "1. 'message': Reply with plain text in 'content' if the user asks a general question, chat, or explanation.\n"
            "2. 'tool_call': If the user explicitly asks to run, execute, ping, or invoke a tool, choose 'tool_call' with 'tool_id' and 'arguments'.\n\n"
            f"Available Registered Tools:\n{tool_descriptions}\n\n"
            "Examples:\n"
            "User: Hello, how are you today?\n"
            "Response: {\"action\": \"message\", \"content\": \"Hello! I am ready to assist you.\"}\n\n"
            "User: Execute hello_world tool for Tanay\n"
            "Response: {\"action\": \"tool_call\", \"tool_call\": {\"tool_id\": \"hello_world\", \"tool_version\": \"1.0.0\", \"arguments\": {\"input\": \"Tanay\"}}}\n\n"
            "User: Run diagnostic system ping\n"
            "Response: {\"action\": \"tool_call\", \"tool_call\": {\"tool_id\": \"system_ping\", \"tool_version\": \"1.0.0\", \"arguments\": {}}}\n"
        )

        messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": user_message},
        ]

        payload = {
            "messages": messages,
            "temperature": temperature,
            "response_format": {
                "type": "json_object",
                "schema": schema,
            },
        }

        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                raw_body = resp.read().decode("utf-8")
                res = json.loads(raw_body)
                content_str = res["choices"][0]["message"]["content"]
                
                # Parse structured output guaranteed by llama.cpp grammar
                parsed = json.loads(content_str)
                return LLMResponse.model_validate(parsed)
        except urllib.error.URLError as e:
            logger.error(f"Llama.cpp server communication error: {e}")
            raise RuntimeError(f"Cannot reach llama.cpp server at {self.base_url}: {e}")
        except Exception as e:
            logger.error(f"Error parsing constrained LLM response: {e}")
            raise
