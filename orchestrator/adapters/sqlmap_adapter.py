"""
SQLMap Adapter: SQL injection scanner with batch/machine-readable mode parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class SqlmapAdapter(ToolAdapter):
    tool_id = "sqlmap.scan.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "sqlmap"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        url = inputs["url"]
        method = inputs.get("method", "GET")
        data = inputs.get("data", "")
        params = inputs.get("params", "")
        level = int(inputs.get("level", 1))
        risk = int(inputs.get("risk", 1))
        dbms = inputs.get("dbms", "")
        technique = inputs.get("technique", "")
        dbs = inputs.get("dbs", False)
        tables = inputs.get("tables", False)
        extra = inputs.get("extra_args", [])

        # Always: batch mode, no color, no banner, machine-readable
        args = [
            "-u", url,
            "--batch",
            "--answers=N",          # Answer "No" to all prompts
            "--no-logging",
            "--disable-coloring",
            "--level", str(level),
            "--risk", str(risk),
            "-v", "0",              # Minimum verbosity for clean output
        ]
        if method.upper() == "POST":
            args += ["--method=POST"]
            if data:
                args += ["--data", data]
        if params:
            args += ["-p", params]
        if dbms:
            args += ["--dbms", dbms]
        if technique:
            args += ["--technique", technique]
        if dbs:
            args.append("--dbs")
        if tables:
            args.append("--tables")
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        injection_points = []
        databases = []
        tables_found = []
        injectable = False
        dbms_detected = ""
        summary = ""

        for line in stdout.splitlines():
            line_stripped = line.strip()

            # Injection detection
            if "is vulnerable" in line_stripped or "sqlmap identified" in line_stripped:
                injectable = True
            if "all tested parameters do not appear to be injectable" in line_stripped.lower():
                injectable = False

            # Injection point details
            m = re.search(r"Parameter:\s+(.+?)\s+\((\w+)\)", line_stripped)
            if m:
                injection_points.append({
                    "parameter": m.group(1),
                    "type": m.group(2),
                    "technique": "",
                    "payload": "",
                })

            # Technique detail
            m2 = re.search(r"Type:\s+(.+)", line_stripped)
            if m2 and injection_points:
                injection_points[-1]["technique"] = m2.group(1).strip()

            m3 = re.search(r"Payload:\s+(.+)", line_stripped)
            if m3 and injection_points:
                injection_points[-1]["payload"] = m3.group(1).strip()

            # DBMS detection
            m4 = re.search(r"(?:the\s+)?back-end DBMS(?:\s+is|:)\s+(.+)", line_stripped, re.I)
            if m4:
                dbms_detected = m4.group(1).strip()

            # Database enumeration
            if re.match(r"\[\*\]\s+\w", line_stripped):
                db_m = re.match(r"\[\*\]\s+(\S+)", line_stripped)
                if db_m:
                    databases.append(db_m.group(1))

            # Summary
            if line_stripped.startswith("[") and "sqlmap" in line_stripped.lower():
                summary = line_stripped

        if injectable and not injection_points:
            injection_points.append({"parameter": "unknown", "type": "injectable", "technique": "", "payload": ""})

        return {
            "tool": "sqlmap",
            "target": meta.get("inputs", {}).get("url", ""),
            "injectable": injectable,
            "injection_points": injection_points,
            "databases": databases,
            "tables": tables_found,
            "dbms": dbms_detected,
            "summary": summary,
        }
