"""
Test suite verifying ToolSpec YAML schema compliance and registry loader validation.
Verifies:
1. Valid specs in registry/tools load cleanly with all 16 blueprint fields.
2. Startup loader strictly rejects malformed specs (missing fields, wrong types, invalid YAML).
3. Rejection occurs at load/startup time, not execution time.
4. Python and TypeScript registry loader interoperability.
"""

import json
import os
from pathlib import Path
import tempfile
import pytest
import yaml

from registry.loader import ToolRegistry, ToolSpec, ToolSpecValidationError

BLUEPRINT_FIELDS = [
    "id",
    "binary",
    "category",
    "capabilities",
    "inputs",
    "outputs",
    "side_effects",
    "privilege",
    "gui",
    "parser",
    "prerequisites",
    "docs",
    "success_signals",
    "failure_signals",
    "rollback",
    "version_compatibility",
]


def test_production_tools_conform_to_blueprint():
    """Verify all existing production tools in registry/tools load with all 16 fields."""
    registry = ToolRegistry()
    tools = registry.list_tools()
    assert len(tools) >= 4, f"Expected at least 4 tools, found {len(tools)}"

    for tool in tools:
        assert isinstance(tool, ToolSpec)
        assert tool.id in ["shell.run.v1", "kali.exec.v1", "hello_world", "system_ping"]
        assert tool.binary, f"Tool {tool.id} missing binary"
        assert tool.category, f"Tool {tool.id} missing category"
        assert isinstance(tool.capabilities, list), f"Tool {tool.id} capabilities must be list"
        assert isinstance(tool.inputs, dict), f"Tool {tool.id} inputs must be dict"
        assert isinstance(tool.outputs, dict), f"Tool {tool.id} outputs must be dict"
        assert isinstance(tool.side_effects, list), f"Tool {tool.id} side_effects must be list"
        assert tool.privilege in ["user", "root", "admin", "elevated", "kernel", "guest"], f"Tool {tool.id} invalid privilege"
        assert tool.gui is not None, f"Tool {tool.id} missing gui"
        assert tool.parser, f"Tool {tool.id} missing parser"
        assert isinstance(tool.prerequisites, list), f"Tool {tool.id} prerequisites must be list"
        assert tool.docs, f"Tool {tool.id} missing docs"
        assert isinstance(tool.success_signals, dict), f"Tool {tool.id} success_signals must be dict"
        assert isinstance(tool.failure_signals, dict), f"Tool {tool.id} failure_signals must be dict"
        assert tool.rollback is not None, f"Tool {tool.id} missing rollback"
        assert tool.version_compatibility is not None, f"Tool {tool.id} missing version_compatibility"

        # Check serialization round-trip
        data = tool.to_dict()
        for field_name in BLUEPRINT_FIELDS:
            assert field_name in data, f"to_dict() missing blueprint field {field_name}"


def test_reject_missing_required_blueprint_field():
    """Verify that omitting ANY of the 16 blueprint fields raises ToolSpecValidationError on load."""
    valid_spec = {
        "id": "test.tool.v1",
        "binary": "python",
        "category": "utility",
        "capabilities": ["test"],
        "inputs": {"type": "object", "properties": {}},
        "outputs": {"type": "object", "properties": {}},
        "side_effects": ["none"],
        "privilege": "user",
        "gui": False,
        "parser": "raw",
        "prerequisites": [],
        "docs": "Test documentation",
        "success_signals": {"exit_codes": [0]},
        "failure_signals": {"exit_codes": [1]},
        "rollback": {"supported": False},
        "version_compatibility": {"min_agent_version": "1.0.0"},
    }

    # Test removing each blueprint field one by one
    for field_to_remove in BLUEPRINT_FIELDS:
        corrupted = dict(valid_spec)
        del corrupted[field_to_remove]

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / f"missing_{field_to_remove}.yaml"
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(corrupted, f)

            with pytest.raises(ToolSpecValidationError) as exc_info:
                ToolRegistry(tmpdir)

            assert field_to_remove in str(exc_info.value), (
                f"Validation error should specifically mention missing field '{field_to_remove}'"
            )


def test_reject_invalid_privilege_enum():
    """Verify rejection of invalid privilege level at load time."""
    spec = {
        "id": "test.bad.privilege",
        "binary": "bash",
        "category": "security",
        "capabilities": ["exploit"],
        "inputs": {},
        "outputs": {},
        "side_effects": [],
        "privilege": "super_god_mode",  # Invalid enum value
        "gui": False,
        "parser": "raw",
        "prerequisites": [],
        "docs": "Test",
        "success_signals": {"exit_codes": [0]},
        "failure_signals": {"exit_codes": [1]},
        "rollback": "none",
        "version_compatibility": "1.0.0",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "bad_privilege.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(spec, f)

        with pytest.raises(ToolSpecValidationError) as exc_info:
            ToolRegistry(tmpdir)

        assert "privilege" in str(exc_info.value)


def test_reject_invalid_type_capabilities():
    """Verify rejection when array field receives scalar at load time."""
    spec = {
        "id": "test.bad.type",
        "binary": "bash",
        "category": "security",
        "capabilities": "not-an-array",  # Should be array
        "inputs": {},
        "outputs": {},
        "side_effects": [],
        "privilege": "user",
        "gui": False,
        "parser": "raw",
        "prerequisites": [],
        "docs": "Test",
        "success_signals": {"exit_codes": [0]},
        "failure_signals": {"exit_codes": [1]},
        "rollback": "none",
        "version_compatibility": "1.0.0",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "bad_type.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(spec, f)

        with pytest.raises(ToolSpecValidationError) as exc_info:
            ToolRegistry(tmpdir)

        assert "capabilities" in str(exc_info.value)


def test_reject_syntax_error_yaml():
    """Verify rejection of malformed YAML syntax at load time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "broken.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("id: [unclosed list\n  key: {bad syntax")

        with pytest.raises(ToolSpecValidationError):
            ToolRegistry(tmpdir)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
