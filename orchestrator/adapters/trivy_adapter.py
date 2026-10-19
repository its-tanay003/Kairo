"""
Trivy Filesystem Vulnerability Scanner Adapter for Kairo.
Parses JSON and table outputs into structured CVEs, secrets, and package flaw findings.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List
from orchestrator.adapters.base import ToolAdapter


class TrivyAdapter(ToolAdapter):
    tool_id = "trivy.fs.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "trivy"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs.get("target") or inputs.get("path") or "."
        severity = inputs.get("severity", "HIGH,CRITICAL")
        scanners = inputs.get("scanners", "vuln,secret")
        fmt = inputs.get("format", "json")
        options = inputs.get("options", "")

        args = [
            "fs",
            "--severity", str(severity),
            "--scanners", str(scanners),
            "--format", str(fmt),
            str(target),
        ]
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        target = meta.get("inputs", {}).get("target", "") or "."
        vulnerabilities: List[Dict[str, Any]] = []
        secrets: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []

        # Attempt JSON parse
        parsed_json = None
        try:
            trimmed = stdout.strip()
            if trimmed.startswith("{") or trimmed.startswith("["):
                parsed_json = json.loads(trimmed)
        except Exception:
            pass

        if parsed_json and isinstance(parsed_json, dict):
            results = parsed_json.get("Results", [])
            for r in results:
                target_file = r.get("Target", target)
                for v in r.get("Vulnerabilities", []):
                    cve = {
                        "cve_id": v.get("VulnerabilityID", "UNKNOWN"),
                        "package": v.get("PkgName", ""),
                        "installed_version": v.get("InstalledVersion", ""),
                        "fixed_version": v.get("FixedVersion", ""),
                        "severity": v.get("Severity", "UNKNOWN"),
                        "title": v.get("Title", ""),
                        "target_file": target_file,
                    }
                    vulnerabilities.append(cve)
                    findings.append({
                        "type": "cve_vulnerability",
                        "severity": cve["severity"],
                        "name": f"{cve['cve_id']} ({cve['package']})",
                        "description": cve["title"],
                    })

                for s in r.get("Secrets", []):
                    sec = {
                        "rule_id": s.get("RuleID", ""),
                        "category": s.get("Category", ""),
                        "severity": s.get("Severity", "HIGH"),
                        "title": s.get("Title", ""),
                        "start_line": s.get("StartLine"),
                    }
                    secrets.append(sec)
                    findings.append({
                        "type": "exposed_secret",
                        "severity": sec["severity"],
                        "name": sec["title"],
                    })

        elif parsed_json and isinstance(parsed_json, list):
            for item in parsed_json:
                if isinstance(item, dict) and "VulnerabilityID" in item:
                    vulnerabilities.append(item)

        else:
            # Fallback regex parsing on text output
            for line in stdout.splitlines():
                cve_m = re.search(r"\b(CVE-\d{4}-\d{4,7})\b", line)
                if cve_m:
                    cve_id = cve_m.group(1)
                    vulnerabilities.append({
                        "cve_id": cve_id,
                        "raw_line": line.strip(),
                        "severity": "CRITICAL" if "CRITICAL" in line else "HIGH",
                    })

        return {
            "tool": "trivy",
            "tool_id": self.tool_id,
            "target": target,
            "exit_code": exit_code,
            "vulnerabilities": vulnerabilities,
            "secrets": secrets,
            "findings": findings,
            "total_findings": len(vulnerabilities) + len(secrets),
            "vulnerabilities_count": len(vulnerabilities),
            "secrets_count": len(secrets),
        }
