"""
WHOIS Adapter: domain/IP lookup with key-value text parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class WhoisAdapter(ToolAdapter):
    tool_id = "whois.lookup.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "whois"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs["target"]
        server = inputs.get("server", "")
        extra = inputs.get("extra_args", [])

        args = []
        if server:
            args += ["-h", server]
        args.append(target)
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        raw_fields: Dict[str, str] = {}
        name_servers: List[str] = []
        status_list: List[str] = []
        emails: List[str] = []

        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("%") or line.startswith("#"):
                continue

            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()
                if not value:
                    continue
                raw_fields[key] = value

                if "name_server" in key or key == "nserver":
                    ns = value.split()[0].rstrip(".")
                    if ns not in name_servers:
                        name_servers.append(ns)
                elif "status" in key:
                    status_list.append(value.split()[0])
                elif re.search(r"\w+@\w+\.\w+", value):
                    emails += re.findall(r"\b[\w.+-]+@[\w.-]+\.\w+\b", value)

        return {
            "tool": "whois",
            "target": meta.get("inputs", {}).get("target", ""),
            "domain": raw_fields.get("domain_name", raw_fields.get("domain", "")),
            "registrar": raw_fields.get("registrar", ""),
            "registrant": raw_fields.get("registrant_name", raw_fields.get("registrant", "")),
            "creation_date": raw_fields.get("creation_date", raw_fields.get("created", "")),
            "expiry_date": raw_fields.get("registry_expiry_date", raw_fields.get("expires", raw_fields.get("expiry_date", ""))),
            "updated_date": raw_fields.get("updated_date", raw_fields.get("last-modified", "")),
            "name_servers": list(dict.fromkeys(name_servers)),
            "status": list(dict.fromkeys(status_list)),
            "emails": list(dict.fromkeys(emails)),
            "raw_fields": raw_fields,
        }
