"""
Adapter for subfinder.enum.v1.
Implements Kairo ToolAdapter interface.
"""

from __future__ import annotations
from typing import Any, Dict, List
from sdk.base import BaseToolAdapter
from sdk.registry_bridge import register_adapter
from .subfinder_enum_v1_parser import SubfinderEnumV1Parser


class SubfinderEnumV1Adapter(BaseToolAdapter):
    tool_id = "subfinder.enum.v1"
    tool_version = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor, parser=SubfinderEnumV1Parser())

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        domain = inputs.get("domain") or inputs.get("target") or "target.lab"
        args.extend(["-d", str(domain)])

        if inputs.get("silent", True):
            args.append("-silent")

        threads = inputs.get("threads")
        if threads:
            args.extend(["-t", str(threads)])

        timeout = inputs.get("timeout")
        if timeout:
            args.extend(["-timeout", str(timeout)])

        options = inputs.get("options", "")
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)

        return args

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.custom_parser.parse(stdout, stderr, exit_code, meta)


# Self-register into runtime adapter registry
register_adapter(SubfinderEnumV1Adapter)
