"""
Kairo ToolSpec SDK.
Standalone developer SDK for creating, packaging, testing, and verifying
third-party security tools for the Kairo autonomous security engineering platform.
"""

from sdk.base import BaseToolAdapter, BaseToolParser
from sdk.conformance import ConformanceReport, GateResult, ToolSpecConformanceRunner
from sdk.generator import ToolSpecGenerator, to_class_name, to_slug
from sdk.registry_bridge import (
    auto_discover_sdk_tools,
    load_toolspec,
    register_adapter,
)

__version__ = "1.0.0"

__all__ = [
    "BaseToolAdapter",
    "BaseToolParser",
    "ConformanceReport",
    "GateResult",
    "ToolSpecConformanceRunner",
    "ToolSpecGenerator",
    "auto_discover_sdk_tools",
    "load_toolspec",
    "register_adapter",
    "to_class_name",
    "to_slug",
]
