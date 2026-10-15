"""
Nikto Adapter: web vulnerability scanner with CSV output parser.
"""
from __future__ import annotations
import csv
import io
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from orchestrator.adapters.base import ToolAdapter

class NiktoAdapter(ToolAdapter):
    tool_id = "nikto.scan.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "nikto"


    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        raw = inputs.get("host") or inputs.get("target") or inputs.get("url") or "127.0.0.1"
        raw_str = str(raw).strip()

        ssl_inferred = False
        if raw_str.startswith("https://"):
            ssl_inferred = True
            raw_str = raw_str[8:]
        elif raw_str.startswith("http://"):
            raw_str = raw_str[7:]

        # Strip URL paths or queries if passed
        if "/" in raw_str:
            raw_str = raw_str.split("/")[0]

        port = inputs.get("port")
        if ":" in raw_str:
            parts = raw_str.split(":", 1)
            host = parts[0]
            if not port:
                try:
                    port = int(parts[1])
                except ValueError:
                    port = 443 if ssl_inferred else 80
        else:
            host = raw_str

        if not port:
            port = 443 if ssl_inferred else int(inputs.get("port", 80))
        else:
            port = int(port)

        ssl = inputs.get("ssl", ssl_inferred or (port == 443))
        plugins = inputs.get("plugins", "")
        tuning = inputs.get("tuning", "")
        timeout = int(inputs.get("timeout", 3))
        maxtime = str(inputs.get("maxtime", "35s")).strip()
        extra = inputs.get("extra_args", [])

        args = [
            "-h", host,
            "-p", str(port),
            "-Format", "csv",
            "-timeout", str(timeout),
            "-maxtime", maxtime,
            "-ipv4",
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
        error_msg = None

        combined_text = f"{stdout}\n{stderr}"
        if "Cannot resolve hostname" in combined_text:
            error_msg = "Cannot resolve hostname: DNS lookup failed"
            server_info["connection_status"] = "unresolvable"
        elif "Unable to connect" in combined_text or "Connection refused" in combined_text:
            error_msg = "Target port is closed or not accepting HTTP/HTTPS connections"
            server_info["connection_status"] = "unreachable"
        elif "timed out" in combined_text.lower():
            error_msg = "Scan reached timeout limit"
            server_info["connection_status"] = "timeout"

        # Parse CSV lines from nikto output
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
                if row["osvdb"].strip().lower() == "osvdb":
                    continue
                findings.append({
                    "id": row.get("osvdb", "").strip().strip('"'),
                    "method": row.get("method", "").strip().strip('"') or "GET",
                    "uri": row.get("uri", "").strip().strip('"') or "/",
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
            m3 = re.search(r"Target IP:\s+(\S+)", line)
            if m3:
                server_info["target_ip"] = m3.group(1).strip()
            m4 = re.search(r"Target Port:\s+(\d+)", line)
            if m4:
                server_info["target_port"] = int(m4.group(1).strip())

        inputs_meta = meta.get("inputs", {})
        target_display = inputs_meta.get("host") or inputs_meta.get("target") or inputs_meta.get("url") or "127.0.0.1"

        return {
            "tool": "nikto",
            "target": target_display,
            "findings": findings,
            "vulnerabilities": findings,
            "total_findings": len(findings),
            "alerts_count": len(findings),
            "server_info": server_info,
            "status": "error" if error_msg and not findings else "success",
            "error": error_msg,
        }

