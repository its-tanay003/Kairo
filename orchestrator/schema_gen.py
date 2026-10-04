"""
Generates minimal ToolSpec-shaped JSON schemas for llama.cpp grammar-constrained generation.
"""

from typing import Any, Dict, List
import json


def build_tool_call_json_schema(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds a JSON schema defining:
    - either plain text response
    - or a structured tool call validated against registered ToolSpec ids and properties.
    """
    tool_ids = [t["id"] for t in tools] if tools else ["hello_world"]

    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["message", "tool_call"],
                "description": "Choose 'message' for conversational response or 'tool_call' to execute a tool"
            },
            "content": {
                "type": "string",
                "description": "The textual answer to the user when action is 'message'"
            },
            "tool_call": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": tool_ids,
                        "description": "Identifier of the tool to execute"
                    },
                    "tool_version": {
                        "type": "string",
                        "description": "Version of the tool (e.g. 1.0.0)"
                    },
                    "arguments": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": "Primary argument or query payload"
                            },
                            "target": {
                                "type": "string",
                                "description": "Target entity or recipient"
                            }
                        }
                    }
                },
                "required": ["tool_id"]
            }
        },
        "required": ["action"]
    }
    return schema
