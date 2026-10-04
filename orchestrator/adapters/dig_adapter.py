"""
Dig DNS Adapter: DNS interrogation with structured answer/authority section parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class DigAdapter(ToolAdapter):
    tool_id = "dig.lookup.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "dig"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs["target"]
        record_type = inputs.get("record_type", "A")
        server = inputs.get("server", "")
        port = int(inputs.get("port", 53))
        timeout = int(inputs.get("timeout", 5))
        extra = inputs.get("extra_args", [])

        args = []
        if server:
            args.append(f"@{server.lstrip('@')}")
        if port != 53:
            args += ["-p", str(port)]
        args += [target, record_type]
        args += ["+time=" + str(timeout), "+tries=2"]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        answers: List[Dict[str, Any]] = []
        authority: List[Dict[str, Any]] = []
        additional: List[Dict[str, Any]] = []
        query_time_ms = 0
        server_used = ""
        status = "NOERROR"
        section = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                if ";; ANSWER SECTION:" in line:
                    section = "answer"
                elif ";; AUTHORITY SECTION:" in line:
                    section = "authority"
                elif ";; ADDITIONAL SECTION:" in line:
                    section = "additional"
                elif ";; Query time:" in line:
                    m = re.search(r"(\d+)\s+msec", line)
                    if m:
                        query_time_ms = int(m.group(1))
                    section = None
                elif ";; SERVER:" in line:
                    m = re.search(r"SERVER:\s+(.+?)#", line)
                    if m:
                        server_used = m.group(1).strip()
                    section = None
                elif ";; ->>HEADER<<-" in line:
                    m = re.search(r"status:\s+(\w+)", line)
                    if m:
                        status = m.group(1)
                    section = None
                continue

            if section and line:
                # Parse RR: "example.com. 300 IN A 93.184.216.34"
                parts = line.split()
                if len(parts) >= 4:
                    record: Dict[str, Any] = {
                        "name": parts[0].rstrip("."),
                        "ttl": int(parts[1]) if parts[1].isdigit() else 0,
                        "class": parts[2] if len(parts) > 2 else "IN",
                        "type": parts[3] if len(parts) > 3 else "",
                        "value": " ".join(parts[4:]) if len(parts) > 4 else "",
                    }
                    if section == "answer":
                        answers.append(record)
                    elif section == "authority":
                        authority.append(record)
                    elif section == "additional":
                        additional.append(record)

        return {
            "tool": "dig",
            "target": meta.get("inputs", {}).get("target", ""),
            "record_type": meta.get("inputs", {}).get("record_type", "A"),
            "status": status,
            "answers": answers,
            "authority": authority,
            "additional": additional,
            "query_time_ms": query_time_ms,
            "server_used": server_used,
            "answers_count": len(answers),
        }
