"""
Kairo Tool Adapters: argument construction + execution + structured output parsing.
Each adapter returns a normalized JSON "observation" object and writes to the event store.
"""
from orchestrator.adapters.base import ToolAdapter, ToolObservation, AdapterResult
from orchestrator.adapters.gui_base import BaseGuiAdapter, GuiControl
from orchestrator.adapters.burpsuite_adapter import BurpSuiteGuiAdapter
from orchestrator.adapters.wireshark_adapter import WiresharkGuiAdapter
from orchestrator.adapters.zap_adapter import ZapGuiAdapter
from orchestrator.adapters.browser_adapter import SecurityBrowserAdapter, browser_adapter
from orchestrator.adapters.registry import AdapterRegistry, adapter_registry

__all__ = [
    "ToolAdapter",
    "ToolObservation",
    "AdapterResult",
    "BaseGuiAdapter",
    "GuiControl",
    "BurpSuiteGuiAdapter",
    "WiresharkGuiAdapter",
    "ZapGuiAdapter",
    "SecurityBrowserAdapter",
    "browser_adapter",
    "AdapterRegistry",
    "adapter_registry",
]

