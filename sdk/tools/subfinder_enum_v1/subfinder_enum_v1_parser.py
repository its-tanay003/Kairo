"""
Parser for subfinder.enum.v1.
Extracts structured observation facts from subfinder stdout/stderr.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List


class SubfinderEnumV1Parser:
    """Parses raw subfinder outputs into structured finding dictionaries."""

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        subdomains: List[str] = []
        hosts: List[str] = []
        findings: List[Dict[str, Any]] = []

        # Parse line-delimited subdomains (standard subfinder output)
        for line in stdout.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("[") or " " in clean:
                continue
            if "." in clean:
                subdomains.append(clean)
                if clean not in hosts:
                    hosts.append(clean)

        # Extract IPs
        ip_matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", stdout)
        for ip in ip_matches:
            if ip not in hosts:
                hosts.append(ip)

        if subdomains:
            findings.append({
                "title": f"Discovered {len(subdomains)} Subdomains",
                "severity": "INFO",
                "count": len(subdomains),
                "subdomains": subdomains[:50],
            })

        return {
            "tool_id": "subfinder.enum.v1",
            "exit_code": exit_code,
            "subdomains": subdomains,
            "hosts": hosts,
            "findings": findings,
            "count": len(subdomains),
            "raw_stdout_sample": stdout[:500],
            "raw_stderr": stderr[:500] if stderr else "",
        }
