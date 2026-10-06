"""
Adapter for dnsrecon.enum.v1.
Implements Kairo ToolAdapter interface for DNSRecon enumeration.
"""

from __future__ import annotations
from typing import Any, Dict, List
from sdk.base import BaseToolAdapter
from sdk.registry_bridge import register_adapter
from .dnsrecon_enum_v1_parser import DnsreconEnumV1Parser


class DnsreconEnumV1Adapter(BaseToolAdapter):
    tool_id = "dnsrecon.enum.v1"
    tool_version = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor, parser=DnsreconEnumV1Parser())

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        domain = inputs.get("domain") or inputs.get("target") or "target.lab"
        args.extend(["-d", str(domain)])

        scan_type = inputs.get("scan_type", "std")
        args.extend(["-t", str(scan_type)])

        dictionary = inputs.get("dictionary")
        if dictionary:
            args.extend(["-D", str(dictionary)])

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


# Register dynamically into Kairo runtime
register_adapter(DnsreconEnumV1Adapter)
