"""
Nikto Adapter: web vulnerability scanner with CSV output parser.
"""
from __future__ import annotations
import csv
import io
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class NiktoAdapter(ToolAdapter):
    tool_id = "nikto.scan.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "nikto"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        host = inputs["host"]
        port = int(inputs.get("port", 80))
        ssl = inputs.get("ssl", False)
        plugins = inputs.get("plugins", "")
        tuning = inputs.get("tuning", "")
        timeout = int(inputs.get("timeout", 10))
        extra = inputs.get("extra_args", [])

        args = [
            "-h", host,
            "-p", str(port),
            "-Format", "csv",
            "-timeout", str(timeout),
            "-nointeractive",
        ]
        if ssl:
            args.append("-ssl")
        if plugins:
            args += ["-Plugins", plugins]
        if tuning:
            args += ["-Tuning", tuning]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        findings = []
        server_info: Dict[str, Any] = {}

        # Parse CSV lines from nikto output
        # Nikto CSV format: "host","ip","port","osvdb","method","uri","description"
        lines = [l for l in stdout.splitlines() if l.strip() and not l.startswith("#")]
        if lines:
            reader = csv.DictReader(
                lines,
                fieldnames=["host", "ip", "port", "osvdb", "method", "uri", "description"],
                skipinitialspace=True,
            )
            for row in reader:
                if not row.get("osvdb"):
                    continue
                # Skip header-like rows
                if row["osvdb"].strip().lower() == "osvdb":
                    continue
                findings.append({
                    "id": row.get("osvdb", "").strip().strip('"'),
                    "method": row.get("method", "").strip().strip('"'),
                    "uri": row.get("uri", "").strip().strip('"'),
                    "osvdb": row.get("osvdb", "").strip().strip('"'),
                    "description": row.get("description", "").strip().strip('"'),
                })

        # Try to extract server info and text findings from non-CSV output
        for line in stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("+ /"):
                parts = line_str[2:].split(":", 1)
                uri = parts[0].strip()
                desc = parts[1].strip() if len(parts) > 1 else uri
                findings.append({
                    "id": "NIKTO-FINDING",
                    "method": "GET",
                    "uri": uri,
                    "osvdb": "OSVDB-0",
                    "description": desc,
                })
            m = re.search(r"Server:\s+(.+)", line)
            if m:
                server_info["server"] = m.group(1).strip()
            m2 = re.search(r"Retrieved\s+(\w+)\s+header:\s+(.+)", line, re.I)
            if m2:
                server_info[m2.group(1).lower()] = m2.group(2).strip()

        return {
            "tool": "nikto",
            "target": f"{meta.get('inputs', {}).get('host', '')}:{meta.get('inputs', {}).get('port', 80)}",
            "findings": findings,
            "total_findings": len(findings),
            "server_info": server_info,
        }
