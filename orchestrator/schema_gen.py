import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.schema_gen")

ROOT_DIR = Path(__file__).resolve().parent.parent
TOOLSPEC_SCHEMA_PATH = ROOT_DIR / "registry" / "schema" / "toolspec.schema.json"


def load_toolspec_schema(schema_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """
    Loads and returns the authoritative ToolSpec JSON Schema from registry/schema/toolspec.schema.json.
    """
    path = Path(schema_path) if schema_path else TOOLSPEC_SCHEMA_PATH
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read ToolSpec schema from {path}: {e}")
    return {}


def build_recommendation_json_schema() -> Dict[str, Any]:
    """
    Builds a JSON schema defining structured NextStepRecommendation objects:
    - title: string
    - description: string
    - tool_id: string
    - prompt: string
    - priority: "high" | "medium" | "low"
    - rationale: string
    """
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Concise action title for the recommendation"
            },
            "description": {
                "type": "string",
                "description": "Brief explanation of what this next step accomplishes"
            },
            "tool_id": {
                "type": "string",
                "description": "Unique identifier of the recommended tool from tool registry"
            },
            "prompt": {
                "type": "string",
                "description": "Executable natural language prompt ready to send to Kairo"
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Urgency and priority rank of the recommendation"
            },
            "rationale": {
                "type": "string",
                "description": "Technical justification based on current scan findings"
            }
        },
        "required": ["title", "description", "tool_id", "prompt", "priority"]
    }


def build_recommendation_list_json_schema() -> Dict[str, Any]:
    """
    Builds a JSON schema for a list of 3 to 5 NextStepRecommendation items.
    """
    return {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": build_recommendation_json_schema(),
                "description": "List of 3 to 5 proactive next-step recommendations"
            }
        },
        "required": ["recommendations"]
    }


def build_tool_call_json_schema(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds a JSON schema defining:
    - either plain text response
    - or a structured tool call validated against registered ToolSpec ids and properties.
    """
    tool_ids = [t["id"] for t in tools] if tools else ["hello_world", "shell.run.v1"]

    # Incorporate inputs/arguments declared across supplied tools
    base_arg_properties: Dict[str, Any] = {
        "command": {
            "type": "string",
            "description": "The command executable for shell.run.v1 (e.g. python, node, echo)"
        },
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of string arguments for the command"
        },
        "timeout_ms": {
            "type": "integer",
            "description": "Execution timeout in milliseconds"
        },
        "input": {
            "type": "string",
            "description": "Primary argument or query payload"
        },
        "target": {
            "type": "string",
            "description": "Target entity or recipient"
        },
        "url": {
            "type": "string",
            "description": "Target HTTP/HTTPS URL"
        },
        "ports": {
            "type": "string",
            "description": "Port specification (e.g. '80,443' or '1-1000')"
        },
        "wordlist": {
            "type": "string",
            "description": "Path to wordlist file"
        }
    }

    # Dynamically merge parameter properties from tool specifications
    if tools:
        for t in tools:
            inputs = t.get("inputs") or t.get("parameters") or {}
            props = inputs.get("properties") if isinstance(inputs, dict) else None
            if isinstance(props, dict):
                for k, v in props.items():
                    if k not in base_arg_properties and isinstance(v, dict):
                        base_arg_properties[k] = v

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
                        "properties": base_arg_properties,
                        "additionalProperties": True
                    }
                },
                "required": ["tool_id"]
            }
        },
        "required": ["action"]
    }
    return schema
