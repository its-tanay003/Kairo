"""
Nmap Adapter: arg construction + execution + XML parser -> structured observation.
"""
from __future__ import annotations
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

logger = logging.getLogger("orchestrator.adapters.nmap")


class NmapAdapter(ToolAdapter):
    tool_id = "nmap.scan.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "nmap"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs["target"]
        ports = inputs.get("ports", "1-1024")
        scan_type = inputs.get("scan_type", "sV")
        scripts = inputs.get("scripts", "")
        timing = int(inputs.get("timing", 3))
        extra = inputs.get("extra_args", [])

        args = [f"-{scan_type}", f"-T{timing}", "--open", "-oX", "-"]
        if ports and ports != "-":
            args += ["-p", str(ports)]
        elif ports == "-":
            args += ["-p-"]
        if scripts:
            args += [f"--script={scripts}"]
        args += [str(a) for a in extra]
        args.append(target)
        return args

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        hosts = []
        scan_stats: Dict[str, Any] = {}

        # nmap -oX - writes XML to stdout
        xml_text = stdout.strip()
        if not xml_text or not xml_text.startswith("<?xml"):
            # Fallback: try text parse
            return self._parse_text(stdout, stderr, exit_code)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            return {
                "parse_error": f"XML parse failed: {e}",
                "hosts": [],
                "raw_snippet": stdout[:500],
            }

        for host_el in root.findall("host"):
            host: Dict[str, Any] = {
                "ip": "",
                "hostname": "",
                "state": "unknown",
                "ports": [],
                "os": [],
            }

            status_el = host_el.find("status")
            if status_el is not None:
                host["state"] = status_el.get("state", "unknown")

            # Addresses
            for addr_el in host_el.findall("address"):
                if addr_el.get("addrtype") == "ipv4":
                    host["ip"] = addr_el.get("addr", "")
                elif addr_el.get("addrtype") == "mac":
                    host["mac"] = addr_el.get("addr", "")

            # Hostnames
            hnames_el = host_el.find("hostnames")
            if hnames_el is not None:
                for hn in hnames_el.findall("hostname"):
                    host["hostname"] = hn.get("name", "")
                    break

            # Ports
            ports_el = host_el.find("ports")
            if ports_el is not None:
                for port_el in ports_el.findall("port"):
                    port_info: Dict[str, Any] = {
                        "port": int(port_el.get("portid", 0)),
                        "protocol": port_el.get("protocol", "tcp"),
                        "state": "unknown",
                        "service": "",
                        "version": "",
                        "product": "",
                        "extrainfo": "",
                        "scripts": [],
                    }
                    state_el = port_el.find("state")
                    if state_el is not None:
                        port_info["state"] = state_el.get("state", "unknown")
                    svc_el = port_el.find("service")
                    if svc_el is not None:
                        port_info["service"] = svc_el.get("name", "")
                        port_info["version"] = svc_el.get("version", "")
                        port_info["product"] = svc_el.get("product", "")
                        port_info["extrainfo"] = svc_el.get("extrainfo", "")
                    # NSE scripts
                    for script_el in port_el.findall("script"):
                        port_info["scripts"].append({
                            "id": script_el.get("id", ""),
                            "output": script_el.get("output", "")[:500],
                        })
                    host["ports"].append(port_info)

            # OS detection
            os_el = host_el.find("os")
            if os_el is not None:
                for match in os_el.findall("osmatch"):
                    host["os"].append({
                        "name": match.get("name", ""),
                        "accuracy": int(match.get("accuracy", 0)),
                    })

            hosts.append(host)

        # Stats
        run_stats_el = root.find("runstats")
        if run_stats_el is not None:
            finished_el = run_stats_el.find("finished")
            if finished_el is not None:
                scan_stats["elapsed"] = finished_el.get("elapsed", "")
                scan_stats["summary"] = finished_el.get("summary", "")
            hosts_el = run_stats_el.find("hosts")
            if hosts_el is not None:
                scan_stats["hosts_up"] = int(hosts_el.get("up", 0))
                scan_stats["hosts_down"] = int(hosts_el.get("down", 0))
                scan_stats["hosts_total"] = int(hosts_el.get("total", 0))

        return {
            "tool": "nmap",
            "target": meta.get("inputs", {}).get("target", ""),
            "hosts": hosts,
            "hosts_found": len(hosts),
            "open_ports": sum(
                len([p for p in h["ports"] if p["state"] == "open"]) for h in hosts
            ),
            "scan_stats": scan_stats,
        }

    def _parse_text(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """Fallback text-mode parser when XML is unavailable."""
        hosts = []
        current_host: Dict[str, Any] = {}
        for line in stdout.splitlines():
            m = re.match(r"Nmap scan report for (.+)", line)
            if m:
                if current_host:
                    hosts.append(current_host)
                current_host = {"hostname": m.group(1).strip(), "ip": "", "ports": [], "state": "up"}
            m2 = re.match(r"(\d+)/(\w+)\s+(\w+)\s+(.+)", line)
            if m2 and current_host:
                current_host["ports"].append({
                    "port": int(m2.group(1)),
                    "protocol": m2.group(2),
                    "state": m2.group(3),
                    "service": m2.group(4).split()[0] if m2.group(4) else "",
                    "version": " ".join(m2.group(4).split()[1:]) if m2.group(4) else "",
                })
        if current_host:
            hosts.append(current_host)
        return {"tool": "nmap", "hosts": hosts, "hosts_found": len(hosts), "mode": "text_fallback"}
