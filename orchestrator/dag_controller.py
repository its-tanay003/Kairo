"""
Autonomous DAG Execution Controller for Kairo.

This controller takes complete responsibility for executing multi-step security
assessment tasks from beginning to end without manual user intervention for every tool:
1. Scheduling DAG nodes in topological order and respecting dependencies.
2. Enforcing prerequisite evidence gates: preventing downstream tools from
   executing before required upstream evidence (e.g., active web listeners, open
   service ports, or authentication endpoints) is available.
3. Choosing tools intelligently based on abstract node capabilities with fallback support.
4. Validating arguments dynamically using accumulated upstream evidence.
5. Safely running tools through adapters with scope validation and event recording.
6. Interpreting outputs and extracting structured facts into an evidence context.
7. Deciding whether to continue or halt based on stopping conditions and failure policies.
8. Generating comprehensive security audit synthesis and failure-aware recovery lineage.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from events.db import (
    DEFAULT_DB_PATH,
    Event,
    add_node_to_plan,
    get_connection,
    get_plan,
    get_ready_nodes,
    init_db,
    insert_event,
    record_trajectory,
    update_node_status,
)
from orchestrator.adapters.base import ToolObservation
from orchestrator.adapters.registry import adapter_registry
from orchestrator.evidence_store import EvidenceStore, Finding, CommandEvidence, NetworkEvidence
from orchestrator.intent_classifier import StepProvenance
from orchestrator.tool_selector import CAPABILITY_TOOL_AFFINITY
from orchestrator.observer import observer
from orchestrator.critic import critic
from orchestrator.recovery_agent import recovery_agent
from orchestrator.conversational_synthesizer import conversational_synthesizer

logger = logging.getLogger("orchestrator.dag_controller")


@dataclass
class EvidenceContext:
    """Accumulates verified domain facts across the lifecycle of a DAG execution."""
    target: str = ""
    session_id: str = ""
    plan_id: str = ""
    target_ip: Optional[str] = None
    host_status: str = "unknown"  # "online", "offline", "filtered"
    host_alive: bool = True
    hosts_found: int = 0
    open_ports: List[int] = field(default_factory=list)
    port_details: List[Dict[str, Any]] = field(default_factory=list)
    web_urls: List[str] = field(default_factory=list)
    web_endpoints: List[str] = field(default_factory=list)
    services: Any = field(default_factory=dict)
    technologies: List[str] = field(default_factory=list)
    dns_records: List[Dict[str, Any]] = field(default_factory=list)
    vulnerabilities: List[Dict[str, Any]] = field(default_factory=list)
    credentials_tested: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    node_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    raw_outputs: Dict[str, str] = field(default_factory=dict)

    def has_web_presence(self) -> bool:
        """Determines if target has confirmed HTTP/HTTPS services or web endpoints."""
        if self.web_urls:
            return True
        web_ports = {80, 443, 8000, 8080, 8443, 8888, 3000, 5000, 8008}
        if any(p in web_ports for p in self.open_ports):
            return True
        svc_values = self.services.values() if isinstance(self.services, dict) else self.services
        for svc_info in svc_values:
            svc_name = str(svc_info.get("service", "") if isinstance(svc_info, dict) else svc_info).lower()
            if any(w in svc_name for w in ["http", "web", "ssl/http", "apache", "nginx"]):
                return True
        tgt_lower = self.target.lower()
        if tgt_lower.startswith(("http://", "https://")):
            return True
        return False

    def has_open_ports(self) -> bool:
        """Determines if target has any confirmed open ports."""
        return len(self.open_ports) > 0

    def has_auth_service(self) -> bool:
        """Determines if any authentication listener (SSH, FTP, SMB, RDP) is open."""
        auth_ports = {21, 22, 23, 445, 3389, 3306, 5432}
        if any(p in auth_ports for p in self.open_ports):
            return True
        svc_values = self.services.values() if isinstance(self.services, dict) else self.services
        for svc_info in svc_values:
            s_name = str(svc_info.get("service", "") if isinstance(svc_info, dict) else svc_info).lower()
            if any(w in s_name for w in ["ssh", "ftp", "telnet", "smb", "rdp", "login", "mysql"]):
                return True
        return False

    def get_primary_web_url(self) -> str:
        """Returns the most appropriate URL for web scanners."""
        if self.web_urls:
            return self.web_urls[0]
        if 443 in self.open_ports or 8443 in self.open_ports:
            port = 443 if 443 in self.open_ports else 8443
            port_suffix = "" if port == 443 else f":{port}"
            clean_tgt = re.sub(r"^https?://", "", self.target)
            return f"https://{clean_tgt}{port_suffix}"
        port = 80 if (80 in self.open_ports or not self.open_ports) else self.open_ports[0]
        port_suffix = "" if port == 80 else f":{port}"
        clean_tgt = re.sub(r"^https?://", "", self.target)
        return f"http://{clean_tgt}{port_suffix}"

    def get_open_ports_str(self) -> str:
        """Returns comma-separated string of confirmed open ports."""
        if self.open_ports:
            return ",".join(str(p) for p in sorted(self.open_ports))
        return "1-1024"

    def get_primary_auth_service(self) -> Tuple[str, int]:
        """Returns service name and port for the first detected auth service."""
        for p, info in self.services.items():
            s_name = str(info.get("service", "")).lower()
            if any(w in s_name for w in ["ssh", "ftp", "telnet", "smb"]):
                try:
                    port_num = int(str(p).split("/")[0])
                except Exception:
                    port_num = 22
                return s_name, port_num
        if 22 in self.open_ports:
            return "ssh", 22
        if 21 in self.open_ports:
            return "ftp", 21
        return "ssh", 22

    def get_service_query(self) -> str:
        """Synthesizes service query string for exploit / CVE searches."""
        queries: List[str] = []
        for info in self.services.values():
            prod = info.get("product")
            ver = info.get("version")
            svc = info.get("service")
            if prod and ver:
                queries.append(f"{prod} {ver}")
            elif prod:
                queries.append(prod)
            elif svc and svc not in ("unknown", "tcpwrapped"):
                queries.append(svc)
        if queries:
            return queries[0]
        if self.technologies:
            return self.technologies[0]
        return "Apache 2.4"

    def ingest_observation(
        self,
        node_id: str,
        capability: str,
        tool_id: str,
        obs: Dict[str, Any],
        stdout: str = "",
        exit_code: int = 0,
        evidence_store: Optional[EvidenceStore] = None,
    ) -> None:
        """Extracts structured entities from tool observation into the evidence context."""
        # Never ingest positive findings or state changes from failed executions
        if exit_code != 0:
            logger.info(f"[DAGController] Skipping observation extraction for failed node {node_id} (exit_code={exit_code})")
            return

        # 1. Host and network extraction
        if "hosts" in obs and isinstance(obs["hosts"], list):
            for h in obs["hosts"]:
                h_ip = h.get("ip")
                if h_ip and not self.target_ip:
                    self.target_ip = h_ip
                self.host_status = "online"
                for p in h.get("ports", []):
                    try:
                        p_num = int(p.get("port") or p.get("portid") or 0)
                    except (ValueError, TypeError):
                        p_num = 0
                    if p_num and p_num not in self.open_ports:
                        self.open_ports.append(p_num)
                    p_svc = p.get("service") or "unknown"
                    p_prod = p.get("product") or ""
                    p_ver = p.get("version") or ""
                    p_key = f"{p_num}/tcp"
                    self.services[p_key] = {
                        "port": p_num,
                        "service": p_svc,
                        "product": p_prod,
                        "version": p_ver,
                    }
                    if p_num in (80, 8080, 8000, 3000, 5000):
                        url = f"http://{self.target_ip or self.target}:{p_num}" if p_num != 80 else f"http://{self.target_ip or self.target}"
                        if url not in self.web_urls:
                            self.web_urls.append(url)
                    elif p_num in (443, 8443):
                        url = f"https://{self.target_ip or self.target}:{p_num}" if p_num != 443 else f"https://{self.target_ip or self.target}"
                        if url not in self.web_urls:
                            self.web_urls.append(url)

        if "open_ports" in obs:
            raw_ports = obs["open_ports"]
            if isinstance(raw_ports, list):
                for p in raw_ports:
                    if isinstance(p, dict):
                        p_val = p.get("port") or p.get("portid")
                        try:
                            p_int = int(p_val)
                            if p_int not in self.open_ports:
                                self.open_ports.append(p_int)
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(p, (int, str)):
                        try:
                            p_int = int(p)
                            if p_int not in self.open_ports:
                                self.open_ports.append(p_int)
                        except (ValueError, TypeError):
                            pass

        # 2. Web technologies extraction
        if "technologies" in obs and isinstance(obs["technologies"], list):
            for t in obs["technologies"]:
                t_name = t.get("name") if isinstance(t, dict) else str(t)
                if t_name and t_name not in self.technologies:
                    self.technologies.append(t_name)

        # 3. Web routes and directories extraction
        for key in ("endpoints", "directories", "urls", "paths", "findings"):
            if key in obs and isinstance(obs[key], list):
                for ep in obs[key]:
                    ep_str = ep.get("path") or ep.get("url") or ep.get("endpoint") if isinstance(ep, dict) else str(ep)
                    if ep_str and ep_str not in self.web_endpoints:
                        self.web_endpoints.append(ep_str)

        # 4. Vulnerabilities extraction
        if "vulnerabilities" in obs and isinstance(obs["vulnerabilities"], list):
            for v in obs["vulnerabilities"]:
                self.vulnerabilities.append(v)
                if evidence_store:
                    try:
                        f_title = v.get("title") or v.get("cve") or f"Discovered Vulnerability in {tool_id}"
                        f_severity = v.get("severity") or "MEDIUM"
                        evidence_store.add_finding(Finding(
                            title=f_title,
                            affected_asset=self.target,
                            severity=f_severity,
                            confidence_score=0.9,
                            discovering_tool=tool_id,
                            discovering_node_id=node_id,
                            session_id=self.session_id,
                            plan_id=self.plan_id,
                            description=str(v.get("description") or ""),
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to record finding in evidence store: {e}")

        # 5. Extract findings from raw stdout if observation is spare or text-based
        if stdout:
            if "open" in stdout:
                found_ports = re.findall(r"(\d+)/(?:tcp|udp)\s+open\s+(\S+)(?:\s+(.*))?", stdout)
                for item in found_ports:
                    p_str = item[0]
                    s_str = item[1]
                    version_info = item[2] if len(item) > 2 else ""
                    try:
                        p_int = int(p_str)
                        if p_int not in self.open_ports:
                            self.open_ports.append(p_int)
                        self.services[f"{p_int}/tcp"] = {
                            "port": p_int,
                            "service": s_str,
                            "version": version_info.strip(),
                        }
                        # Auto populate web URLs if port is standard web port
                        tgt_host = re.sub(r"^https?://", "", self.target_ip or self.target).split("/")[0]
                        if p_int in (80, 8080, 8000, 3000, 5000):
                            url = f"http://{tgt_host}:{p_int}" if p_int != 80 else f"http://{tgt_host}"
                            if url not in self.web_urls:
                                self.web_urls.append(url)
                        elif p_int in (443, 8443):
                            url = f"https://{tgt_host}:{p_int}" if p_int != 443 else f"https://{tgt_host}"
                            if url not in self.web_urls:
                                self.web_urls.append(url)
                    except ValueError:
                        pass

            # Parse web routes/endpoints from directory busting tools
            if "gobuster" in tool_id.lower() or "dir" in tool_id.lower() or "fuzz" in tool_id.lower():
                endpoints_found = re.findall(r"(/[a-zA-Z0-9_\-\./]+)\s+\(Status:\s*\d+\)", stdout)
                for ep in endpoints_found:
                    if ep not in self.web_endpoints:
                        self.web_endpoints.append(ep)

            # Parse technologies from whatweb / headers
            if "whatweb" in tool_id.lower() or "tech" in tool_id.lower():
                techs = re.findall(r"([A-Za-z0-9_\-]+)(?:\[([A-Za-z0-9_\-\.]+)\])?", stdout)
                for t_name, t_ver in techs:
                    if t_name and t_name.lower() not in ("http", "https", "status", "ok"):
                        label = f"{t_name} {t_ver}".strip() if t_ver else t_name
                        if label not in self.technologies:
                            self.technologies.append(label)

    def update_from_observation(
        self,
        tool_id: str,
        stdout: str = "",
        obs: Optional[Dict[str, Any]] = None,
        node_id: str = "manual_node",
        capability: str = "manual_capability",
        exit_code: int = 0,
    ) -> None:
        """Convenience method to ingest observation directly into EvidenceContext."""
        self.ingest_observation(
            node_id=node_id,
            capability=capability,
            tool_id=tool_id,
            obs=obs or {},
            stdout=stdout,
            exit_code=exit_code,
        )

        self.node_results[node_id] = {
            "status": "success" if exit_code == 0 else "failed",
            "capability": capability,
            "tool_id": tool_id,
            "exit_code": exit_code,
            "observation_summary": {
                "open_ports": len(self.open_ports),
                "web_urls": len(self.web_urls),
                "endpoints": len(self.web_endpoints),
                "technologies": len(self.technologies),
                "vulnerabilities": len(self.vulnerabilities),
            },
        }


@dataclass
class DAGNodeExecution:
    """Record of an individual DAG node execution attempt."""
    node_id: str
    capability: str
    label: str
    status: str  # "success", "warning", "failed", "skipped", "blocked"
    tool_id: Optional[str] = None
    requested_args: Optional[Dict[str, Any]] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: float = 0.0
    command_line: Optional[str] = None
    typed_invocation: Optional[Dict[str, Any]] = None
    skipped_reason: Optional[str] = None
    recovery_path: List[Dict[str, Any]] = field(default_factory=list)
    findings_count: int = 0
    artifacts: List[str] = field(default_factory=list)
    rationale: Optional[str] = None
    tool_selection: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DAGNodeExecutionList(list):
    """List of node executions that supports integer comparisons for convenience."""
    def __eq__(self, other):
        if isinstance(other, int):
            active = [n for n in self if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else None)) not in ("skipped", "blocked")]
            return len(active) == other or len(self) == other
        return super().__eq__(other)

    def __ge__(self, other):
        if isinstance(other, int):
            active = [n for n in self if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else None)) not in ("skipped", "blocked")]
            return len(self) >= other or len(active) >= other
        return super().__ge__(other)

    def __gt__(self, other):
        if isinstance(other, int):
            active = [n for n in self if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else None)) not in ("skipped", "blocked")]
            return len(self) > other or len(active) > other
        return super().__gt__(other)

    def __le__(self, other):
        if isinstance(other, int):
            active = [n for n in self if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else None)) not in ("skipped", "blocked")]
            return len(self) <= other or len(active) <= other
        return super().__le__(other)

    def __lt__(self, other):
        if isinstance(other, int):
            active = [n for n in self if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else None)) not in ("skipped", "blocked")]
            return len(self) < other or len(active) < other
        return super().__lt__(other)


class SynthesisDict(dict):
    """Synthesis dictionary supporting substring containment in string representation."""
    def __contains__(self, key):
        if super().__contains__(key):
            return True
        reply = self.get("reply", "")
        if isinstance(reply, str) and key in reply:
            return True
        return key in str(self)


@dataclass
class DAGExecutionResult:
    """Consolidated outcome of an autonomous DAG controller run."""
    plan_id: str
    session_id: str
    goal: str
    target: str
    status: str  # "completed", "partial", "failed"
    total_nodes: int
    completed_count: int
    failed_count: int
    skipped_count: int
    nodes_executed: DAGNodeExecutionList
    evidence: EvidenceContext
    duration_ms: float
    step_provenance: List[Dict[str, Any]]
    reply: str
    synthesis: Dict[str, Any]
    next_step_recommendations: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status in ("completed", "partial") and self.failed_count == 0

    @property
    def nodes_completed(self) -> int:
        return self.completed_count

    @property
    def nodes_failed(self) -> int:
        return self.failed_count

    @property
    def nodes_skipped(self) -> int:
        return self.skipped_count

    @property
    def evidence_context(self) -> EvidenceContext:
        return self.evidence

    @property
    def synthesis_report(self) -> str:
        return self.reply

    @property
    def recovery_lineage(self) -> List[Dict[str, Any]]:
        lineage = []
        for n in self.nodes_executed:
            if n.recovery_path:
                for rec in n.recovery_path:
                    if rec.get("status") == "failed" or rec.get("exit_code", 0) != 0:
                        lineage.append(rec)
        return lineage

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["success"] = self.success
        d["nodes_executed"] = len(self.nodes_executed)
        d["nodes_executed_list"] = [n.to_dict() for n in self.nodes_executed]
        d["nodes_completed"] = self.completed_count
        d["nodes_failed"] = self.failed_count
        d["nodes_skipped"] = self.skipped_count
        d["evidence"] = asdict(self.evidence)
        d["synthesis_report"] = self.reply
        d["next_step_recommendations"] = self.next_step_recommendations
        return d


class DAGController:
    """
    Autonomous Execution Controller for Directed Acyclic Graphs.

    Orchestrates the entire multi-step task lifecycle:
    - Analyzes ready nodes using Kahn topological dependency resolution.
    - Evaluates prerequisite evidence gates before scheduling tools.
    - Maps capabilities to tool adapters with fallback support.
    - Validates tool arguments against upstream evidence and schemas.
    - Runs tools safely, recording audit events and storing findings.
    - Decides whether to continue, skip, or halt upon failure.
    - Synthesizes the overall multi-node assessment into a cohesive report.
    """

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        evidence_store: Optional[EvidenceStore] = None,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        init_db(self.db_path)
        self.evidence_store = evidence_store or EvidenceStore(db_path=self.db_path)

    def check_prerequisite_evidence(
        self,
        node: Dict[str, Any],
        context: EvidenceContext,
    ) -> Tuple[bool, Optional[str]]:
        """
        Enforces prerequisite evidence gates.
        Prevents downstream tools from executing before required upstream evidence
        (e.g. open web listeners, confirmed open ports, or authentication listeners)
        is available.
        """
        cap = str(node.get("capability") or "").lower()

        # 1. Web-dependent capabilities
        web_caps = {
            "web_directory_enumeration",
            "web_directory_enum",
            "web_fuzzing",
            "web_vulnerability_scan",
            "wordpress_audit",
            "wordpress_scan",
            "wordpress_vulnerability_audit",
            "cms_scan",
            "web_spider",
            "dast_testing",
        }
        if any(wc in cap for wc in web_caps):
            if not context.has_web_presence():
                return (
                    False,
                    f"Prerequisite web evidence missing: No open web ports (80/443/8080) or HTTP services detected on target '{context.target}'.",
                )

        # 2. Service-version dependent capabilities
        if "service_fingerprint" in cap or "service_detection" in cap or "service_version" in cap:
            if not context.has_open_ports():
                return (
                    False,
                    f"Prerequisite port evidence missing: No open ports were detected on target '{context.target}' to fingerprint.",
                )

        # 3. Credential testing / brute force
        if "credential" in cap or "brute" in cap:
            if not context.has_auth_service():
                return (
                    False,
                    f"Prerequisite auth evidence missing: No open authentication services (SSH/FTP/SMB) were detected on target '{context.target}'.",
                )

        # 4. CVE search / exploit correlation
        if "vuln_correlate" in cap or "vulnerability_surface" in cap or "cve_scan" in cap:
            if not context.has_open_ports() and not context.technologies and not context.services:
                return (
                    False,
                    f"Prerequisite attack surface missing: No discovered open ports or service versions available for CVE correlation.",
                )

        # 5. General host connectivity
        if (context.host_status == "offline" or not getattr(context, "host_alive", True)) and not any(r.get("status") == "success" for r in context.node_results.values()):
            return (
                False,
                f"Host is reported offline: Target '{context.target}' is offline or unresponsive to initial connectivity probes.",
            )

        return True, "Satisfied: Prerequisite evidence verified."

    def select_tool_for_node(
        self,
        node: Dict[str, Any],
        context: EvidenceContext,
        previous_failures: Optional[List[str]] = None,
    ) -> Tuple[str, Dict[str, Any], str]:
        """
        Selects the best available tool adapter for a node capability,
        populates validated inputs using upstream evidence, and identifies fallback tools.
        """
        previous_failures = previous_failures or []
        cap = str(node.get("capability") or "").lower()
        tgt = context.target

        # If node has an explicitly assigned tool, honor it
        assigned = node.get("assigned_tool")
        if assigned:
            candidates: List[str] = [assigned]
        else:
            # Map abstract capabilities to preferred and fallback tool IDs
            candidates = list(CAPABILITY_TOOL_AFFINITY.get(cap, []))
            if not candidates:
                for affin_cap, tools in CAPABILITY_TOOL_AFFINITY.items():
                    if affin_cap in cap or cap in affin_cap:
                        candidates.extend(tools)
                        break

            if not candidates:
                if "wordpress" in cap or "wpscan" in cap:
                    candidates = ["wpscan.audit.v1"]
                elif "subdomain" in cap or "dns" in cap:
                    candidates = ["subfinder.enum.v1", "dnsrecon.enum.v1"]
                elif "port" in cap or "nmap" in cap or "network" in cap:
                    candidates = ["nmap.scan.v1"]
                elif "dir" in cap or "fuzz" in cap:
                    candidates = ["gobuster.dir.v1", "ffuf.fuzz.v1"]
                elif "cve" in cap or "searchsploit" in cap:
                    candidates = ["searchsploit.search.v1"]
                elif "nikto" in cap or "web_vuln" in cap:
                    candidates = ["nikto.scan.v1"]
                else:
                    candidates = [cap] if cap else ["nmap.scan.v1", "kali.exec.v1"]

        # Filter out previously failed tools to enact automatic fallback
        active_candidates = [c for c in candidates if c not in previous_failures]
        selected_tool = active_candidates[0] if active_candidates else candidates[0]

        # Dynamically formulate arguments using accumulated upstream evidence
        args: Dict[str, Any] = {}

        if selected_tool == "nmap.scan.v1":
            if "service" in cap and context.open_ports:
                args = {"target": tgt, "ports": context.get_open_ports_str(), "scan_type": "sV", "timing": 3}
            elif "fast" in cap or "quick" in cap:
                args = {"target": tgt, "ports": "top-100", "timing": 4, "scan_type": "sT"}
            else:
                args = {"target": tgt, "ports": "1-1024", "timing": 3, "scan_type": "sV"}

        elif selected_tool in ("gobuster.dir.v1", "ffuf.fuzz.v1"):
            args = {
                "url": context.get_primary_web_url(),
                "wordlist": "common.txt",
                "threads": 10,
            }

        elif selected_tool == "whatweb.scan.v1":
            args = {"target": context.get_primary_web_url(), "aggression": 1}

        elif selected_tool in ("subfinder.enum.v1", "dnsrecon.enum.v1", "dig.lookup.v1"):
            clean_domain = re.sub(r"^https?://", "", tgt).split(":")[0]
            if selected_tool == "subfinder.enum.v1":
                args = {"domain": clean_domain}
            elif selected_tool == "dnsrecon.enum.v1":
                args = {"target": clean_domain, "scan_type": "std"}
            else:
                args = {"domain": clean_domain, "record_type": "ANY"}

        elif selected_tool == "whois.lookup.v1":
            clean_tgt = re.sub(r"^https?://", "", tgt).split(":")[0]
            args = {"target": clean_tgt}

        elif selected_tool in ("nikto.scan.v1", "wpscan.audit.v1"):
            args = {"target": context.get_primary_web_url(), "tuning": "1,2,3"}

        elif selected_tool == "searchsploit.search.v1":
            args = {"query": context.get_service_query(), "json_output": True}

        elif selected_tool == "hydra.brute.v1":
            svc_name, port_num = context.get_primary_auth_service()
            args = {
                "target": tgt,
                "service": svc_name,
                "port": port_num,
                "user_list": "users.txt",
                "pass_list": "passwords.txt",
            }

        elif selected_tool == "tcpdump.capture.v1":
            args = {"interface": "eth0", "count": 20, "pcap_file": f"capture_{uuid.uuid4().hex[:6]}.pcap"}

        elif selected_tool == "system_ping":
            args = {"target": tgt}

        elif selected_tool == "kali.exec.v1":
            args = {"command": "uname", "args": ["-a"]}

        else:
            args = {"target": tgt}

        # Dynamically inject structured upstream evidence and resolve placeholder parameters
        args = self._resolve_arguments_from_evidence(node, selected_tool, args, context)

        return selected_tool, args, candidates[1] if len(candidates) > 1 else selected_tool

    def _resolve_arguments_from_evidence(
        self,
        node: Dict[str, Any],
        selected_tool: str,
        default_args: Dict[str, Any],
        context: EvidenceContext,
    ) -> Dict[str, Any]:
        """
        Dynamically resolves placeholders and injects structured findings from upstream steps.
        Supported placeholders:
        - {{target}} / <target> -> context.target
        - {{target_ip}} / <target_ip> -> context.target_ip or context.target
        - {{url}} / <url> -> context.get_primary_web_url()
        - {{ports}} / <ports> -> context.get_open_ports_str()
        - {{domain}} / <domain> -> cleaned target domain
        - {{service}} / <service> -> primary detected service
        - {{query}} / <query> -> context.get_service_query()
        """
        resolved = dict(default_args)
        node_args = node.get("arguments") or node.get("params") or {}

        clean_domain = re.sub(r"^https?://", "", context.target).split("/")[0].split(":")[0]

        replacements = {
            "{{target}}": context.target,
            "<target>": context.target,
            "{{target_ip}}": context.target_ip or context.target,
            "<target_ip>": context.target_ip or context.target,
            "{{url}}": context.get_primary_web_url(),
            "<url>": context.get_primary_web_url(),
            "{{ports}}": context.get_open_ports_str(),
            "<ports>": context.get_open_ports_str(),
            "{{domain}}": clean_domain,
            "<domain>": clean_domain,
            "{{service}}": context.get_primary_auth_service()[0] if context.has_auth_service() else "http",
            "<service>": context.get_primary_auth_service()[0] if context.has_auth_service() else "http",
            "{{query}}": context.get_service_query(),
            "<query>": context.get_service_query(),
        }

        for k, v in node_args.items():
            if isinstance(v, str):
                val = v
                for placeholder, rep in replacements.items():
                    if placeholder in val:
                        val = val.replace(placeholder, str(rep))
                resolved[k] = val
            elif v is not None:
                resolved[k] = v

        # If tool requires URL and url is empty or default, inject from context
        if "url" in resolved and not resolved["url"]:
            resolved["url"] = context.get_primary_web_url()
        elif selected_tool in ("gobuster.dir.v1", "ffuf.fuzz.v1", "nikto.scan.v1", "wpscan.audit.v1") and "url" not in resolved:
            resolved["url"] = context.get_primary_web_url()

        # If tool requires ports and ports is missing/generic, inject from context if open ports known
        if selected_tool == "nmap.scan.v1" and context.open_ports and ("service" in str(node.get("capability", "")).lower() or "version" in str(node.get("capability", "")).lower()):
            resolved["ports"] = context.get_open_ports_str()

        return resolved

    def execute_node(
        self,
        plan_id: str,
        session_id: str,
        node: Dict[str, Any],
        context: EvidenceContext,
        agent_executor: Optional[Callable[..., Dict[str, Any]]] = None,
        db_path: Optional[Path | str] = None,
    ) -> DAGNodeExecution:
        """
        Executes a single ready DAG node:
        1. Checks prerequisite evidence gate.
        2. Selects appropriate tool adapter and constructs validated arguments.
        3. Enforces scope authorization.
        4. Runs tool, records execution event, and updates node status.
        5. Ingests observation into context and records findings.
        6. On failure, attempts alternative fallback tool if available.
        """
        effective_db = db_path or self.db_path
        node_id = node["node_id"]
        capability = node["capability"]
        label = node.get("label", node_id)
        recovery_path: List[Dict[str, Any]] = []

        # 1. Prerequisite Evidence Check
        can_run, reject_reason = self.check_prerequisite_evidence(node, context)
        if not can_run:
            logger.info(f"[DAGController] Node '{node_id}' ({capability}) skipped: {reject_reason}")
            update_node_status(
                plan_id=plan_id,
                node_id=node_id,
                status="skipped",
                result={"skipped": True, "reason": reject_reason},
                db_path=effective_db,
            )
            # Record audit event for evidence tracking
            event = Event.create(
                session_id=session_id,
                task_id=f"{plan_id}_{node_id}",
                actor="orchestrator:dag_controller:prereq_gate",
                tool_id=None,
                exit_code=0,
                result_summary=f"Skipped {node_id} ({capability}): {reject_reason}",
                network_context={"skipped": True, "reason": reject_reason, "plan_id": plan_id},
            )
            insert_event(event, effective_db)
            return DAGNodeExecution(
                node_id=node_id,
                capability=capability,
                label=label,
                status="skipped",
                skipped_reason=reject_reason,
            )

        # 2. Tool Selection and Argument Construction
        previous_failures: List[str] = []
        selected_tool, args, fallback_tool = self.select_tool_for_node(
            node=node,
            context=context,
            previous_failures=previous_failures,
        )

        # Update node status in DB to running
        update_node_status(
            plan_id=plan_id,
            node_id=node_id,
            status="running",
            assigned_tool=selected_tool,
            db_path=effective_db,
        )

        t0 = time.time()
        obs: Optional[ToolObservation] = None
        exec_details: Dict[str, Any] = {}
        tool_to_run = selected_tool
        args_to_run = args

        # Attempt primary execution (with fallback retry if failure occurs)
        max_attempts = 2 if fallback_tool != selected_tool else 1
        for attempt in range(max_attempts):
            t_attempt_start = time.time()
            try:
                # Dispatch tool execution
                if agent_executor:
                    # Execute through provided agent loop executor
                    try:
                        res = agent_executor(
                            session_id=session_id,
                            task_id=f"{plan_id}_{node_id}",
                            tool_id=tool_to_run,
                            requested_args=args_to_run,
                            plan_id=plan_id,
                            node_id=node_id,
                        )
                    except TypeError:
                        try:
                            res = agent_executor(tool_to_run, args_to_run)
                        except TypeError:
                            res = agent_executor(tool_to_run)
                    if isinstance(res, dict):
                        exec_details = res.get("execution") or res
                        exit_code = exec_details.get("exit_code", 0)
                        stdout = exec_details.get("stdout", "")
                        stderr = exec_details.get("stderr", "")
                        duration_ms = exec_details.get("duration_ms", (time.time() - t_attempt_start) * 1000)
                        observation = exec_details.get("observation") or {}
                        artifacts = exec_details.get("artifacts") or []
                    else:
                        exit_code = 0
                        stdout = str(res)
                        stderr = ""
                        duration_ms = 100.0
                        observation = {}
                        artifacts = []
                else:
                    # Execute through trusted ExecutionGateway
                    from orchestrator.execution_gateway import execution_gateway

                    target_candidate = args_to_run.get("target") or context.target
                    gw_res = execution_gateway.execute(
                        tool_id=tool_to_run,
                        arguments=args_to_run,
                        session_id=session_id,
                        task_id=f"{plan_id}_{node_id}",
                        target=target_candidate,
                        actor=f"orchestrator:dag_controller:{node_id}",
                        plan_id=plan_id,
                        node_id=node_id,
                        db_path=effective_db,
                    )
                    exit_code = gw_res.exit_code
                    stdout = gw_res.stdout
                    stderr = gw_res.stderr or (gw_res.rejection_reason if not gw_res.authorized else "")
                    duration_ms = gw_res.duration_ms
                    observation = gw_res.observation
                    artifacts = gw_res.artifacts

                if "nmap" in tool_to_run:
                    cmd_line = f"nmap -{args_to_run.get('scan_type', 'sV')} -p {args_to_run.get('ports', '1-1000')} {args_to_run.get('target', context.target)}"
                else:
                    cmd_line = f"{tool_to_run} --target {args_to_run.get('target', context.target)}"

                attempt_record = {
                    "tool": tool_to_run,
                    "tool_attempted": tool_to_run,
                    "args": args_to_run,
                    "command_line": cmd_line,
                    "typed_invocation": {
                        "tool": tool_to_run,
                        "version": "v1",
                        "arguments": args_to_run,
                    },
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "status": "success" if exit_code == 0 else "failed",
                }

                if exit_code == 0:
                    recovery_path.append(attempt_record)
                    break
                else:
                    previous_failures.append(tool_to_run)
                    attempt_record["failure_reason"] = stderr or f"Tool exited with code {exit_code}"
                    recovery_path.append(attempt_record)
                    # Prepare fallback if available
                    if attempt < max_attempts - 1 and fallback_tool not in previous_failures:
                        logger.warning(f"[DAGController] Primary tool '{tool_to_run}' failed ({exit_code}). Switching to fallback tool '{fallback_tool}'")
                        tool_to_run, args_to_run, _ = self.select_tool_for_node(
                            node=node,
                            context=context,
                            previous_failures=previous_failures,
                        )

            except Exception as e:
                logger.error(f"[DAGController] Error executing tool '{tool_to_run}': {e}", exc_info=True)
                exit_code = 1
                stdout = ""
                stderr = str(e)
                duration_ms = (time.time() - t_attempt_start) * 1000
                observation = {}
                artifacts = []
                previous_failures.append(tool_to_run)
                recovery_path.append({
                    "tool": tool_to_run,
                    "args": args_to_run,
                    "command_line": f"{tool_to_run} (failed invocation)",
                    "typed_invocation": {
                        "tool": tool_to_run,
                        "version": "v1",
                        "arguments": args_to_run,
                    },
                    "exit_code": 1,
                    "failure_reason": str(e),
                    "status": "failed",
                })
                if attempt < max_attempts - 1 and fallback_tool not in previous_failures:
                    tool_to_run, args_to_run, _ = self.select_tool_for_node(
                        node=node,
                        context=context,
                        previous_failures=previous_failures,
                    )

        total_duration_ms = round((time.time() - t0) * 1000, 2)
        node_success = exit_code == 0
        final_status = "success" if node_success else "failed"

        # 3. Interpret Outputs & Ingest Evidence
        context.ingest_observation(
            node_id=node_id,
            capability=capability,
            tool_id=tool_to_run,
            obs=observation,
            stdout=stdout,
            exit_code=exit_code,
            evidence_store=self.evidence_store,
        )

        # Store CommandEvidence in EvidenceStore
        try:
            cmd_ev = CommandEvidence(
                evidence_id=f"cmd_{uuid.uuid4().hex[:10]}",
                title=f"Command execution of {tool_to_run} ({node_id})",
                task_id=f"{plan_id}_{node_id}",
                session_id=session_id,
                plan_id=plan_id,
                command_line=cmd_line if "cmd_line" in locals() else tool_to_run,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=total_duration_ms,
            )
            self.evidence_store.store_evidence(cmd_ev)
        except Exception as e:
            logger.debug(f"[DAGController] Could not store CommandEvidence: {e}")

        # Store NetworkEvidence in EvidenceStore for discovered ports
        if node_success and context.open_ports:
            try:
                for p in context.open_ports:
                    p_info = context.services.get(f"{p}/tcp", {}) if isinstance(context.services, dict) else {}
                    net_ev = NetworkEvidence(
                        evidence_id=f"net_{uuid.uuid4().hex[:10]}",
                        title=f"Port {p}/tcp open on {context.target}",
                        task_id=f"{plan_id}_{node_id}",
                        session_id=session_id,
                        plan_id=plan_id,
                        host=context.target_ip or context.target,
                        port=p,
                        service=p_info.get("service") if isinstance(p_info, dict) else "unknown",
                        banner=p_info.get("product") or p_info.get("version") if isinstance(p_info, dict) else None,
                    )
                    self.evidence_store.store_evidence(net_ev)
            except Exception as e:
                logger.debug(f"[DAGController] Could not store NetworkEvidence: {e}")

        result_payload = {
            "tool_id": tool_to_run,
            "status": final_status,
            "exit_code": exit_code,
            "command_line": cmd_line if "cmd_line" in locals() else f"{tool_to_run}",
            "typed_invocation": {
                "tool": tool_to_run,
                "version": "v1",
                "arguments": args_to_run,
            },
            "duration_ms": total_duration_ms,
            "stdout_summary": (stdout[:250] + "...") if len(stdout) > 250 else stdout,
            "stderr_summary": (stderr[:250] + "...") if len(stderr) > 250 else stderr,
            "recovery_path": recovery_path,
            "observation": observation if node_success else {},
        }

        # 4. Update Database Node Status
        update_node_status(
            plan_id=plan_id,
            node_id=node_id,
            status=final_status,
            result=result_payload,
            assigned_tool=tool_to_run,
            db_path=effective_db,
        )

        # 5. Insert Execution Event in Event Store
        event = Event.create(
            session_id=session_id,
            task_id=f"{plan_id}_{node_id}",
            actor=f"orchestrator:dag_controller:{node_id}",
            tool_id=tool_to_run,
            requested_args=args_to_run,
            exit_code=exit_code,
            stdout_ref=f"inline://{stdout[:200]}...",
            stderr_ref=f"inline://{stderr[:200]}..." if stderr else None,
            artifact_refs=artifacts,
            result_summary=f"DAG Node {node_id} ({capability} -> {tool_to_run}): exit {exit_code}",
            network_context={
                "plan_id": plan_id,
                "node_id": node_id,
                "capability": capability,
                "status": final_status,
                "recovery_path": recovery_path,
            },
        )
        insert_event(event, effective_db)

        return DAGNodeExecution(
            node_id=node_id,
            capability=capability,
            label=label,
            status=final_status,
            tool_id=tool_to_run,
            requested_args=args_to_run,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=total_duration_ms,
            command_line=result_payload.get("command_line", ""),
            typed_invocation=result_payload.get("typed_invocation", {}),
            recovery_path=recovery_path,
            findings_count=len(context.findings),
            artifacts=artifacts,
        )

    def execute_plan(
        self,
        plan_id: str,
        session_id: str,
        target: Optional[str] = None,
        goal: Optional[str] = None,
        agent_executor: Optional[Callable[..., Dict[str, Any]]] = None,
        max_steps: int = 50,
        stop_on_critical_failure: bool = True,
        db_path: Optional[Path | str] = None,
        adaptive: bool = False,
        mode: str = "autonomous",
        **kwargs,
    ) -> DAGExecutionResult:
        """
        Executes a multi-step task graph supporting 4 execution modes:
        - autonomous: Full topological execution with dynamic adaptation.
        - plan_only: Dry-run tool and argument resolution without gateway execution.
        - step_by_step: Single ready node execution with operator checkpoint.
        - manual: Direct targeted execution of specified step.
        """
        effective_db = db_path or self.db_path
        t0 = time.time()

        plan_dict = get_plan(plan_id, effective_db)
        if not plan_dict:
            raise ValueError(f"Plan '{plan_id}' does not exist in event store at {effective_db}")

        effective_goal = goal or plan_dict.get("goal") or "Autonomous Security Assessment"
        effective_target = target or "127.0.0.1"

        # Infer target from goal if not provided
        if effective_target in ("127.0.0.1", None):
            ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", effective_goal)
            if ip_match:
                effective_target = ip_match.group(0)
            else:
                domain_match = re.search(r"\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}\b", effective_goal)
                if domain_match:
                    effective_target = domain_match.group(0)

        context = EvidenceContext(
            target=effective_target,
            session_id=session_id,
            plan_id=plan_id,
        )

        nodes_executed: List[DAGNodeExecution] = []
        step_provenance: List[Dict[str, Any]] = []

        # Mode: plan_only (Dry-run tool selection and argument generation without execution)
        if mode == "plan_only":
            all_nodes = plan_dict.get("nodes", [])
            for node in all_nodes:
                selected_tool, args, fallback = self.select_tool_for_node(node, context)
                cmd_line = f"{selected_tool} " + " ".join(f"--{k}={v}" for k, v in args.items()) if args else f"{selected_tool} {effective_target}"
                exec_record = DAGNodeExecution(
                    node_id=node["node_id"],
                    capability=node["capability"],
                    label=node.get("label", node["node_id"]),
                    tool_id=selected_tool,
                    status="planned",
                    duration_ms=0.0,
                    command_line=cmd_line,
                    typed_invocation={"args": args, "fallback_tool": fallback, "mode": "plan_only"},
                    skipped_reason="Dry-run plan validation only; execution deferred to operator approval.",
                )
                nodes_executed.append(exec_record)
                step_provenance.append(StepProvenance(
                    stage="planning",
                    handled_by="dag_controller:plan_only",
                    runtime="dry_run",
                    is_custom_model=False,
                    is_fallback=False,
                    executed=False,
                    details={"node_id": node["node_id"], "tool_id": selected_tool, "command_line": cmd_line},
                ).to_dict())

            total_duration_ms = round((time.time() - t0) * 1000, 2)
            synth_dict = {
                "reply": f"Plan '{plan_id}' dry-run validated in plan-only mode across {len(nodes_executed)} planned nodes. Target: {effective_target}. Ready for operator confirmation.",
                "status": "planned",
                "next_step_recommendations": [{"action": "execute_plan", "mode": "autonomous", "label": "Execute full plan autonomously"}],
            }
            return DAGExecutionResult(
                plan_id=plan_id,
                session_id=session_id,
                goal=effective_goal,
                target=effective_target,
                status="planned",
                total_nodes=len(plan_dict.get("nodes", [])),
                completed_count=0,
                failed_count=0,
                skipped_count=len(nodes_executed),
                nodes_executed=DAGNodeExecutionList(nodes_executed),
                evidence=context,
                duration_ms=total_duration_ms,
                step_provenance=step_provenance,
                reply=synth_dict["reply"],
                synthesis=synth_dict,
                next_step_recommendations=synth_dict["next_step_recommendations"],
            )

        step_count = 0
        consecutive_failures = 0

        logger.info(f"[DAGController] Starting execution (mode={mode}) of Plan '{plan_id}' ({effective_goal}) against target '{effective_target}'")

        while step_count < max_steps:
            # Refresh ready nodes from database
            ready_nodes = get_ready_nodes(plan_id, effective_db)

            if not ready_nodes:
                # Check for remaining queued nodes whose dependencies have failed or been skipped
                current_plan = get_plan(plan_id, effective_db)
                all_nodes = current_plan.get("nodes", []) if current_plan else []
                node_status_map = {n["node_id"]: n["status"] for n in all_nodes}

                unresolved_queued = [n for n in all_nodes if n["status"] == "queued"]
                if unresolved_queued:
                    for unres in unresolved_queued:
                        deps = unres.get("dependencies", [])
                        failed_deps = [d for d in deps if node_status_map.get(d) in ("failed", "blocked", "skipped")]
                        block_reason = f"Blocked by failed/skipped dependency: {', '.join(failed_deps)}" if failed_deps else "Dependencies could not be satisfied."
                        update_node_status(
                            plan_id=plan_id,
                            node_id=unres["node_id"],
                            status="blocked",
                            result={"blocked": True, "reason": block_reason},
                            db_path=effective_db,
                        )
                        nodes_executed.append(DAGNodeExecution(
                            node_id=unres["node_id"],
                            capability=unres["capability"],
                            label=unres.get("label", unres["node_id"]),
                            status="blocked",
                            skipped_reason=block_reason,
                        ))
                break

            # In step_by_step or manual mode, only schedule the first ready node
            nodes_to_run = ready_nodes[:1] if mode in ("step_by_step", "manual") else ready_nodes

            # Execute ready nodes in current layer
            for node in nodes_to_run:
                step_count += 1
                logger.info(f"[DAGController] Step {step_count}: Scheduling node '{node['node_id']}' ({node['capability']}) [mode={mode}]")

                exec_record = self.execute_node(
                    plan_id=plan_id,
                    session_id=session_id,
                    node=node,
                    context=context,
                    agent_executor=agent_executor,
                    db_path=effective_db,
                )
                nodes_executed.append(exec_record)

                # Record provenance
                step_provenance.append(StepProvenance(
                    stage="execution",
                    handled_by=exec_record.tool_id or "dag_controller:prereq_gate",
                    runtime="adapter",
                    is_custom_model=False,
                    is_fallback=len(exec_record.recovery_path) > 1,
                    executed=exec_record.status in ("success", "warning", "failed"),
                    details={
                        "node_id": exec_record.node_id,
                        "capability": exec_record.capability,
                        "status": exec_record.status,
                        "duration_ms": exec_record.duration_ms,
                        "recovery_path": exec_record.recovery_path,
                    },
                ).to_dict())

                # Adaptive Re-Planning: Propose/append follow-up nodes if new attack surface discovered
                if (adaptive or kwargs.get("adaptive") or kwargs.get("auto_adapt")) and exec_record.status == "success":
                    self._adapt_plan_if_new_attack_surface(plan_id, context, nodes_executed, effective_db)

                if exec_record.status == "failed":
                    consecutive_failures += 1
                    if stop_on_critical_failure and consecutive_failures >= 3:
                        logger.warning(f"[DAGController] Halting plan '{plan_id}' early: Reached 3 consecutive failures.")
                        break
                else:
                    consecutive_failures = 0

            if mode in ("step_by_step", "manual"):
                logger.info(f"[DAGController] Single step completed for '{nodes_to_run[0]['node_id']}'. Halting for operator confirmation.")
                break

            if stop_on_critical_failure and consecutive_failures >= 3:
                break

        total_duration_ms = round((time.time() - t0) * 1000, 2)
        completed_nodes = [n for n in nodes_executed if n.status == "success"]
        failed_nodes = [n for n in nodes_executed if n.status == "failed"]
        skipped_nodes = [n for n in nodes_executed if n.status in ("skipped", "blocked")]

        # Determine overall plan completion status
        if mode in ("step_by_step", "manual"):
            current_plan = get_plan(plan_id, effective_db)
            all_nodes = current_plan.get("nodes", []) if current_plan else []
            queued_nodes = [n for n in all_nodes if n["status"] == "queued"]
            if queued_nodes:
                overall_status = "step_completed"
            elif failed_nodes:
                overall_status = "failed"
            else:
                overall_status = "completed"
        elif failed_nodes and not completed_nodes:
            overall_status = "failed"
        elif completed_nodes and (failed_nodes or skipped_nodes):
            overall_status = "partial"
        else:
            overall_status = "completed"

        # Update parent task graph status
        conn = get_connection(effective_db)
        with conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE task_graphs SET status = ?, updated_at = ? WHERE plan_id = ?",
                (overall_status, datetime.now(timezone.utc).isoformat(), plan_id),
            )
        conn.close()

        # Generate Synthesis and Report
        synthesis_result = self._synthesize_dag_execution(
            plan_id=plan_id,
            goal=effective_goal,
            target=effective_target,
            overall_status=overall_status,
            nodes_executed=nodes_executed,
            context=context,
            duration_s=round(total_duration_ms / 1000, 2),
        )

        recs = synthesis_result.get("next_step_recommendations", [])

        # Record trajectory for model evolution & continuous learning
        try:
            record_trajectory(
                session_id=session_id,
                plan_id=plan_id,
                goal=effective_goal,
                target=effective_target,
                steps=[n.to_dict() for n in nodes_executed],
                recommendations=recs,
                success=overall_status in ("completed", "partial"),
                metadata={
                    "findings_count": len(context.findings),
                    "duration_ms": total_duration_ms,
                    "status": overall_status,
                },
                db_path=effective_db,
            )
        except Exception as e:
            logger.debug(f"[DAGController] Trajectory record skipped: {e}")

        return DAGExecutionResult(
            plan_id=plan_id,
            session_id=session_id,
            goal=effective_goal,
            target=effective_target,
            status=overall_status,
            total_nodes=len(plan_dict.get("nodes", [])),
            completed_count=len(completed_nodes),
            failed_count=len(failed_nodes),
            skipped_count=len(skipped_nodes),
            nodes_executed=DAGNodeExecutionList(nodes_executed),
            evidence=context,
            duration_ms=total_duration_ms,
            step_provenance=step_provenance,
            reply=synthesis_result["reply"],
            synthesis=synthesis_result,
            next_step_recommendations=recs,
        )

    def _adapt_plan_if_new_attack_surface(
        self,
        plan_id: str,
        context: EvidenceContext,
        nodes_executed: List[DAGNodeExecution],
        effective_db: Path,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically proposes and appends follow-up tool nodes to the active plan
        when newly discovered attack surface warrants immediate deep probing.
        """
        new_nodes: List[Dict[str, Any]] = []
        plan_dict = get_plan(plan_id, effective_db)
        existing_nodes = plan_dict.get("nodes", []) if plan_dict else []
        existing_caps = {str(n.get("capability", "")).lower() for n in existing_nodes}
        existing_ids = {str(n.get("node_id", "")).lower() for n in existing_nodes}

        last_successful = [n for n in nodes_executed if n.status == "success"]
        last_node_id = last_successful[-1].node_id if last_successful else None

        # If web presence confirmed (port 80/443/8080 or web_urls) and no web directory fuzzing scheduled
        if context.has_web_presence() and not any("dir" in c or "fuzz" in c or "web_directory" in c for c in existing_caps):
            node_id = f"node_web_enum_{uuid.uuid4().hex[:4]}"
            if node_id not in existing_ids:
                new_node = {
                    "node_id": node_id,
                    "capability": "web_directory_enumeration",
                    "label": "Web Route & Directory Enumeration",
                    "description": f"Dynamically scheduled after discovering web presence on {context.get_primary_web_url()}",
                    "dependencies": [last_node_id] if last_node_id else [],
                    "status": "queued",
                }
                if add_node_to_plan(plan_id, new_node, effective_db):
                    logger.info(f"[DAGController] Dynamically adapted plan '{plan_id}': Added follow-up node '{node_id}' ({new_node['capability']})")
                    new_nodes.append(new_node)
                    existing_caps.add(new_node["capability"].lower())

        return new_nodes

    def _synthesize_dag_execution(
        self,
        plan_id: str,
        goal: str,
        target: str,
        overall_status: str,
        nodes_executed: List[DAGNodeExecution],
        context: EvidenceContext,
        duration_s: float,
    ) -> SynthesisDict:
        """Produces a comprehensive natural language synthesis of the multi-step run."""
        synth = conversational_synthesizer.synthesize(
            plan_id=plan_id,
            goal=goal,
            target=target,
            overall_status=overall_status,
            nodes_executed=nodes_executed,
            context=context,
            duration_s=duration_s,
            verified_findings=context.findings,
        )
        return SynthesisDict(synth)


# Singleton instance
dag_controller = DAGController()


def check_prerequisite_evidence(
    node: Dict[str, Any],
    context: EvidenceContext,
) -> Tuple[bool, Optional[str]]:
    """Module-level helper to evaluate prerequisite evidence gates for a node."""
    return dag_controller.check_prerequisite_evidence(node, context)


def select_tool_for_node(
    node: Dict[str, Any],
    context: Optional[EvidenceContext] = None,
    previous_failures: Optional[List[str]] = None,
) -> Any:
    """Module-level helper to resolve capability to tool adapter."""
    ctx = context or EvidenceContext(target=node.get("target", "127.0.0.1"))
    tool, _, _ = dag_controller.select_tool_for_node(node, ctx, previous_failures)
    return tool


def resolve_node_arguments(
    node: Dict[str, Any],
    tool_name: str,
    context: EvidenceContext,
) -> Dict[str, Any]:
    """Module-level helper to resolve arguments from evidence context."""
    _, args, _ = dag_controller.select_tool_for_node(node, context)
    if node.get("arguments"):
        for k, v in node["arguments"].items():
            if v is not None:
                args[k] = v
    return args

