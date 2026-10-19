"""
Subfinder Adapter for Kairo.
Performs passive subdomain discovery and structured asset extraction.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List
from orchestrator.adapters.base import ToolAdapter


class SubfinderAdapter(ToolAdapter):
    tool_id = "subfinder.enum.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "subfinder"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs.get("target") or inputs.get("domain") or "127.0.0.1"
        args = ["-d", str(target), "-silent"]

        threads = inputs.get("threads")
        if threads:
            args += ["-t", str(threads)]

        timeout_s = inputs.get("timeout_s") or inputs.get("timeout")
        if timeout_s:
            args += ["-timeout", str(timeout_s)]

        options = inputs.get("options", "")
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)

        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        subdomains: List[str] = []
        findings: List[Dict[str, Any]] = []

        target = meta.get("inputs", {}).get("target", "") or meta.get("inputs", {}).get("domain", "")

        for line in stdout.splitlines():
            s = line.strip()
            if not s or s.startswith("[") or " " in s:
                continue
            if s not in subdomains:
                subdomains.append(s)
                findings.append({
                    "subdomain": s,
                    "target": target,
                    "type": "subdomain_asset",
                })

        return {
            "tool": "subfinder",
            "tool_id": self.tool_id,
            "target": target,
            "exit_code": exit_code,
            "subdomains": subdomains,
            "findings": findings,
            "total_found": len(subdomains),
        }
