"""
Adapter for trivy.fs.v1.
Implements Kairo ToolAdapter interface for Trivy filesystem scanning.
"""

from __future__ import annotations
from typing import Any, Dict, List
from sdk.base import BaseToolAdapter
from sdk.registry_bridge import register_adapter
from .trivy_fs_v1_parser import TrivyFsV1Parser


class TrivyFsV1Adapter(BaseToolAdapter):
    tool_id = "trivy.fs.v1"
    tool_version = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor, parser=TrivyFsV1Parser())

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        args: List[str] = ["fs"]
        
        severity = inputs.get("severity", "HIGH,CRITICAL")
        args.extend(["--severity", str(severity)])

        scanners = inputs.get("scanners", "vuln,secret")
        args.extend(["--scanners", str(scanners)])

        output_format = inputs.get("format", "json")
        args.extend(["--format", str(output_format)])

        target = inputs.get("target") or inputs.get("path") or "."
        args.append(str(target))

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
register_adapter(TrivyFsV1Adapter)
