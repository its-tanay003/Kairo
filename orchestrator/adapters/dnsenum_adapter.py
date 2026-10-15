"""
Dnsenum Adapter: DNS domain enumeration with structured record and host parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class DnsenumAdapter(ToolAdapter):
    tool_id = "dnsenum.enum.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "dnsenum"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs.get("target") or inputs.get("domain") or "target.local"
        # Strip protocols or slashes if passed
        target = target.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]

        noreverse = inputs.get("noreverse", True)
        threads = int(inputs.get("threads", 5))
        subfile = inputs.get("subfile", "")
        extra = inputs.get("extra_args", [])

        args = [
            f"--threads", str(threads),
            "--nocolor",
        ]
        if noreverse:
            args.append("--noreverse")
        if subfile:
            args += ["-f", str(subfile)]
        args += [str(a) for a in extra]
        args.append(target)
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        target = meta.get("inputs", {}).get("target", "")
        name_servers: List[str] = []
        mail_servers: List[str] = []
        host_addresses: List[Dict[str, str]] = []
        subdomains: List[str] = []
        zone_transfer = {"status": "untested"}

        section = "header"
        for line in stdout.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("___") or line_str.startswith("---"):
                continue

            lower = line_str.lower()
            if "host's addresses" in lower:
                section = "hosts"
                continue
            elif "name servers" in lower:
                section = "ns"
                continue
            elif "mail (mx) servers" in lower:
                section = "mx"
                continue
            elif "zone transfer" in lower:
                section = "axfr"
                continue
            elif "subdomains" in lower:
                section = "subdomains"
                continue

            # Parse lines based on current section
            # Typical format: host.name. 5 IN A 1.2.3.4
            m = re.search(r"(\S+)\s+\d+\s+IN\s+(A|AAAA|CNAME|MX|NS)\s+(\S+)", line_str)
            if m:
                h_name = m.group(1).rstrip(".")
                record_type = m.group(2)
                val = m.group(3).rstrip(".")

                if section == "hosts":
                    host_addresses.append({"host": h_name, "ip": val, "type": record_type})
                elif section == "ns":
                    name_servers.append(val or h_name)
                elif section == "mx":
                    mail_servers.append(val or h_name)
                elif section == "subdomains":
                    subdomains.append(h_name)
                continue

            # Fallback simple IP match
            ip_m = re.search(r"(\S+)\s+(?:has address\s+)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line_str)
            if ip_m and section == "hosts":
                host_addresses.append({"host": ip_m.group(1).rstrip("."), "ip": ip_m.group(2)})

        return {
            "tool": "dnsenum",
            "domain": target,
            "name_servers": list(set(name_servers)),
            "mail_servers": list(set(mail_servers)),
            "host_addresses": host_addresses,
            "subdomains": list(set(subdomains)),
            "zone_transfer": zone_transfer,
            "total_hosts": len(host_addresses),
            "status": "success" if exit_code == 0 or host_addresses else "error",
        }
