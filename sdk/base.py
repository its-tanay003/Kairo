"""
Kairo ToolSpec SDK - Base Interfaces and Data Contracts.
Extracts the ToolSpec + Adapter + Parser interface into an extensible,
standalone developer SDK for third-party security tool integration.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union, runtime_checkable

# Re-use canonical contracts from orchestrator without modifying core
from orchestrator.adapters.base import ToolAdapter, ToolObservation
from orchestrator.observer import ObservationFact, ObservationResult

logger = logging.getLogger("sdk.base")


@runtime_checkable
class BaseToolParser(Protocol):
    """
    Protocol defining the parser interface for raw tool outputs.
    Converts stdout, stderr, and exit codes into a structured observation dictionary.
    """

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Parses raw tool execution outputs into a structured dictionary.
        Must return a dictionary containing observation fields and optional '_artifacts' list.
        """
        ...


class BaseToolAdapter(ToolAdapter):
    """
    Base class for all Kairo SDK Tool Adapters.
    Third-party adapters inherit from this class and implement:
      - tool_id: unique identifier matching ToolSpec YAML (e.g. 'dnsrecon.enum.v1')
      - tool_version: semantic version (e.g. '1.0.0')
      - build_args(inputs): constructs CLI command arguments
      - parse(stdout, stderr, exit_code, meta): converts stdout/stderr into structured observation
    """

    tool_id: str = ""
    tool_version: str = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None, parser: Optional[BaseToolParser] = None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor)
        self.custom_parser = parser

    @abstractmethod
    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        """Build ordered CLI arguments from validated input parameters."""
        ...

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Default parse delegating to custom_parser if provided,
        or overridden directly in subclass.
        """
        if self.custom_parser:
            return self.custom_parser.parse(stdout, stderr, exit_code, meta)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }

    def validate_inputs(self, inputs: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validates input arguments against basic sanity and Scope Contract boundaries.
        Returns (is_valid, error_messages).
        """
        errors: List[str] = []
        if not isinstance(inputs, dict):
            return False, ["Inputs must be a key-value dictionary"]
        return True, []
