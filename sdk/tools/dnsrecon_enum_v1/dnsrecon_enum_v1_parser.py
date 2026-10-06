"""
Parser for dnsrecon.enum.v1.
Extracts structured DNS records, subdomains, name servers, and findings.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List


class DnsreconEnumV1Parser:
    """Parses raw dnsrecon outputs into structured DNS observation facts."""

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        records: List[Dict[str, str]] = []
        hosts: List[str] = []
        findings: List[Dict[str, Any]] = []

        # Parse standard dnsrecon lines:
        # [*]      A target.lab 192.168.1.50
        # [*]      NS ns1.target.lab 192.168.1.1
        # [*]      MX mail.target.lab 192.168.1.20
        # [*]      TXT v=spf1 ...
        for line in stdout.splitlines():
            line_str = line.strip()
            m = re.match(r"^\[\*\]\s+([A-Z]+)\s+([^\s]+)\s*(.*)$", line_str)
            if m:
                rtype, host, value = m.groups()
                records.append({
                    "type": rtype,
                    "host": host,
                    "value": value,
                })
                if host not in hosts:
                    hosts.append(host)

            # Check for zone transfer vulnerability
            if "Zone Transfer Successful" in line_str or "axfr" in line_str.lower() and "successful" in line_str.lower():
                findings.append({
                    "title": "DNS Zone Transfer Allowed",
                    "severity": "HIGH",
                    "description": line_str,
                })

        # Extract general IPs as hosts
        ip_matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", stdout)
        for ip in ip_matches:
            if ip not in hosts:
                hosts.append(ip)

        return {
            "tool_id": "dnsrecon.enum.v1",
            "exit_code": exit_code,
            "hosts": hosts,
            "dns_records": records,
            "findings": findings,
            "records_count": len(records),
            "raw_stdout_sample": stdout[:1000],
            "raw_stderr": stderr[:500] if stderr else "",
        }
