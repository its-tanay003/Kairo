"""
Gobuster Adapter: directory/file/vhost enumeration with text-output parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class GobusterAdapter(ToolAdapter):
    tool_id = "gobuster.dir.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "gobuster"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        url = inputs["url"]
        mode = inputs.get("mode", "dir")
        wordlist = inputs.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        threads = int(inputs.get("threads", 10))
        status_codes = inputs.get("status_codes", "200,204,301,302,307,401,403")
        extensions = inputs.get("extensions", "")
        timeout = int(inputs.get("timeout_s", 10))
        extra = inputs.get("extra_args", [])

        args = [
            mode,
            "-u", url,
            "-w", wordlist,
            "-t", str(threads),
            "--timeout", f"{timeout}s",
            "-s", status_codes,
            "--no-error",
        ]
        if extensions:
            args += ["-x", extensions]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        findings = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("=") or line.startswith("Go"):
                continue
            # "Found: /admin (Status: 301) [Size: 123]" or just "/admin (Status: 200)"
            m = re.search(r"(?:Found:\s+)?(/\S*)\s+\(Status:\s*(\d+)\)(?:\s+\[Size:\s*(\d+)\])?(?:\s+->\s+(\S+))?", line)
            if m:
                findings.append({
                    "path": m.group(1),
                    "status": int(m.group(2)),
                    "size": int(m.group(3)) if m.group(3) else None,
                    "redirect": m.group(4) or "",
                })
        return {
            "tool": "gobuster",
            "target_url": meta.get("inputs", {}).get("url", ""),
            "mode": meta.get("inputs", {}).get("mode", "dir"),
            "findings": findings,
            "total_found": len(findings),
        }
