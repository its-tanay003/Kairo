"""
Kairo Tool Adapters: argument construction + execution + structured output parsing.
Each adapter returns a normalized JSON "observation" object and writes to the event store.
"""
from orchestrator.adapters.base import ToolAdapter, ToolObservation, AdapterResult
from orchestrator.adapters.registry import AdapterRegistry, adapter_registry

__all__ = [
    "ToolAdapter",
    "ToolObservation",
    "AdapterResult",
    "AdapterRegistry",
    "adapter_registry",
]
