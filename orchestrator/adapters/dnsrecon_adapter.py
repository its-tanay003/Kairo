"""
DNSRecon Adapter for Kairo.
Performs advanced DNS enumeration, zone transfer checks, and record extraction.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List
from orchestrator.adapters.base import ToolAdapter


class DnsreconAdapter(ToolAdapter):
    tool_id = "dnsrecon.enum.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "dnsrecon"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs.get("target") or inputs.get("domain") or "target.lab"
        scan_type = inputs.get("scan_type", "std")
        dictionary = inputs.get("dictionary", "")
        options = inputs.get("options", "")

        args = ["-d", str(target), "-t", str(scan_type)]
        if dictionary:
            args += ["-D", str(dictionary)]
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        records: List[Dict[str, str]] = []
        hosts: List[str] = []
        findings: List[Dict[str, Any]] = []

        for line in stdout.splitlines():
            line_str = line.strip()
            # [*] A target.lab 192.168.1.50
            m = re.match(r"^\[\*\]\s+([A-Z]+)\s+([^\s]+)\s*(.*)$", line_str)
            if m:
                rtype, host, val = m.groups()
                records.append({"type": rtype, "host": host, "value": val})
                if host not in hosts:
                    hosts.append(host)

            if "Zone Transfer Successful" in line_str or ("axfr" in line_str.lower() and "successful" in line_str.lower()):
                findings.append({
                    "title": "DNS Zone Transfer Allowed",
                    "severity": "HIGH",
                    "description": line_str,
                })

        # Extract IPv4 addresses
        for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", stdout):
            if ip not in hosts:
                hosts.append(ip)

        target = meta.get("inputs", {}).get("target", "") or meta.get("inputs", {}).get("domain", "")
        return {
            "tool": "dnsrecon",
            "tool_id": self.tool_id,
            "target": target,
            "exit_code": exit_code,
            "hosts": hosts,
            "dns_records": records,
            "findings": findings,
            "records_count": len(records),
        }
