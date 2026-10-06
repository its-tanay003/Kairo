"""
Parser for wpscan.audit.v1.
Extracts WordPress version, detected plugins, identified vulnerabilities, and enumerated users.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List


class WpscanAuditV1Parser:
    """Parses WPScan output into structured WordPress security findings."""

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        wp_version = None
        plugins: List[Dict[str, str]] = []
        vulnerabilities: List[Dict[str, Any]] = []
        users: List[str] = []
        technologies: List[str] = ["WordPress"]

        # 1. Parse WordPress core version
        v_match = re.search(r"WordPress version ([0-9\.]+) identified", stdout, re.IGNORECASE)
        if v_match:
            wp_version = v_match.group(1)
            technologies.append(f"WordPress {wp_version}")

        # 2. Parse plugins
        # [i] Plugin: contact-form-7 (version 5.1.0)
        plugin_matches = re.findall(r"\[i\] Plugin:?\s+([a-zA-Z0-9_-]+)(?:\s+\(version\s+([0-9\.]+)\))?", stdout)
        for p_name, p_ver in plugin_matches:
            plugins.append({
                "name": p_name,
                "version": p_ver if p_ver else "unknown",
            })
            technologies.append(f"WordPress-Plugin:{p_name}")

        # 3. Parse vulnerabilities
        # [!] Title: Contact Form 7 Remote Code Execution
        vuln_matches = re.findall(r"\[!\]\s+(?:Title:\s+)?(.*)$", stdout, re.MULTILINE)
        for v_title in vuln_matches:
            v_title_clean = v_title.strip()
            if v_title_clean and not v_title_clean.startswith("[") and "outdated" not in v_title_clean.lower():
                vulnerabilities.append({
                    "title": v_title_clean,
                    "severity": "HIGH" if "execution" in v_title_clean.lower() or "sql" in v_title_clean.lower() else "MEDIUM",
                })

        # 4. Parse enumerated users
        # [i] User: admin
        user_matches = re.findall(r"\[i\] User:?\s+([a-zA-Z0-9_\.-]+)", stdout)
        users.extend(list(set(user_matches)))

        # Also support JSON format if tool was run with --format json
        if stdout.strip().startswith("{"):
            try:
                data = json.loads(stdout)
                if "version" in data and isinstance(data["version"], dict):
                    wp_version = data["version"].get("number", wp_version)
                if "plugins" in data and isinstance(data["plugins"], dict):
                    for p_k, p_v in data["plugins"].items():
                        plugins.append({
                            "name": p_k,
                            "version": p_v.get("version", {}).get("number", "unknown") if isinstance(p_v, dict) else "unknown"
                        })
                if "users" in data and isinstance(data["users"], dict):
                    users.extend(list(data["users"].keys()))
            except Exception:
                pass

        return {
            "tool_id": "wpscan.audit.v1",
            "exit_code": exit_code,
            "wordpress_version": wp_version or "unknown",
            "technologies": technologies,
            "plugins_found": plugins,
            "vulnerabilities": vulnerabilities,
            "users": users,
            "findings": vulnerabilities,
            "raw_stdout_sample": stdout[:1000],
            "raw_stderr": stderr[:500] if stderr else "",
        }
