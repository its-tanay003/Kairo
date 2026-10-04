"""
Strategic Planner Component for Autonomous Security Assessments.
Decomposes natural language security goals into Directed Acyclic Graphs (DAGs)
of abstract capabilities with explicit parallel execution branches and
multi-parent convergence nodes.
"""

import collections
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import Event, PlanDAG, PlanNode, insert_event, insert_plan, get_plan, list_plans, update_node_status, get_ready_nodes
from orchestrator.llama_client import LlamaCppClient

logger = logging.getLogger("orchestrator.planner")

PLANNER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_id": {"type": "string"},
        "goal": {"type": "string"},
        "rationale": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "capability": {"type": "string"},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "status": {
                        "type": "string",
                        "enum": ["queued", "running", "success", "warning", "failed"],
                    },
                },
                "required": ["node_id", "capability", "label", "dependencies", "status"],
            },
        },
    },
    "required": ["plan_id", "goal", "rationale", "nodes"],
}

PLANNER_SYSTEM_PROMPT = """You are Kairo's Strategic Autonomous Planner for offensive security assessments.
Given a natural language security goal, your mission is to decompose it into a Directed Acyclic Graph (DAG) of execution nodes.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. YOU MUST PRODUCE A DIRECTED ACYCLIC GRAPH (DAG), NOT A SINGLE LINEAR LIST!
   - A single linear list (like PentestGPT's ReAct loop) or a static sequential chain (like HexStrike's fixed pipeline) is STRICTLY FORBIDDEN.
   - You MUST identify independent, concurrent reconnaissance and analysis axes (e.g. network port discovery vs. web technology profiling vs. DNS enumeration) and make them root nodes with dependencies: [] so they execute in parallel.
   - You MUST define multi-parent CONVERGENCE nodes (e.g. attack surface correlation, vulnerability verification, report generation) that depend on multiple upstream branches.
2. ABSTRACT CAPABILITIES ONLY:
   - Each node MUST specify an intended abstract capability (e.g. 'network_port_scan', 'dns_subdomain_discovery', 'web_technology_fingerprint', 'web_directory_enumeration', 'vulnerability_surface_correlation', 'credential_testing', 'evidence_reporting').
   - DO NOT bind nodes to specific binary tool names (e.g. use capability 'network_port_scan', NOT tool 'nmap'). Tool selection happens later in the execution gateway.
3. GRAPH INTEGRITY:
   - The graph MUST be acyclic (no circular dependencies).
   - All items in 'dependencies' must refer to valid 'node_id's defined in the same graph.
   - Root nodes must have 'dependencies': [].

Return ONLY a valid JSON object matching the requested schema.
"""


def validate_dag(nodes: List[Any]) -> Tuple[bool, Optional[str], Dict[str, int]]:
    """
    Validates that a list of nodes forms a valid, non-empty Directed Acyclic Graph (DAG).
    Accepts either Dicts or PlanNode dataclass instances.
    Returns (is_valid, error_message, node_depths).
    """
    if not nodes:
        return False, "DAG must contain at least one node", {}

    def get_val(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    node_ids: Set[str] = set()
    for n in nodes:
        nid = get_val(n, "node_id")
        if not nid:
            return False, "Node missing required 'node_id'", {}
        if nid in node_ids:
            return False, f"Duplicate node_id detected: {nid}", {}
        node_ids.add(nid)

    # Adjacency list and in-degrees
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}

    for n in nodes:
        nid = get_val(n, "node_id")
        deps = get_val(n, "dependencies") or []
        for dep in deps:
            if dep not in node_ids:
                return False, f"Node '{nid}' references non-existent dependency '{dep}'", {}
            if dep == nid:
                return False, f"Node '{nid}' cannot depend on itself (self-cycle)", {}
            adj[dep].append(nid)
            in_degree[nid] += 1

    # Kahn's algorithm for topological sorting and cycle detection
    queue = collections.deque([nid for nid in node_ids if in_degree[nid] == 0])
    depths: Dict[str, int] = {nid: 0 for nid in queue}
    visited_count = 0

    while queue:
        curr = queue.popleft()
        visited_count += 1
        curr_depth = depths[curr]

        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            depths[neighbor] = max(depths.get(neighbor, 0), curr_depth + 1)
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(node_ids):
        return False, "Circular dependency (cycle) detected in task graph", {}

    # Check that it is not purely a trivial 1-to-1 linear list if there are >= 3 nodes
    if len(nodes) >= 3:
        roots = [n for n in nodes if not get_val(n, "dependencies")]
        convergences = [n for n in nodes if len(get_val(n, "dependencies") or []) >= 2]
        is_dag_shaped = len(roots) >= 2 or len(convergences) >= 1
        if not is_dag_shaped:
            logger.info("Graph is linear; encouraging multi-branch parallelism")

    return True, None, depths


class Planner:
    def __init__(
        self,
        llama_url: Optional[str] = None,
        db_path: Optional[Path | str] = None,
    ):
        self.llama_client = LlamaCppClient(base_url=llama_url)
        self.db_path = db_path or (ROOT_DIR / "events" / "events.db")

    def decompose(
        self,
        goal: str,
        session_id: Optional[str] = None,
        prefer_llm: bool = True,
    ) -> Dict[str, Any]:
        """
        Decomposes a natural language goal into a validated DAG plan.
        Stores the graph in the SQLite event store and records an audit event.
        """
        session_id = session_id or f"sess_plan_{uuid.uuid4().hex[:6]}"
        plan_id = f"plan_{int(time.time())}_{uuid.uuid4().hex[:4]}"

        dag_dict: Optional[Dict[str, Any]] = None

        # 1. Attempt LLM DAG generation via llama.cpp if available
        if prefer_llm and self.llama_client.is_healthy():
            try:
                dag_dict = self._generate_with_llama(goal, plan_id)
            except Exception as e:
                logger.warning(f"Llama.cpp planning failed: {e}. Falling back to domain template DAG planner.")

        # 2. Domain Template DAG Fallback (guarantees a rich DAG with parallel branches and convergence)
        if not dag_dict:
            dag_dict = self._generate_domain_dag(goal, plan_id)

        # 3. Validate DAG Properties
        nodes = dag_dict.get("nodes", [])
        is_valid, err_msg, depths = validate_dag(nodes)
        if not is_valid:
            logger.error(f"Generated DAG invalid: {err_msg}. Applying DAG repair.")
            dag_dict = self._generate_domain_dag(goal, plan_id)
            is_valid, err_msg, depths = validate_dag(dag_dict["nodes"])

        # Attach depths / execution layers for UI layout
        for n in dag_dict["nodes"]:
            n["layer"] = depths.get(n["node_id"], 0)

        # 4. Convert to PlanDAG dataclass and persist to Event Store
        plan_nodes = [
            PlanNode(
                node_id=n["node_id"],
                capability=n["capability"],
                label=n["label"],
                description=n.get("description", ""),
                dependencies=n.get("dependencies", []),
                status=n.get("status", "queued"),
            )
            for n in dag_dict["nodes"]
        ]

        plan_dag = PlanDAG(
            plan_id=plan_id,
            session_id=session_id,
            goal=goal,
            nodes=plan_nodes,
            status="queued",
            metadata={
                "rationale": dag_dict.get("rationale", ""),
                "max_depth": max(depths.values()) if depths else 0,
                "parallel_roots": len([n for n in plan_nodes if not n.dependencies]),
            },
        )

        insert_plan(plan_dag, self.db_path)

        # 5. Insert Event into SQLite Event Store
        event = Event.create(
            session_id=session_id,
            task_id=plan_id,
            actor="orchestrator:planner",
            tool_id="planner.dag.v1",
            tool_version="1.0.0",
            requested_args={"goal": goal},
            normalized_args={
                "plan_id": plan_id,
                "node_count": len(plan_nodes),
                "parallel_roots": len([n for n in plan_nodes if not n.dependencies]),
                "max_depth": max(depths.values()) if depths else 0,
            },
            result_summary=f"Decomposed goal into DAG plan '{plan_id}' with {len(plan_nodes)} capability nodes across {max(depths.values()) + 1} execution levels.",
            artifact_refs=[f"dag://{plan_id}"],
            confidence=0.98,
        )
        insert_event(event, self.db_path)

        # Retrieve saved plan with full metadata
        saved_plan = get_plan(plan_id, self.db_path)
        return saved_plan or dag_dict

    def _generate_with_llama(self, goal: str, plan_id: str) -> Dict[str, Any]:
        """Calls llama.cpp server with structured JSON schema constraint."""
        payload = {
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Decompose the following security assessment goal into a DAG of abstract capabilities:\n\nGoal: {goal}\nPlan ID: {plan_id}",
                },
            ],
            "temperature": 0.2,
            "response_format": {
                "type": "json_object",
                "schema": PLANNER_JSON_SCHEMA,
            },
        }

        url = f"{self.llama_client.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30.0) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            content_str = data["choices"][0]["message"]["content"]
            parsed = json.loads(content_str)
            parsed["plan_id"] = plan_id
            parsed["goal"] = goal
            return parsed

    def _generate_domain_dag(self, goal: str, plan_id: str) -> Dict[str, Any]:
        """
        High-capability domain DAG planner that generates multi-branch parallel DAGs
        with explicit convergence nodes for various security assessment goals.
        """
        goal_lower = goal.lower()

        # Pattern A: Web Application Assessment (Parallel Network Ports + Web Tech + DNS -> Directory Enum -> Vuln Scan -> Report)
        if any(w in goal_lower for w in ["web", "http", "api", "url", "directory", "endpoint", "injection", "owasp"]):
            return {
                "plan_id": plan_id,
                "goal": goal,
                "rationale": "Parallel execution of network discovery and web technology profiling, converging into route enumeration, vulnerability correlation, and reporting.",
                "nodes": [
                    {
                        "node_id": "node_net_ports",
                        "capability": "network_port_scan",
                        "label": "Network Port Discovery",
                        "description": "Identify open TCP/UDP service ports and active listeners on target host.",
                        "dependencies": [],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_dns_recon",
                        "capability": "dns_subdomain_discovery",
                        "label": "DNS & Domain Discovery",
                        "description": "Enumerate DNS records, virtual hosts, and subdomains.",
                        "dependencies": [],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_web_fingerprint",
                        "capability": "web_technology_fingerprint",
                        "label": "Web Technology Profiling",
                        "description": "Detect web server, reverse proxies, frameworks, CMS, and backend versions.",
                        "dependencies": ["node_net_ports"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_web_routes",
                        "capability": "web_directory_enumeration",
                        "label": "Route & Content Discovery",
                        "description": "Fuzz directory paths, administrative endpoints, and API routes.",
                        "dependencies": ["node_web_fingerprint"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_service_enum",
                        "capability": "service_fingerprinting",
                        "label": "Service Version Probing",
                        "description": "Probe service banners and versions on non-web listeners.",
                        "dependencies": ["node_net_ports"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_vuln_correlate",
                        "capability": "vulnerability_surface_correlation",
                        "label": "Attack Surface Correlation",
                        "description": "Correlate discovered web endpoints and service versions against known vulnerability databases.",
                        "dependencies": ["node_web_routes", "node_service_enum", "node_dns_recon"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_reporting",
                        "capability": "evidence_reporting",
                        "label": "Security Audit Report Synthesis",
                        "description": "Synthesize captured evidence, artifact hashes, and risk posture into final report.",
                        "dependencies": ["node_vuln_correlate"],
                        "status": "queued",
                    },
                ],
            }

        # Pattern B: Network Infrastructure & Service Assessment
        elif any(w in goal_lower for w in ["infra", "network", "host", "ip", "subnet", "ssh", "credential", "brute"]):
            return {
                "plan_id": plan_id,
                "goal": goal,
                "rationale": "Parallel host discovery and protocol analysis, followed by credential audits and evidence generation.",
                "nodes": [
                    {
                        "node_id": "node_host_discovery",
                        "capability": "host_live_detection",
                        "label": "Host Live Detection",
                        "description": "Ping and ARP sweep to verify host availability.",
                        "dependencies": [],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_osint_whois",
                        "capability": "domain_whois_lookup",
                        "label": "OSINT & Autonomous System Recon",
                        "description": "Collect registrar, ASN, and network block ownership info.",
                        "dependencies": [],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_port_scan",
                        "capability": "network_port_scan",
                        "label": "Full Port & Service Scan",
                        "description": "Scan comprehensive port range for exposed protocols.",
                        "dependencies": ["node_host_discovery"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_packet_capture",
                        "capability": "network_traffic_capture",
                        "label": "Baseline Traffic Capture",
                        "description": "Capture network baseline traffic to PCAP evidence.",
                        "dependencies": ["node_host_discovery"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_service_audit",
                        "capability": "service_fingerprinting",
                        "label": "Service Vulnerability Audit",
                        "description": "Query exploit databases for detected service versions.",
                        "dependencies": ["node_port_scan"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_cred_testing",
                        "capability": "credential_testing",
                        "label": "Weak Credential Assessment",
                        "description": "Test default and weak credentials on exposed authentication services.",
                        "dependencies": ["node_service_audit"],
                        "status": "queued",
                    },
                    {
                        "node_id": "node_final_report",
                        "capability": "evidence_reporting",
                        "label": "Infrastructure Evidence Report",
                        "description": "Compile verified attack vectors, PCAP hashes, and remediation roadmap.",
                        "dependencies": ["node_cred_testing", "node_packet_capture", "node_osint_whois"],
                        "status": "queued",
                    },
                ],
            }

        # Pattern C: General Comprehensive Assessment (Default Parallel DAG)
        return {
            "plan_id": plan_id,
            "goal": goal,
            "rationale": "Decomposed into parallel reconnaissance axes (Network and OSINT) converging into vulnerability identification and reporting.",
            "nodes": [
                {
                    "node_id": "node_net_recon",
                    "capability": "network_port_scan",
                    "label": "Network Perimeter Recon",
                    "description": "Scan and fingerprint exposed listening services.",
                    "dependencies": [],
                    "status": "queued",
                },
                {
                    "node_id": "node_osint_recon",
                    "capability": "domain_whois_lookup",
                    "label": "OSINT & DNS Enumeration",
                    "description": "Gather domain registry and DNS perimeter topology.",
                    "dependencies": [],
                    "status": "queued",
                },
                {
                    "node_id": "node_service_deep",
                    "capability": "service_fingerprinting",
                    "label": "Deep Service Enumeration",
                    "description": "Extract granular version banners and configuration headers.",
                    "dependencies": ["node_net_recon"],
                    "status": "queued",
                },
                {
                    "node_id": "node_vuln_scan",
                    "capability": "vulnerability_assessment",
                    "label": "Vulnerability Analysis",
                    "description": "Assess exposed surface against known security advisories.",
                    "dependencies": ["node_service_deep"],
                    "status": "queued",
                },
                {
                    "node_id": "node_synthesis",
                    "capability": "evidence_reporting",
                    "label": "Consolidated Security Report",
                    "description": "Synthesize all findings, artifacts, and risk posture into verified output.",
                    "dependencies": ["node_vuln_scan", "node_osint_recon"],
                    "status": "queued",
                },
            ],
        }


# Singleton instance
planner = Planner()
