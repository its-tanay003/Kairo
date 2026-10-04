"""
Pydantic data models for structured LLM response validation against ToolSpec schema.
"""

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class ToolCallPayload(BaseModel):
    tool_id: str = Field(..., description="Target tool ID from registry")
    tool_version: Optional[str] = Field("1.0.0", description="Semantic version of the tool")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments conforming to ToolSpec")


class LLMResponse(BaseModel):
    action: Literal["message", "tool_call"] = Field(
        ..., description="Either conversational plain text message or a structured tool call"
    )
    content: Optional[str] = Field(
        None, description="Plain text reply when action is 'message', or commentary when 'tool_call'"
    )
    tool_call: Optional[ToolCallPayload] = Field(
        None, description="Structured tool call payload when action is 'tool_call'"
    )

    def is_tool_call(self) -> bool:
        return self.action == "tool_call" and self.tool_call is not None
