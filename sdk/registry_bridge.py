"""
Kairo ToolSpec SDK - Runtime Registry Bridge.
Bridges SDK-defined third-party tools into the Kairo ToolRegistry and AdapterRegistry
dynamically at runtime WITHOUT modifying core orchestrator or gateway files.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.adapters.base import ToolAdapter
from orchestrator.adapters.registry import adapter_registry
from registry.loader import ToolRegistry, ToolSpec

logger = logging.getLogger("sdk.registry_bridge")


def register_adapter(adapter_cls: Type[ToolAdapter]) -> None:
    """
    Registers a third-party ToolAdapter into the Kairo runtime adapter registry
    without modifying core orchestrator code.
    """
    if not hasattr(adapter_cls, "tool_id") or not adapter_cls.tool_id:
        raise ValueError(f"Adapter {adapter_cls.__name__} must define a non-empty 'tool_id'")

    adapter_registry._adapters[adapter_cls.tool_id] = adapter_cls
    logger.info(f"[SDK Bridge] Dynamically registered adapter for tool_id='{adapter_cls.tool_id}'")


def load_toolspec(yaml_path: Path | str, registry: Optional[ToolRegistry] = None) -> ToolSpec:
    """
    Loads and validates a third-party ToolSpec YAML file against the 16-field blueprint schema.
    """
    reg = registry or ToolRegistry()
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"ToolSpec YAML not found at: {path}")

    # Use existing ToolRegistry validation
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    errors = reg.validate_spec_data(data)
    if errors:
        raise ValueError(f"ToolSpec validation failed for {path.name}: {'; '.join(errors)}")

    spec = ToolSpec.from_dict(data)
    reg._tools[spec.id] = spec
    logger.info(f"[SDK Bridge] Loaded schema-validated ToolSpec: '{spec.id}'")
    return spec


def load_module_from_file(py_path: Path | str):
    """Dynamically imports a Python module from an arbitrary file path."""
    path = Path(py_path).resolve()
    
    # If path is inside ROOT_DIR, attempt standard package import
    try:
        rel = path.relative_to(ROOT_DIR)
        dotted = ".".join(rel.with_suffix("").parts)
        import importlib
        return importlib.import_module(dotted)
    except Exception:
        pass

    parent_str = str(path.parent)
    if parent_str not in sys.path:
        sys.path.insert(0, parent_str)

    module_name = f"sdk_tool_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if not spec or not spec.loader:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def auto_discover_sdk_tools(search_dir: Optional[Path | str] = None) -> List[str]:
    """
    Scans a directory (and subdirectories) for *_adapter.py files, discovers ToolAdapter subclasses,
    and registers them into the runtime adapter registry.
    """
    discovered: List[str] = []
    p = Path(search_dir) if search_dir is not None else ROOT_DIR / "sdk" / "tools"
    if not p.exists():
        return discovered

    seen_files = set()
    candidate_files = list(p.glob("*_adapter.py")) + list(p.rglob("*_adapter.py"))

    for py_file in candidate_files:
        if py_file in seen_files:
            continue
        seen_files.add(py_file)
        try:
            mod = load_module_from_file(py_file)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, ToolAdapter)
                    and obj is not ToolAdapter
                    and getattr(obj, "tool_id", "")
                ):
                    register_adapter(obj)
                    if obj.tool_id not in discovered:
                        discovered.append(obj.tool_id)
        except Exception as e:
            logger.warning(f"[SDK Bridge] Failed discovering adapter in {py_file.name}: {e}")

    return discovered
