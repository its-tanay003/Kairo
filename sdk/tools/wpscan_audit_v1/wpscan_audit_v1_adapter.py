"""
Adapter for wpscan.audit.v1.
Implements Kairo ToolAdapter interface for WordPress vulnerability scanning.
"""

from __future__ import annotations
from typing import Any, Dict, List
from sdk.base import BaseToolAdapter
from sdk.registry_bridge import register_adapter
from .wpscan_audit_v1_parser import WpscanAuditV1Parser


class WpscanAuditV1Adapter(BaseToolAdapter):
    tool_id = "wpscan.audit.v1"
    tool_version = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor, parser=WpscanAuditV1Parser())

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        target = inputs.get("target") or inputs.get("url") or "http://127.0.0.1:8080"
        args.extend(["--url", str(target)])

        detection_mode = inputs.get("detection_mode", "passive")
        args.extend(["--detection-mode", str(detection_mode)])

        enumerate_targets = inputs.get("enumerate", "vp,u")
        args.extend(["-e", str(enumerate_targets)])

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
register_adapter(WpscanAuditV1Adapter)
