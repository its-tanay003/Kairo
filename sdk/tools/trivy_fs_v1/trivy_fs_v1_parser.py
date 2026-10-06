"""
Parser for trivy.fs.v1.
Extracts structured vulnerability findings, packages, CVEs, and secrets from Trivy output.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List


class TrivyFsV1Parser:
    """Parses Trivy JSON and table output into structured security facts."""

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        vulnerabilities: List[Dict[str, Any]] = []
        secrets: List[Dict[str, Any]] = []
        technologies: List[str] = []

        # Try parsing JSON first
        parsed_json = None
        if stdout.strip().startswith("{") or stdout.strip().startswith("["):
            try:
                parsed_json = json.loads(stdout)
                # Trivy schema: {"Results": [{"Target": "...", "Vulnerabilities": [...], "Secrets": [...]}]}
                results = parsed_json.get("Results", []) if isinstance(parsed_json, dict) else parsed_json
                if isinstance(results, list):
                    for res in results:
                        if not isinstance(res, dict):
                            continue
                        target_path = res.get("Target", "")
                        for vuln in res.get("Vulnerabilities", []):
                            vuln_id = vuln.get("VulnerabilityID", "UNKNOWN")
                            pkg_name = vuln.get("PkgName", "")
                            installed_ver = vuln.get("InstalledVersion", "")
                            fixed_ver = vuln.get("FixedVersion", "")
                            severity = vuln.get("Severity", "UNKNOWN")
                            title = vuln.get("Title") or f"{vuln_id} in {pkg_name}"

                            vulnerabilities.append({
                                "cve": vuln_id,
                                "package": pkg_name,
                                "installed_version": installed_ver,
                                "fixed_version": fixed_ver,
                                "severity": severity,
                                "title": title,
                                "target": target_path,
                            })
                            if pkg_name:
                                technologies.append(pkg_name)

                        for secret in res.get("Secrets", []):
                            secrets.append({
                                "rule_id": secret.get("RuleID", "Secret"),
                                "category": secret.get("Category", "Secret"),
                                "severity": secret.get("Severity", "HIGH"),
                                "title": secret.get("Title", "Exposed Secret"),
                                "target": target_path,
                            })
            except Exception:
                pass

        # If not JSON or empty, parse table/text patterns
        if not vulnerabilities and not secrets:
            cve_matches = re.findall(r"(CVE-\d{4}-\d{4,7})\s+([A-Z]+)\s+([a-zA-Z0-9_\.-]+)", stdout)
            for cve, sev, pkg in cve_matches:
                vulnerabilities.append({
                    "cve": cve,
                    "severity": sev,
                    "package": pkg,
                    "title": f"{cve} in {pkg}",
                })
                technologies.append(pkg)

        total_findings = len(vulnerabilities) + len(secrets)

        return {
            "tool_id": "trivy.fs.v1",
            "exit_code": exit_code,
            "vulnerabilities": vulnerabilities,
            "secrets": secrets,
            "technologies": list(set(technologies)),
            "total_findings": total_findings,
            "findings": vulnerabilities + secrets,
            "raw_stdout_sample": stdout[:1000],
            "raw_stderr": stderr[:500] if stderr else "",
        }
