"""
ToolSpec loader and registry manager for YAML tool definitions.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

DEFAULT_TOOLS_DIR = Path(__file__).resolve().parent / "tools"


@dataclass
class ToolSpec:
    id: str
    name: str
    version: str
    description: str
    category: str = "general"
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 5000
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolSpec":
        if "id" not in data or "name" not in data or "version" not in data:
            raise ValueError(f"ToolSpec missing required fields: {data}")
        return cls(
            id=data["id"],
            name=data["name"],
            version=str(data["version"]),
            description=data.get("description", ""),
            category=data.get("category", "general"),
            parameters=data.get("parameters", {}),
            timeout_ms=data.get("timeout_ms", 5000),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "parameters": self.parameters,
            "timeout_ms": self.timeout_ms,
            "metadata": self.metadata,
        }


class ToolRegistry:
    def __init__(self, directory: Optional[Path | str] = None):
        self.directory = Path(directory) if directory else DEFAULT_TOOLS_DIR
        self._tools: Dict[str, ToolSpec] = {}
        self.reload()

    def reload(self) -> None:
        self._tools.clear()
        if not self.directory.exists():
            return

        for yaml_file in self.directory.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        spec = ToolSpec.from_dict(content)
                        self._tools[spec.id] = spec
            except Exception as e:
                print(f"[Registry] Error loading {yaml_file}: {e}")

        for yml_file in self.directory.glob("*.yml"):
            try:
                with open(yml_file, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        spec = ToolSpec.from_dict(content)
                        self._tools[spec.id] = spec
            except Exception as e:
                print(f"[Registry] Error loading {yml_file}: {e}")

    def get(self, tool_id: str) -> Optional[ToolSpec]:
        return self._tools.get(tool_id)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self._tools
