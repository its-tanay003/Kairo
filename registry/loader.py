"""
ToolSpec loader and registry manager for YAML tool definitions.
Enforces the exact 16-field ToolSpec blueprint schema on startup via JSON Schema validation:
(id, binary, category, capabilities, inputs, outputs, side_effects,
privilege, gui, parser, prerequisites, docs, success_signals,
failure_signals, rollback, version_compatibility).

Malformed specs are rejected at load time, not execution time.
"""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
import jsonschema

logger = logging.getLogger("registry.loader")

REGISTRY_ROOT = Path(__file__).resolve().parent
DEFAULT_TOOLS_DIR = REGISTRY_ROOT / "tools"
DEFAULT_SCHEMA_PATH = REGISTRY_ROOT / "schema" / "toolspec.schema.json"


class ToolSpecValidationError(Exception):
    """Raised when a ToolSpec fails validation against the ToolSpec JSON Schema at load time."""
    def __init__(self, message: str, file_path: Optional[Path | str] = None, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.file_path = file_path
        self.errors = errors or []


@dataclass
class ToolSpec:
    # 16 Core Blueprint Fields
    id: str
    binary: str
    category: str
    capabilities: List[str]
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    side_effects: List[str]
    privilege: str
    gui: Union[bool, Dict[str, Any]]
    parser: Union[str, Dict[str, Any]]
    prerequisites: List[str]
    docs: Union[str, Dict[str, Any]]
    success_signals: Dict[str, Any]
    failure_signals: Dict[str, Any]
    rollback: Union[str, Dict[str, Any]]
    version_compatibility: Union[str, Dict[str, Any]]

    # Convenience / Backward-Compatibility Fields
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    timeout_ms: int = 5000
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolSpec":
        """Instantiates a ToolSpec from a validated dictionary."""
        # Derive name/version/description if not explicitly present
        name = data.get("name") or data.get("id", "unnamed_tool")
        version = str(data.get("version", "1.0.0"))
        description = data.get("description")
        if not description:
            if isinstance(data.get("docs"), dict):
                description = data["docs"].get("summary", "")
            elif isinstance(data.get("docs"), str):
                description = data["docs"]
            else:
                description = ""

        # Align parameters with inputs for backward-compatibility with agent loop
        inputs = data.get("inputs") or {}
        parameters = data.get("parameters") or inputs

        return cls(
            id=str(data["id"]),
            binary=str(data["binary"]),
            category=str(data["category"]),
            capabilities=list(data.get("capabilities", [])),
            inputs=inputs,
            outputs=data.get("outputs") or {},
            side_effects=list(data.get("side_effects", [])),
            privilege=str(data.get("privilege", "user")),
            gui=data.get("gui", False),
            parser=data.get("parser", "raw"),
            prerequisites=list(data.get("prerequisites", [])),
            docs=data.get("docs", {}),
            success_signals=data.get("success_signals") or {},
            failure_signals=data.get("failure_signals") or {},
            rollback=data.get("rollback") or {},
            version_compatibility=data.get("version_compatibility") or {},
            name=name,
            version=version,
            description=description,
            timeout_ms=int(data.get("timeout_ms", 5000)),
            parameters=parameters,
            metadata=data.get("metadata") or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ToolSpec to dictionary including all blueprint fields."""
        return {
            "id": self.id,
            "binary": self.binary,
            "category": self.category,
            "capabilities": self.capabilities,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "side_effects": self.side_effects,
            "privilege": self.privilege,
            "gui": self.gui,
            "parser": self.parser,
            "prerequisites": self.prerequisites,
            "docs": self.docs,
            "success_signals": self.success_signals,
            "failure_signals": self.failure_signals,
            "rollback": self.rollback,
            "version_compatibility": self.version_compatibility,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "timeout_ms": self.timeout_ms,
            "parameters": self.parameters,
            "metadata": self.metadata,
        }


class ToolRegistry:
    """
    Registry that validates every ToolSpec YAML file against the formal JSON Schema
    on startup and rejects malformed specs at load time.
    """

    def __init__(
        self,
        directory: Optional[Path | str] = None,
        schema_path: Optional[Path | str] = None,
        strict: bool = True,
    ):
        self.directory = Path(directory) if directory else DEFAULT_TOOLS_DIR
        self.schema_path = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
        self.strict = strict
        self._tools: Dict[str, ToolSpec] = {}

        # Load and prepare JSON Schema validator
        self._validator = self._load_schema_validator()

        # Load all specs on startup
        self.reload()

    def _load_schema_validator(self) -> jsonschema.Draft7Validator:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"ToolSpec schema not found at {self.schema_path}")
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema_json = json.load(f)
        return jsonschema.Draft7Validator(schema_json)

    def validate_spec_data(self, data: Dict[str, Any]) -> List[str]:
        """Validates a parsed ToolSpec dictionary against the schema and returns list of error messages."""
        errors = []
        for error in self._validator.iter_errors(data):
            path_str = " -> ".join([str(p) for p in error.path]) if error.path else "root"
            errors.append(f"[{path_str}] {error.message}")
        return errors

    def reload(self) -> None:
        """
        Loads and validates every YAML spec file in the directory.
        Rejects malformed specs immediately on startup.
        """
        self._tools.clear()
        if not self.directory.exists():
            logger.warning(f"[ToolRegistry] Tools directory does not exist: {self.directory}")
            return

        yaml_files = sorted(list(self.directory.glob("*.yaml")) + list(self.directory.glob("*.yml")))

        for yaml_file in yaml_files:
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
            except Exception as e:
                err_msg = f"Failed to parse YAML syntax in {yaml_file.name}: {e}"
                logger.error(f"[ToolRegistry] {err_msg}")
                if self.strict:
                    raise ToolSpecValidationError(err_msg, file_path=yaml_file)
                continue

            if not isinstance(content, dict):
                err_msg = f"YAML root in {yaml_file.name} must be a dictionary, got {type(content).__name__}"
                logger.error(f"[ToolRegistry] {err_msg}")
                if self.strict:
                    raise ToolSpecValidationError(err_msg, file_path=yaml_file)
                continue

            # Validate against JSON Schema
            validation_errors = self.validate_spec_data(content)
            if validation_errors:
                err_details = "; ".join(validation_errors)
                err_msg = (
                    f"ToolSpec load-time schema validation rejected '{yaml_file.name}': {err_details}"
                )
                logger.error(f"[ToolRegistry] {err_msg}")
                if self.strict:
                    raise ToolSpecValidationError(err_msg, file_path=yaml_file, errors=validation_errors)
                continue

            # Instantiate validated ToolSpec
            try:
                spec = ToolSpec.from_dict(content)
                self._tools[spec.id] = spec
                logger.debug(f"[ToolRegistry] Loaded and validated spec '{spec.id}' from {yaml_file.name}")
            except Exception as e:
                err_msg = f"Failed instantiating ToolSpec from {yaml_file.name}: {e}"
                logger.error(f"[ToolRegistry] {err_msg}")
                if self.strict:
                    raise ToolSpecValidationError(err_msg, file_path=yaml_file)

    def get(self, tool_id: str) -> Optional[ToolSpec]:
        """Returns the ToolSpec by id if loaded, else None."""
        return self._tools.get(tool_id)

    def list_tools(self) -> List[ToolSpec]:
        """Returns all loaded, schema-validated ToolSpecs."""
        return list(self._tools.values())

    def has_tool(self, tool_id: str) -> bool:
        """Checks if a tool id is loaded and registered."""
        return tool_id in self._tools

    def count(self) -> int:
        """Returns the number of loaded tools."""
        return len(self._tools)
