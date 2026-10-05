"""
Observer Component for Kairo.

Converts raw tool output (stdout, stderr, exit code, execution metadata)
into structured "observation" facts by reusing Task 1.3's parsers
from orchestrator.adapters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from orchestrator.adapters.registry import adapter_registry

logger = logging.getLogger("orchestrator.observer")


@dataclass
class ObservationFact:
    """
    Standardized, structured facts extracted from any tool execution.
    Provides a unified queryable schema for downstream cognitive agents (Critic, Planner).
    """
    hosts: List[str] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)
    endpoints: List[Dict[str, Any]] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    vulnerabilities: List[Dict[str, Any]] = field(default_factory=list)
    credentials: List[Dict[str, Any]] = field(default_factory=list)
    hashes: List[Dict[str, Any]] = field(default_factory=list)
    dns_records: List[Dict[str, Any]] = field(default_factory=list)
    files_extracted: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def total_facts_count(self) -> int:
        return (
            len(self.hosts)
            + len(self.ports)
            + len(self.endpoints)
            + len(self.technologies)
            + len(self.vulnerabilities)
            + len(self.credentials)
            + len(self.hashes)
            + len(self.dns_records)
            + len(self.files_extracted)
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservationResult:
    """
    High-level observation envelope containing raw adapter parse results
    plus normalized observation facts and semantic summary.
    """
    tool_id: str
    exit_code: int
    status: str  # "success" | "error" | "timeout" | "parser_error"
    summary: str
    facts: ObservationFact
    raw_observation: Dict[str, Any]
    has_findings: bool
    is_empty: bool
    parser_mismatch: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "exit_code": self.exit_code,
            "status": self.status,
            "summary": self.summary,
            "facts": self.facts.to_dict(),
            "fact_count": self.facts.total_facts_count(),
            "raw_observation": self.raw_observation,
            "has_findings": self.has_findings,
            "is_empty": self.is_empty,
            "parser_mismatch": self.parser_mismatch,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class Observer:
    """
    Observer agent: translates raw execution telemetry and stdout/stderr
    into clean, normalized, structured facts for cognitive evaluation.
    Reuses existing tool adapter parsers.
    """

    def __init__(self):
        self.registry = adapter_registry

    def observe(
        self,
        tool_id: str,
        stdout: str,
        stderr: str = "",
        exit_code: int = 0,
        meta: Optional[Dict[str, Any]] = None,
        duration_ms: float = 0.0,
    ) -> ObservationResult:
        meta = meta or {}
        adapter = self.registry.get_instance(tool_id)

        raw_observation: Dict[str, Any] = {}
        parser_mismatch = False
        parse_err_msg = None

        if adapter:
            try:
                raw_observation = adapter.parse(stdout, stderr, exit_code, meta)
                if not isinstance(raw_observation, dict):
                    raw_observation = {"result": raw_observation}
                if "parse_error" in raw_observation:
                    parser_mismatch = True
                    parse_err_msg = raw_observation.get("parse_error")
            except Exception as e:
                logger.error(f"[Observer] Adapter '{tool_id}' parse exception: {e}")
                parser_mismatch = True
                parse_err_msg = str(e)
                raw_observation = {"parse_error": str(e), "raw_stdout_sample": stdout[:1000]}
        else:
            # Generic adapter / shell / unknown tool
            raw_observation = {"tool": tool_id, "stdout": stdout[:2000], "exit_code": exit_code}

        # Normalize into structured facts
        facts = self._normalize_facts(tool_id, raw_observation, stdout, stderr, exit_code)

        # If parser mismatched or yielded zero facts from non-empty stdout, run fallback heuristic extraction
        if (parser_mismatch or facts.total_facts_count() == 0) and stdout.strip():
            fallback_facts = self._fallback_extract_facts(stdout, stderr, exit_code)
            facts = self._merge_facts(facts, fallback_facts)

        # Determine findings and emptiness
        total_facts = facts.total_facts_count()
        has_findings = total_facts > 0
        is_empty = not stdout.strip() and total_facts == 0

        # Determine overall status
        if meta.get("timed_out") or exit_code == 124:
            status = "timeout"
        elif parser_mismatch and not has_findings:
            status = "parser_error"
        elif exit_code == 0:
            status = "success"
        else:
            status = "error"

        # Build concise human summary
        summary = self._build_summary(tool_id, facts, exit_code, status, parser_mismatch)

        return ObservationResult(
            tool_id=tool_id,
            exit_code=exit_code,
            status=status,
            summary=summary,
            facts=facts,
            raw_observation=raw_observation,
            has_findings=has_findings,
            is_empty=is_empty,
            parser_mismatch=parser_mismatch,
            error=parse_err_msg or (stderr.strip() if exit_code != 0 else None),
            duration_ms=duration_ms,
        )

    def _normalize_facts(
        self,
        tool_id: str,
        raw: Dict[str, Any],
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> ObservationFact:
        facts = ObservationFact()

        # Nmap Adapter
        if "nmap" in tool_id:
            hosts = raw.get("hosts", [])
            for h in hosts:
                addr = h.get("ip") or h.get("address") or h.get("host") or h.get("hostname")
                if addr and addr not in facts.hosts:
                    facts.hosts.append(addr)
                for p in h.get("ports", []):
                    facts.ports.append({
                        "port": p.get("port"),
                        "protocol": p.get("protocol", "tcp"),
                        "state": p.get("state", "open"),
                        "service": p.get("service", "unknown"),
                        "version": p.get("version", ""),
                        "product": p.get("product", ""),
                    })
                    if p.get("product"):
                        tech_label = f"{p.get('product')} {p.get('version', '')}".strip()
                        if tech_label not in facts.technologies:
                            facts.technologies.append(tech_label)

        # Gobuster Adapter
        elif "gobuster" in tool_id:
            findings = raw.get("findings", [])
            for f in findings:
                facts.endpoints.append({
                    "path": f.get("path"),
                    "status": f.get("status"),
                    "size": f.get("size"),
                    "redirect": f.get("redirect", ""),
                })
            if raw.get("target_url") and raw.get("target_url") not in facts.hosts:
                facts.hosts.append(raw.get("target_url"))

        # Ffuf Adapter
        elif "ffuf" in tool_id:
            results = raw.get("results", [])
            for r in results:
                inp = r.get("input", {})
                path = inp.get("FUZZ", "") if isinstance(inp, dict) else str(inp or "")
                facts.endpoints.append({
                    "url": r.get("url"),
                    "path": path,
                    "status": r.get("status"),
                    "words": r.get("words"),
                    "length": r.get("length"),
                })

        # Nikto Adapter
        elif "nikto" in tool_id:
            if raw.get("ip"):
                facts.hosts.append(raw["ip"])
            srv = raw.get("server") or raw.get("server_info", {}).get("server")
            if srv and srv not in facts.technologies:
                facts.technologies.append(srv)
            for v in raw.get("vulnerabilities", []) or raw.get("findings", []):
                facts.vulnerabilities.append({
                    "id": v.get("osvdb") or v.get("id") or "NIKTO-FINDING",
                    "type": "web_vulnerability",
                    "severity": "MEDIUM",
                    "description": v.get("description", ""),
                    "uri": v.get("uri", ""),
                    "method": v.get("method", "GET"),
                })

        # WhatWeb Adapter
        elif "whatweb" in tool_id:
            for p in raw.get("plugins_found", []):
                name = p.get("name", "")
                ver = p.get("version", "")
                tech = f"{name} {ver}".strip() if ver else name
                if tech and tech not in facts.technologies:
                    facts.technologies.append(tech)
            for t in raw.get("targets", []):
                if t.get("target") and t.get("target") not in facts.hosts:
                    facts.hosts.append(t["target"])
                if t.get("http_status"):
                    facts.endpoints.append({"target": t.get("target"), "status": t.get("http_status")})
                for p in t.get("plugins", []):
                    name = p.get("name", "")
                    ver = p.get("version", "")
                    tech = f"{name} {ver}".strip() if ver else name
                    if tech and tech not in facts.technologies:
                        facts.technologies.append(tech)

        # SqlMap Adapter
        elif "sqlmap" in tool_id:
            dbms = raw.get("dbms")
            if not dbms:
                m_db = re.search(r"(?:the\s+)?back-end DBMS(?:\s+is|:)\s+(.+)", stdout, re.I)
                if m_db:
                    dbms = m_db.group(1).strip()
            if dbms and f"DBMS: {dbms}" not in facts.technologies:
                facts.technologies.append(f"DBMS: {dbms}")
            for pt in raw.get("injection_points", []):
                facts.vulnerabilities.append({
                    "id": "SQLI",
                    "type": "sql_injection",
                    "severity": "CRITICAL",
                    "parameter": pt.get("parameter"),
                    "technique": pt.get("technique"),
                    "payload": pt.get("payload"),
                })
            for db in raw.get("databases", []):
                facts.metadata[f"database_{db}"] = True

        # System Ping & Diagnostics
        elif "system_ping" in tool_id or "ping" in tool_id:
            facts.hosts.append("127.0.0.1")
            facts.metadata["system_healthy"] = True
            facts.metadata["diagnostic"] = "operational"

        # Boundary / Hello World
        elif "hello_world" in tool_id:
            facts.hosts.append(raw.get("target") or "localhost")
            facts.metadata["boundary_verified"] = True

        # Hydra Adapter
        elif "hydra" in tool_id:
            for c in raw.get("credentials", []):
                facts.credentials.append({
                    "username": c.get("login") or c.get("user"),
                    "password": c.get("password") or c.get("pass"),
                    "service": c.get("service") or raw.get("service", "unknown"),
                    "host": c.get("host") or raw.get("target", ""),
                })

        # Searchsploit Adapter
        elif "searchsploit" in tool_id:
            for exp in raw.get("exploits", raw.get("results", [])):
                facts.vulnerabilities.append({
                    "id": exp.get("edb_id") or "EDB-EXPLOIT",
                    "type": "public_exploit",
                    "title": exp.get("title", ""),
                    "path": exp.get("path", ""),
                })

        # Whois Adapter
        elif "whois" in tool_id:
            for k in ("registrar", "creation_date", "expiration_date", "org"):
                if raw.get(k):
                    facts.metadata[k] = raw[k]
            for ns in raw.get("name_servers", []):
                facts.dns_records.append({"type": "NS", "value": ns})

        # Dig Adapter
        elif "dig" in tool_id:
            for r in raw.get("records", []):
                facts.dns_records.append(r)

        # Hashid Adapter
        elif "hashid" in tool_id:
            for h in raw.get("possible_hashes", []) or raw.get("identified_types", []):
                h_name = h.get("name")
                h_mode = h.get("hashcat") or h.get("hashcat_mode")
                facts.hashes.append({"name": h_name, "hashcat_mode": h_mode})
                if h_name and h_name not in facts.technologies:
                    facts.technologies.append(h_name)

        # ExifTool Adapter
        elif "exiftool" in tool_id:
            tags = raw.get("tags", {})
            facts.metadata.update(tags)
            for f in raw.get("files", []):
                facts.metadata.update(f)
                if isinstance(f.get("all_tags"), dict):
                    facts.metadata.update(f["all_tags"])
            for sf in raw.get("sensitive_findings", []):
                facts.vulnerabilities.append({
                    "id": "SENSITIVE_METADATA",
                    "type": "information_disclosure",
                    "tag": sf.get("tag"),
                    "value": sf.get("value"),
                })

        # Metasploit Adapter
        elif "metasploit" in tool_id:
            if raw.get("session_id") or raw.get("compromised"):
                facts.vulnerabilities.append({
                    "id": "MSF_SESSION",
                    "type": "remote_shell_session",
                    "severity": "CRITICAL",
                    "session_id": raw.get("session_id"),
                })

        return facts

    def _fallback_extract_facts(self, stdout: str, stderr: str, exit_code: int) -> ObservationFact:
        """Regex/pattern extraction fallback when adapter parser misses or for raw shell executions."""
        facts = ObservationFact()
        combined = f"{stdout}\n{stderr}"

        # 1. IP addresses
        ip_matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", combined)
        for ip in ip_matches:
            if not ip.startswith("127.0.0.1") and ip not in facts.hosts:
                facts.hosts.append(ip)

        # 2. Open ports e.g. "80/tcp open http Apache httpd 2.4.41"
        port_lines = re.findall(r"(\d{1,5})/(tcp|udp)\s+open\s+([^\r\n]+)", combined, re.I)
        for p, proto, svc_info in port_lines:
            svc_parts = svc_info.strip().split()
            svc = svc_parts[0] if svc_parts else "unknown"
            version = " ".join(svc_parts[1:]) if len(svc_parts) > 1 else ""
            facts.ports.append({
                "port": int(p),
                "protocol": proto.lower(),
                "state": "open",
                "service": svc,
                "version": version,
            })
            if version and version not in facts.technologies:
                facts.technologies.append(version)

        # 3. HTTP Endpoints e.g. "/admin (Status: 200)" or "http://target/path [200]"
        endpoint_matches = re.findall(r"(?:Found:\s+)?(/[\w\-./]+)\s+\(Status:\s*(\d+)\)", combined)
        for path, code in endpoint_matches:
            facts.endpoints.append({"path": path, "status": int(code)})

        # 4. CVE identifiers
        cves = set(re.findall(r"\bCVE-\d{4}-\d{4,7}\b", combined, re.I))
        for cve in cves:
            facts.vulnerabilities.append({
                "id": cve.upper(),
                "type": "vulnerability",
                "severity": "HIGH",
            })

        # 5. Credentials e.g. "[+] [ssh] host: 192.168.1.1   login: admin   password: password123"
        cred_matches = re.findall(r"login:\s*(\S+)\s+password:\s*(\S+)", combined, re.I)
        for u, p in cred_matches:
            facts.credentials.append({"username": u, "password": p, "service": "unknown"})

        return facts

    def _merge_facts(self, primary: ObservationFact, fallback: ObservationFact) -> ObservationFact:
        """Merges fallback facts into primary without duplicates."""
        for h in fallback.hosts:
            if h not in primary.hosts:
                primary.hosts.append(h)

        existing_port_keys = {(p.get("port"), p.get("protocol")) for p in primary.ports}
        for p in fallback.ports:
            key = (p.get("port"), p.get("protocol"))
            if key not in existing_port_keys:
                primary.ports.append(p)
                existing_port_keys.add(key)

        existing_paths = {ep.get("path") for ep in primary.endpoints if ep.get("path")}
        for ep in fallback.endpoints:
            if ep.get("path") and ep["path"] not in existing_paths:
                primary.endpoints.append(ep)
                existing_paths.add(ep["path"])

        for tech in fallback.technologies:
            if tech not in primary.technologies:
                primary.technologies.append(tech)

        existing_vuln_ids = {v.get("id") for v in primary.vulnerabilities if v.get("id")}
        for v in fallback.vulnerabilities:
            if v.get("id") and v["id"] not in existing_vuln_ids:
                primary.vulnerabilities.append(v)
                existing_vuln_ids.add(v["id"])

        for c in fallback.credentials:
            if c not in primary.credentials:
                primary.credentials.append(c)

        return primary

    def _build_summary(
        self,
        tool_id: str,
        facts: ObservationFact,
        exit_code: int,
        status: str,
        parser_mismatch: bool,
    ) -> str:
        if status == "timeout":
            return f"Tool '{tool_id}' exceeded execution timeout budget."
        if parser_mismatch and facts.total_facts_count() == 0:
            return f"Tool '{tool_id}' produced output with a parser mismatch and zero recoverable facts."

        parts = []
        if facts.ports:
            port_desc = ", ".join(f"{p['port']}/{p['service']}" for p in facts.ports[:4])
            if len(facts.ports) > 4:
                port_desc += f" (+{len(facts.ports)-4} more)"
            parts.append(f"Discovered {len(facts.ports)} open port(s): {port_desc}")

        if facts.endpoints:
            parts.append(f"Discovered {len(facts.endpoints)} web endpoint(s)")

        if facts.vulnerabilities:
            vuln_ids = ", ".join(v.get("id", "VULN") for v in facts.vulnerabilities[:3])
            parts.append(f"Detected {len(facts.vulnerabilities)} vulnerability finding(s) ({vuln_ids})")

        if facts.credentials:
            parts.append(f"Recovered {len(facts.credentials)} credential pair(s)")

        if facts.technologies:
            tech_sample = ", ".join(facts.technologies[:3])
            parts.append(f"Fingerprinted technologies: {tech_sample}")

        if parts:
            return f"[{tool_id}] " + "; ".join(parts) + "."

        if exit_code == 0:
            return f"[{tool_id}] Execution succeeded but yielded 0 structured findings or targets appeared closed/inaccessible."
        return f"[{tool_id}] Execution terminated with exit code {exit_code} and 0 actionable findings."


# Global singleton
observer = Observer()
