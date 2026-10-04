"""
AdapterRegistry: auto-discover and register all tool adapters by tool_id.
"""
from __future__ import annotations
import importlib
import logging
from typing import Dict, Optional, Type
from orchestrator.adapters.base import ToolAdapter

logger = logging.getLogger("orchestrator.adapters.registry")

# Map of tool_id -> adapter class
_ADAPTER_MODULES = [
    "orchestrator.adapters.nmap_adapter",
    "orchestrator.adapters.metasploit_adapter",
    "orchestrator.adapters.gobuster_adapter",
    "orchestrator.adapters.ffuf_adapter",
    "orchestrator.adapters.nikto_adapter",
    "orchestrator.adapters.whatweb_adapter",
    "orchestrator.adapters.sqlmap_adapter",
    "orchestrator.adapters.hydra_adapter",
    "orchestrator.adapters.searchsploit_adapter",
    "orchestrator.adapters.whois_adapter",
    "orchestrator.adapters.dig_adapter",
    "orchestrator.adapters.tcpdump_adapter",
    "orchestrator.adapters.exiftool_adapter",
    "orchestrator.adapters.hashid_adapter",
]


class AdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, Type[ToolAdapter]] = {}
        self._load_all()

    def _load_all(self):
        for module_path in _ADAPTER_MODULES:
            try:
                mod = importlib.import_module(module_path)
                # Find ToolAdapter subclasses in module
                for name in dir(mod):
                    obj = getattr(mod, name)
                    try:
                        if (
                            isinstance(obj, type)
                            and issubclass(obj, ToolAdapter)
                            and obj is not ToolAdapter
                            and obj.tool_id
                        ):
                            self._adapters[obj.tool_id] = obj
                            logger.debug(f"[AdapterRegistry] Registered adapter: {obj.tool_id}")
                    except Exception:
                        pass
            except ImportError as e:
                logger.warning(f"[AdapterRegistry] Could not load {module_path}: {e}")

    def get(self, tool_id: str) -> Optional[Type[ToolAdapter]]:
        return self._adapters.get(tool_id)

    def get_instance(self, tool_id: str) -> Optional[ToolAdapter]:
        cls = self.get(tool_id)
        return cls() if cls else None

    def list_tool_ids(self):
        return list(self._adapters.keys())

    def all(self) -> Dict[str, Type[ToolAdapter]]:
        return dict(self._adapters)


# Singleton
adapter_registry = AdapterRegistry()
