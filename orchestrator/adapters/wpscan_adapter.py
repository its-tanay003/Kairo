"""
WPScan WordPress Security Auditor Adapter for Kairo.
Extracts vulnerable plugins, themes, users, and core WordPress flaws.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List
from orchestrator.adapters.base import ToolAdapter


class WpscanAdapter(ToolAdapter):
    tool_id = "wpscan.audit.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "wpscan"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs.get("target") or inputs.get("url") or "http://127.0.0.1:8080"
        detection_mode = inputs.get("detection_mode", "passive")
        enumerate_targets = inputs.get("enumerate", "vp,u")
        options = inputs.get("options", "")

        args = [
            "--url", str(target),
            "--detection-mode", str(detection_mode),
            "-e", str(enumerate_targets),
            "--format", "json",
            "--no-banner",
        ]
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        target = meta.get("inputs", {}).get("target", "") or meta.get("inputs", {}).get("url", "")
        plugins_found: List[Dict[str, Any]] = []
        vulnerabilities: List[Dict[str, Any]] = []
        users: List[str] = []
        findings: List[Dict[str, Any]] = []
        wp_version = "unknown"

        # Attempt JSON parse
        parsed_json = None
        try:
            trimmed = stdout.strip()
            if trimmed.startswith("{"):
                parsed_json = json.loads(trimmed)
        except Exception:
            pass

        if parsed_json and isinstance(parsed_json, dict):
            wp_version = parsed_json.get("version", {}).get("number", "unknown")
            # Parse plugins
            plugins_dict = parsed_json.get("plugins", {})
            for p_name, p_info in plugins_dict.items():
                plugin_entry = {
                    "name": p_name,
                    "version": p_info.get("version", {}).get("number", "unknown") if isinstance(p_info.get("version"), dict) else "unknown",
                    "outdated": p_info.get("outdated", False),
                }
                plugins_found.append(plugin_entry)
                for vuln in p_info.get("vulnerabilities", []):
                    vulnerabilities.append({
                        "plugin": p_name,
                        "title": vuln.get("title", ""),
                        "cve": vuln.get("references", {}).get("cve", []),
                    })
                    findings.append({
                        "type": "plugin_vulnerability",
                        "severity": "HIGH",
                        "name": f"{p_name}: {vuln.get('title', '')}",
                    })

            # Parse users
            users_dict = parsed_json.get("users", {})
            for u_name in users_dict.keys():
                if u_name not in users:
                    users.append(u_name)

        else:
            # Fallback regex parsing on text output
            v_match = re.search(r"WordPress version\s+([0-9\.]+)", stdout, re.IGNORECASE)
            if v_match:
                wp_version = v_match.group(1)

            # Look for plugins "[+] <plugin_name>"
            for p_match in re.finditer(r"\[\+\]\s+([a-zA-Z0-9\-_]+)\s*\n(?:[^\n]*version:\s*([0-9\.]+))?", stdout, re.IGNORECASE):
                p_name = p_match.group(1)
                p_ver = p_match.group(2) or "unknown"
                if p_name.lower() not in ["wordpress", "url", "interesting"]:
                    plugins_found.append({"name": p_name, "version": p_ver})

            # Users "[i] User(s) Identified: \n[+] <user>"
            for u_match in re.finditer(r"\[\+\]\s+([a-zA-Z0-9_\.\-]+)", stdout):
                u_cand = u_match.group(1)
                if u_cand not in users and u_cand.lower() not in ["wordpress", "url", "headers"]:
                    users.append(u_cand)

        return {
            "tool": "wpscan",
            "tool_id": self.tool_id,
            "target": target,
            "exit_code": exit_code,
            "wordpress_version": wp_version,
            "plugins_found": plugins_found,
            "vulnerabilities": vulnerabilities,
            "users": users,
            "findings": findings,
            "total_findings": len(findings) or len(plugins_found),
        }
