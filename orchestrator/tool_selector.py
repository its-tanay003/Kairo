"""
Hybrid Tool Selection Engine for Kairo.

Implements the multi-criteria hybrid scoring formula:
Score(tool) = 0.30 semantic_fit + 0.20 capability_coverage +
              0.15 environment_compatibility + 0.10 expected_signal +
              0.10 reliability_history + 0.05 execution_cost +
              0.10 prior_task_success.

Crucial architectural feature:
Does NOT just pick the top tool silently. Returns the full score breakdown
and raw signals for the top 3 candidates, powering the transparent "Why this tool" UI panel.
"""

import re
import json
import logging
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

import time
from registry.loader import ToolSpec, ToolRegistry
from events.db import get_tool_memory, get_events_by_session, DEFAULT_DB_PATH
from orchestrator.vm_manager import vm_manager

logger = logging.getLogger("orchestrator.tool_selector")

# Exact formula weights
WEIGHT_SEMANTIC_FIT = 0.30
WEIGHT_CAPABILITY_COVERAGE = 0.20
WEIGHT_ENVIRONMENT_COMPATIBILITY = 0.15
WEIGHT_EXPECTED_SIGNAL = 0.10
WEIGHT_RELIABILITY_HISTORY = 0.10
WEIGHT_EXECUTION_COST = 0.05
WEIGHT_PRIOR_TASK_SUCCESS = 0.10

WEIGHTS = {
    "semantic_fit": WEIGHT_SEMANTIC_FIT,
    "capability_coverage": WEIGHT_CAPABILITY_COVERAGE,
    "environment_compatibility": WEIGHT_ENVIRONMENT_COMPATIBILITY,
    "expected_signal": WEIGHT_EXPECTED_SIGNAL,
    "reliability_history": WEIGHT_RELIABILITY_HISTORY,
    "execution_cost": WEIGHT_EXECUTION_COST,
    "prior_task_success": WEIGHT_PRIOR_TASK_SUCCESS,
}

# Mapping between abstract DAG capabilities and known tool capabilities/IDs
CAPABILITY_TOOL_AFFINITY: Dict[str, List[str]] = {
    "network_port_scan": ["nmap.scan.v1", "system_ping"],
    "network_scan": ["nmap.scan.v1", "system_ping"],
    "port_scan": ["nmap.scan.v1"],
    "host_live_detection": ["system_ping", "nmap.scan.v1"],
    "service_detection": ["nmap.scan.v1", "whatweb.scan.v1"],
    "service_fingerprinting": ["whatweb.scan.v1", "nmap.scan.v1"],
    "web_technology_fingerprint": ["whatweb.scan.v1", "nikto.scan.v1"],
    "dns_subdomain_discovery": ["subfinder.enum.v1", "dnsrecon.enum.v1", "dnsenum.enum.v1", "dig.lookup.v1", "gobuster.dir.v1"],
    "subdomain_discovery": ["subfinder.enum.v1", "dnsrecon.enum.v1", "dnsenum.enum.v1"],
    "subdomain_enumeration": ["subfinder.enum.v1", "dnsrecon.enum.v1", "dnsenum.enum.v1"],
    "dns_enumeration": ["dnsrecon.enum.v1", "dnsenum.enum.v1", "dig.lookup.v1"],
    "dns_lookup": ["dig.lookup.v1", "dnsenum.enum.v1", "dnsrecon.enum.v1"],
    "zone_transfer": ["dnsrecon.enum.v1", "dig.lookup.v1"],
    "domain_whois_lookup": ["whois.lookup.v1"],
    "whois": ["whois.lookup.v1"],
    "web_directory_enum": ["gobuster.dir.v1", "ffuf.fuzz.v1"],
    "web_directory_enumeration": ["gobuster.dir.v1", "ffuf.fuzz.v1"],
    "web_enum": ["gobuster.dir.v1", "ffuf.fuzz.v1"],
    "web_fuzzing": ["ffuf.fuzz.v1", "gobuster.dir.v1"],
    "web_vulnerability_scan": ["nikto.scan.v1", "wpscan.audit.v1", "sqlmap.scan.v1"],
    "wordpress_audit": ["wpscan.audit.v1"],
    "wordpress_scan": ["wpscan.audit.v1"],
    "wordpress_vulnerability_audit": ["wpscan.audit.v1"],
    "cms_scan": ["wpscan.audit.v1", "whatweb.scan.v1"],
    "filesystem_vulnerability_scan": ["trivy.fs.v1"],
    "container_fs_scan": ["trivy.fs.v1"],
    "cve_scan": ["trivy.fs.v1", "searchsploit.search.v1", "nikto.scan.v1"],
    "vulnerability_assessment": ["nikto.scan.v1", "trivy.fs.v1", "searchsploit.search.v1"],
    "vulnerability_surface_correlation": ["searchsploit.search.v1", "metasploit.rpc.v1", "trivy.fs.v1"],
    "tls_security_audit": ["nikto.scan.v1", "nmap.scan.v1"],
    "sql_injection_test": ["sqlmap.scan.v1"],
    "sqli_audit": ["sqlmap.scan.v1"],
    "credential_testing": ["hydra.brute.v1"],
    "credential_brute_force": ["hydra.brute.v1"],
    "exploit_search": ["searchsploit.search.v1", "metasploit.rpc.v1"],
    "vulnerability_search": ["searchsploit.search.v1", "metasploit.rpc.v1"],
    "metasploit_exploit": ["metasploit.rpc.v1"],
    "network_traffic_capture": ["tcpdump.capture.v1"],
    "packet_capture": ["tcpdump.capture.v1"],
    "file_metadata_analysis": ["exiftool.extract.v1"],
    "metadata_extraction": ["exiftool.extract.v1"],
    "hash_identification": ["hashid.identify.v1"],
    "os_fingerprint": ["nmap.scan.v1", "whatweb.scan.v1"],
    "command_execution": ["kali.exec.v1", "shell.run.v1"],
    "general_execution": ["kali.exec.v1", "shell.run.v1"],
    "web_proxy": ["burpsuite.gui.v1", "zap.gui.v1"],
    "http_interception": ["burpsuite.gui.v1"],
    "packet_repeater": ["burpsuite.gui.v1"],
    "target_mapping": ["burpsuite.gui.v1", "zap.gui.v1"],
    "packet_analysis": ["wireshark.gui.v1", "tcpdump.capture.v1"],
    "traffic_dissection": ["wireshark.gui.v1"],
    "pcap_analysis": ["wireshark.gui.v1", "tcpdump.capture.v1"],
    "web_spider": ["zap.gui.v1", "gobuster.dir.v1"],
    "gui_security_tools": ["burpsuite.gui.v1", "wireshark.gui.v1", "zap.gui.v1"],
    "browser_testing": ["browser.security.v1"],
    "xss_testing": ["browser.security.v1", "ffuf.fuzz.v1"],
    "auth_flow_testing": ["browser.security.v1", "burpsuite.gui.v1"],
    "dast_testing": ["browser.security.v1", "zap.gui.v1", "nikto.scan.v1"],
    "dom_inspection": ["browser.security.v1"],
    "cookie_security": ["browser.security.v1"],
}

# Capability to Category mapping reflecting tool and security taxonomy
CAPABILITY_CATEGORY_MAP: Dict[str, str] = {
    # Network / Recon
    "network_port_scan": "recon",
    "network_scan": "recon",
    "port_scan": "recon",
    "host_live_detection": "recon",
    "service_detection": "recon",
    "service_fingerprinting": "recon",
    "os_fingerprint": "recon",
    # DNS / OSINT
    "dns_subdomain_discovery": "recon",
    "subdomain_discovery": "recon",
    "subdomain_enumeration": "recon",
    "dns_enumeration": "recon",
    "dns_lookup": "recon",
    "zone_transfer": "recon",
    "domain_whois_lookup": "recon",
    "whois": "recon",
    # Web / Web Security
    "web_directory_enum": "recon",
    "web_directory_enumeration": "recon",
    "web_enum": "recon",
    "web_fuzzing": "recon",
    "web_vulnerability_scan": "web_security",
    "wordpress_audit": "web",
    "wordpress_scan": "web",
    "wordpress_vulnerability_audit": "web",
    "cms_scan": "web",
    "web_technology_fingerprint": "recon",
    "web_proxy": "web_security",
    "http_interception": "web_security",
    "packet_repeater": "web_security",
    "target_mapping": "web_security",
    "web_spider": "web_security",
    "browser_testing": "web_security",
    "xss_testing": "web_security",
    "auth_flow_testing": "web_security",
    "dast_testing": "web_security",
    "dom_inspection": "web_security",
    "cookie_security": "web_security",
    # Exploitation & Credential Auditing
    "sql_injection_test": "exploitation",
    "sqli_audit": "exploitation",
    "credential_testing": "exploitation",
    "credential_brute_force": "exploitation",
    "password_brute_force": "exploitation",
    "metasploit_exploit": "exploitation",
    # Vulnerability & Analysis
    "exploit_search": "recon",
    "vulnerability_search": "recon",
    "vulnerability_assessment": "analysis",
    "vulnerability_surface_correlation": "analysis",
    "cve_scan": "analysis",
    "filesystem_vulnerability_scan": "analysis",
    "container_fs_scan": "analysis",
    "tls_security_audit": "recon",
    # Network Traffic & Capture
    "network_traffic_capture": "recon",
    "packet_capture": "network_analysis",
    "packet_analysis": "network_analysis",
    "traffic_dissection": "network_analysis",
    "pcap_analysis": "network_analysis",
    # Utility / Forensics
    "file_metadata_analysis": "recon",
    "metadata_extraction": "recon",
    "hash_identification": "utility",
    # Execution
    "command_execution": "execution",
    "general_execution": "execution",
    "evidence_reporting": "execution",
}

# Cross-category semantic compatibility clusters
CATEGORY_SYNONYMS: Dict[str, Set[str]] = {
    "web": {"web", "web_security", "web_app", "recon"},
    "web_security": {"web_security", "web", "web_app", "recon"},
    "web_app": {"web_app", "web", "web_security", "recon"},
    "recon": {"recon", "osint", "network", "network_recon", "network_analysis"},
    "network": {"network", "recon", "network_analysis"},
    "network_analysis": {"network_analysis", "recon", "network"},
    "exploitation": {"exploitation", "exploit", "cred_audit", "vuln_scan"},
    "analysis": {"analysis", "vuln_scan", "recon"},
    "utility": {"utility", "diagnostic"},
    "execution": {"execution", "sandbox_execution"},
}


@dataclass
class ToolCandidateScore:
    tool_id: str
    tool_name: str
    category: str
    rank: int
    total_score: float
    semantic_fit: float
    capability_coverage: float
    environment_compatibility: float
    expected_signal: float
    reliability_history: float
    execution_cost: float
    prior_task_success: float
    raw_signals: Dict[str, str]
    summary_rationale: str
    inferred_args: Dict[str, Any]

    @property
    def score_pct(self) -> int:
        return int(round(self.total_score * 100))

    @property
    def dimension_scores(self) -> List[Any]:
        dims = [
            ("semantic_fit", WEIGHTS["semantic_fit"], self.semantic_fit),
            ("capability_coverage", WEIGHTS["capability_coverage"], self.capability_coverage),
            ("environment_compatibility", WEIGHTS["environment_compatibility"], self.environment_compatibility),
            ("expected_signal", WEIGHTS["expected_signal"], self.expected_signal),
            ("reliability_history", WEIGHTS["reliability_history"], self.reliability_history),
            ("execution_cost", WEIGHTS["execution_cost"], self.execution_cost),
            ("prior_task_success", WEIGHTS["prior_task_success"], self.prior_task_success),
        ]
        res = []
        for name, weight, score in dims:
            raw = self.raw_signals.get(name, "")
            res.append(DimensionScore(
                name=name,
                weight=weight,
                weight_pct=int(weight * 100),
                score=score,
                score_pct=int(round(score * 100)),
                weighted_score=round(score * weight, 4),
                raw_signal=raw,
            ))
        return res

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "version": "1.0.0",
            "category": self.category,
            "rank": self.rank,
            "total_score": self.total_score,
            "score_pct": self.score_pct,
            "inferred_args": self.inferred_args,
            "summary_rationale": self.summary_rationale,
            "dimension_scores": [d.to_dict() if hasattr(d, "to_dict") else asdict(d) for d in self.dimension_scores],
        }


@dataclass
class DimensionScore:
    name: str
    weight: float
    weight_pct: int
    score: float
    score_pct: int
    weighted_score: float
    raw_signal: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolSelectionResult:
    selected_tool: ToolCandidateScore
    top_candidates: List[ToolCandidateScore]
    scoring_weights: Dict[str, float]
    task_goal: str
    required_capability: Optional[str]
    session_id: str
    plan_step: Optional[Dict[str, Any]] = None
    intended_capability: Optional[str] = None
    intended_category: Optional[str] = None

    @property
    def candidates(self) -> List[ToolCandidateScore]:
        return self.top_candidates

    @property
    def selection_reason(self) -> str:
        if self.selected_tool:
            return (
                f"Selected {self.selected_tool.tool_name} ({self.selected_tool.tool_id}) "
                f"with highest hybrid utility score of {self.selected_tool.total_score:.3f} "
                f"({self.selected_tool.score_pct}%)."
            )
        return "No tool selected"

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "selected_tool": self.selected_tool.to_dict() if self.selected_tool else None,
            "candidates": [c.to_dict() for c in self.top_candidates],
            "selection_reason": self.selection_reason,
            "evaluated_count": len(self.top_candidates),
            "weights_used": self.scoring_weights,
            "task_goal": self.task_goal,
            "required_capability": self.required_capability,
            "session_id": self.session_id,
        }
        if self.intended_capability:
            d["intended_capability"] = self.intended_capability
        if self.intended_category:
            d["intended_category"] = self.intended_category
        if self.plan_step:
            d["plan_step"] = self.plan_step
        return d


class HybridToolSelector:
    """Evaluates candidate tools using the hybrid scoring function with transparent breakdowns."""

    def __init__(self, registry: Optional[ToolRegistry] = None, db_path: Optional[Path | str] = None):
        if registry:
            self.registry = registry
        else:
            default_tools_dir = Path(__file__).resolve().parent.parent / "registry" / "tools"
            self.registry = ToolRegistry(default_tools_dir)
        self.db_path = db_path or DEFAULT_DB_PATH

    def select(
        self,
        goal: Optional[str] = None,
        required_capability: Optional[str] = None,
        session_id: str = "default_session",
        target_override: Optional[str] = None,
        top_k: int = 3,
        exclude: Optional[List[str]] = None,
        plan_step: Optional[Dict[str, Any]] = None,
        intended_capability: Optional[str] = None,
        intended_category: Optional[str] = None,
        planner_output: Optional[Any] = None,
        **kwargs,
    ) -> ToolSelectionResult:
        """
        Calculates scores for all registered tools and returns top_k candidates with full breakdowns.
        Incorporates the planner's output (intended capability, intended category, step details)
        as a real weighted factor in the semantic_fit dimension alongside keyword boosts.
        Supports excluding specific tool IDs (used by Recovery Agent to select alternate tools).
        """
        if goal is None:
            goal = kwargs.get("intent") or kwargs.get("message") or ""

        # Resolve plan_step from explicit arg or kwargs
        if plan_step is None:
            raw_step = kwargs.get("step") or kwargs.get("node") or kwargs.get("plan_step")
            if isinstance(raw_step, dict):
                plan_step = raw_step

        # Resolve planner_output if provided
        if planner_output is None:
            raw_planner = kwargs.get("planner_output") or kwargs.get("plan")
            if raw_planner:
                planner_output = raw_planner

        planner_rationale = ""
        step_label = ""
        step_description = ""

        # Extract step details from planner_output if plan_step wasn't directly passed
        if plan_step is None and isinstance(planner_output, dict):
            planner_rationale = planner_output.get("rationale") or ""
            nodes = planner_output.get("nodes")
            if isinstance(nodes, list) and nodes:
                req_node_id = kwargs.get("node_id")
                if req_node_id:
                    matched = next((n for n in nodes if isinstance(n, dict) and n.get("node_id") == req_node_id), None)
                    if matched:
                        plan_step = matched
                if plan_step is None:
                    matched = next((n for n in nodes if isinstance(n, dict) and n.get("status") in ("ready", "queued", "running")), nodes[0])
                    if isinstance(matched, dict):
                        plan_step = matched
            elif "capability" in planner_output:
                plan_step = planner_output
        elif isinstance(plan_step, dict):
            step_label = plan_step.get("label") or ""
            step_description = plan_step.get("description") or ""

        if plan_step and isinstance(plan_step, dict):
            step_label = step_label or plan_step.get("label") or ""
            step_description = step_description or plan_step.get("description") or ""

        # Resolve intended_capability
        if intended_capability is None:
            intended_capability = (
                kwargs.get("intended_capability")
                or (plan_step.get("capability") if plan_step else None)
                or required_capability
                or kwargs.get("capability")
            )
        if required_capability is None:
            required_capability = intended_capability

        # Resolve intended_category
        if intended_category is None:
            intended_category = (
                kwargs.get("intended_category")
                or (plan_step.get("category") if plan_step else None)
                or kwargs.get("category")
            )

        # Context text overrides if passed in kwargs
        if not step_label:
            step_label = kwargs.get("step_label") or kwargs.get("label") or ""
        if not step_description:
            step_description = kwargs.get("step_description") or kwargs.get("description") or ""
        if not planner_rationale:
            planner_rationale = kwargs.get("planner_rationale") or kwargs.get("rationale") or ""

        tools = self.registry.list_tools()
        if not tools:
            raise ValueError("No tools registered in ToolRegistry")

        if exclude:
            exclude_set = set(exclude)
            tools = [t for t in tools if t.id not in exclude_set and t.name not in exclude_set]
            if not tools:
                # If everything excluded, fallback to all tools
                tools = self.registry.list_tools()

        scored_candidates: List[ToolCandidateScore] = []

        for tool in tools:
            candidate = self._score_tool(
                tool=tool,
                goal=goal,
                required_capability=required_capability,
                session_id=session_id,
                target_override=target_override,
                intended_capability=intended_capability,
                intended_category=intended_category,
                step_label=step_label,
                step_description=step_description,
                planner_rationale=planner_rationale,
            )
            scored_candidates.append(candidate)

        # Sort descending by total score
        scored_candidates.sort(key=lambda c: c.total_score, reverse=True)

        # Assign ranks
        for idx, c in enumerate(scored_candidates, 1):
            c.rank = idx

        top_candidates = scored_candidates[:top_k]
        selected = top_candidates[0]

        return ToolSelectionResult(
            selected_tool=selected,
            top_candidates=top_candidates,
            scoring_weights=WEIGHTS,
            task_goal=goal,
            required_capability=required_capability,
            session_id=session_id,
            plan_step=plan_step,
            intended_capability=intended_capability,
            intended_category=intended_category,
        )

    def _score_tool(
        self,
        tool: ToolSpec,
        goal: str,
        required_capability: Optional[str],
        session_id: str,
        target_override: Optional[str] = None,
        intended_capability: Optional[str] = None,
        intended_category: Optional[str] = None,
        step_label: str = "",
        step_description: str = "",
        planner_rationale: str = "",
    ) -> ToolCandidateScore:
        """Calculates the 7 hybrid factors, raw signals, and total weighted score for a tool."""

        # 1. Semantic Fit (weight: 0.30)
        s_fit, raw_s_fit = self._calc_semantic_fit(
            tool=tool,
            goal=goal,
            required_capability=required_capability,
            intended_capability=intended_capability,
            intended_category=intended_category,
            step_label=step_label,
            step_description=step_description,
            planner_rationale=planner_rationale,
        )

        # 2. Capability Coverage (weight: 0.20)
        c_cov, raw_c_cov = self._calc_capability_coverage(tool, required_capability, goal)

        # 3. Environment Compatibility (weight: 0.15)
        e_comp, raw_e_comp = self._calc_environment_compatibility(tool)

        # 4. Expected Signal (weight: 0.10)
        e_sig, raw_e_sig = self._calc_expected_signal(tool)

        # 5. Reliability History (weight: 0.10)
        r_hist, raw_r_hist = self._calc_reliability_history(tool)

        # 6. Execution Cost (weight: 0.05)
        e_cost, raw_e_cost = self._calc_execution_cost(tool)

        # 7. Prior Task Success (weight: 0.10)
        p_succ, raw_p_succ = self._calc_prior_task_success(tool, session_id)

        # Compute total weighted score
        total_score = round(
            (WEIGHTS["semantic_fit"] * s_fit)
            + (WEIGHTS["capability_coverage"] * c_cov)
            + (WEIGHTS["environment_compatibility"] * e_comp)
            + (WEIGHTS["expected_signal"] * e_sig)
            + (WEIGHTS["reliability_history"] * r_hist)
            + (WEIGHTS["execution_cost"] * e_cost)
            + (WEIGHTS["prior_task_success"] * p_succ),
            4,
        )

        raw_signals = {
            "semantic_fit": f"semantic_fit: {s_fit:.2f} — {raw_s_fit}",
            "capability_coverage": f"capability_coverage: {c_cov:.2f} — {raw_c_cov}",
            "environment_compatibility": f"environment_compatibility: {e_comp:.2f} — {raw_e_comp}",
            "expected_signal": f"expected_signal: {e_sig:.2f} — {raw_e_sig}",
            "reliability_history": f"reliability_history: {r_hist:.2f} — {raw_r_hist}",
            "execution_cost": f"execution_cost: {e_cost:.2f} — {raw_e_cost}",
            "prior_task_success": f"prior_task_success: {p_succ:.2f} — {raw_p_succ}",
        }

        # Build summary rationale
        summary = (
            f"Scored {total_score:.3f} across 7 weighted dimensions. "
            f"Key strengths: {raw_s_fit.split(';')[0]} and {raw_c_cov.split(';')[0]}."
        )

        inferred_args = self._infer_arguments(tool, goal, target_override)

        return ToolCandidateScore(
            tool_id=tool.id,
            tool_name=tool.name,
            category=tool.category,
            rank=0,  # assigned post-sort
            total_score=total_score,
            semantic_fit=round(s_fit, 4),
            capability_coverage=round(c_cov, 4),
            environment_compatibility=round(e_comp, 4),
            expected_signal=round(e_sig, 4),
            reliability_history=round(r_hist, 4),
            execution_cost=round(e_cost, 4),
            prior_task_success=round(p_succ, 4),
            raw_signals=raw_signals,
            summary_rationale=summary,
            inferred_args=inferred_args,
        )

    # -------------------------------------------------------------------------
    # Factor 1: Semantic Fit (0.30)
    # -------------------------------------------------------------------------
    def _calc_semantic_fit(
        self,
        tool: ToolSpec,
        goal: str,
        required_capability: Optional[str] = None,
        intended_capability: Optional[str] = None,
        intended_category: Optional[str] = None,
        step_label: str = "",
        step_description: str = "",
        planner_rationale: str = "",
    ) -> Tuple[float, str]:
        # Broad execution penalty: heavily demote shell.run.v1 and kali.exec.v1 if goal maps to security ops
        security_ops = [
            "scan", "port", "nmap", "dns", "subdomain", "dir", "fuzz", "cve", "vuln",
            "sql", "sqli", "password", "brute", "whois", "dig", "traffic", "pcap",
            "wordpress", "wpscan", "trivy", "hash", "exif", "metadata", "burp", "wireshark", "zap"
        ]
        target_cap = (intended_capability or required_capability or "").lower()
        if tool.id in ("kali.exec.v1", "shell.run.v1"):
            if any(op in goal.lower() for op in security_ops) or any(op in target_cap for op in security_ops):
                return 0.05, "demoted: typed security tool adapter is favored for this operation"

        text_corpus = (
            f"{tool.id} {tool.name} {tool.category} {tool.description} "
            f"{' '.join(tool.capabilities)} {tool.docs.get('summary', '')} {tool.docs.get('usage', '')}"
        ).lower()

        planner_text = f"{step_label} {step_description} {planner_rationale}".strip()
        effective_cap = (intended_capability or required_capability or "").strip().lower()
        effective_cat = (intended_category or "").strip().lower()
        if not effective_cat and effective_cap:
            effective_cat = CAPABILITY_CATEGORY_MAP.get(effective_cap, "")
            if not effective_cat:
                if any(x in effective_cap for x in ["scan", "recon", "enum", "discovery", "lookup", "whois"]):
                    effective_cat = "recon"
                elif any(x in effective_cap for x in ["wordpress", "web", "http", "fuzz"]):
                    effective_cat = "web"
                elif any(x in effective_cap for x in ["exploit", "brute", "sql", "inject"]):
                    effective_cat = "exploitation"
                elif any(x in effective_cap for x in ["packet", "traffic", "pcap"]):
                    effective_cat = "network_analysis"
                elif any(x in effective_cap for x in ["cve", "vuln", "audit", "trivy"]):
                    effective_cat = "analysis"

        combined_query = f"{goal} {planner_text} {effective_cap}".strip().lower()

        # 1. Domain Vocabulary & Text Overlap (25% weight)
        query_tokens = set(re.findall(r"\w+", combined_query))
        common_words = {"the", "and", "for", "with", "target", "run", "scan", "test", "into", "from", "that", "this"}
        matched_tokens = [tok for tok in query_tokens if tok in text_corpus and len(tok) > 2 and tok not in common_words]
        overlap_score = min(len(matched_tokens) / 3.0, 1.0) if query_tokens else 0.50
        s_overlap = min(max(overlap_score, 0.20), 1.0)

        # 2. Fast Keyword Heuristic Boosts (25% weight when planner present, 55% when absent)
        keyword_boosts = 0.0
        bonus_reasons = []

        q_lower = combined_query
        if any(w in q_lower for w in ["port", "nmap", "syn", "sweep"]) and "nmap" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("port scan terms")
        if any(w in q_lower for w in ["dir", "fuzz", "endpoint", "path", "route"]) and any(
            x in tool.id for x in ["gobuster", "ffuf"]
        ):
            keyword_boosts += 0.35
            bonus_reasons.append("web fuzzing terms")
        if any(w in q_lower for w in ["cve", "exploit", "searchsploit", "vulnerability"]) and (
            "searchsploit" in tool.id or "nikto" in tool.id
        ):
            keyword_boosts += 0.35
            bonus_reasons.append("vulnerability search terms")
        if any(w in q_lower for w in ["password", "brute", "ssh", "hydra", "ftp", "login"]) and "hydra" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("credential audit terms")
        if any(w in q_lower for w in ["sql", "sqli", "injection", "database"]) and "sqlmap" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("SQL injection terms")
        if any(w in q_lower for w in ["whois", "registrar", "asn"]) and "whois" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("whois terms")
        if any(w in q_lower for w in ["dns", "dig", "record", "mx", "ns"]) and "dig" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("DNS terms")
        if any(w in q_lower for w in ["pcap", "traffic", "tcpdump", "sniff", "packet"]) and "tcpdump" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("packet capture terms")
        if any(w in q_lower for w in ["exif", "metadata", "image"]) and "exiftool" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("metadata terms")
        if any(w in q_lower for w in ["hash", "md5", "sha", "identify"]) and "hashid" in tool.id:
            keyword_boosts += 0.35
            bonus_reasons.append("hash identification terms")
        if any(w in q_lower for w in ["subfinder", "subdomain"]) and "subfinder" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("subdomain discovery terms")
        if any(w in q_lower for w in ["dnsrecon", "zone transfer", "axfr"]) and "dnsrecon" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("DNSRecon/zone transfer terms")
        if any(w in q_lower for w in ["trivy", "filesystem", "secret", "package", "cve"]) and "trivy" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("Trivy CVE/filesystem terms")
        if any(w in q_lower for w in ["wpscan", "wordpress", "wp plugin", "wp theme"]) and "wpscan" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("WPScan WordPress terms")
        if any(w in q_lower for w in ["nikto", "header", "misconfiguration", "web vuln", "missing security"]) and "nikto" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("Nikto web vulnerability terms")
        if any(w in q_lower for w in ["browser", "dom", "playwright", "cookie"]) and "browser" in tool.id:
            keyword_boosts += 0.40
            bonus_reasons.append("browser security terms")

        s_keyword = min(0.50 + keyword_boosts, 1.0) if keyword_boosts > 0 else 0.50

        # 3. Planner Decomposition Alignment (50% weight)
        cap_score = 0.50
        cap_reason = ""
        if effective_cap:
            pref_tools = CAPABILITY_TOOL_AFFINITY.get(effective_cap, [])
            if not pref_tools:
                for aff_k, aff_v in CAPABILITY_TOOL_AFFINITY.items():
                    if aff_k in effective_cap or effective_cap in aff_k:
                        pref_tools = aff_v
                        break

            if tool.id in pref_tools:
                idx = pref_tools.index(tool.id)
                cap_score = max(1.0 - (idx * 0.10), 0.70)
                cap_reason = f"affinity #{idx+1} for '{effective_cap}'"
            elif any(c.replace("_", "") == effective_cap.replace("_", "") for c in tool.capabilities):
                cap_score = 0.95
                cap_reason = f"exact match for capability '{effective_cap}'"
            elif any(effective_cap in c or c in effective_cap for c in tool.capabilities):
                cap_score = 0.85
                cap_reason = f"partial match for capability '{effective_cap}'"
            else:
                cap_toks = set(re.findall(r"\w+", effective_cap))
                tool_cap_toks = set(re.findall(r"\w+", " ".join(tool.capabilities) + " " + tool.id))
                ov = cap_toks.intersection(tool_cap_toks)
                if ov:
                    cap_score = 0.60 + min(0.30, len(ov) * 0.15)
                    cap_reason = f"shared capability tokens ({', '.join(ov)})"
                else:
                    cap_score = 0.15
                    cap_reason = f"no capability match for '{effective_cap}'"

        cat_score = 0.50
        cat_reason = ""
        if effective_cat:
            t_cat = (tool.category or "").strip().lower()
            if t_cat == effective_cat:
                cat_score = 1.00
                cat_reason = f"exact category match '{t_cat}'"
            elif t_cat in CATEGORY_SYNONYMS.get(effective_cat, set()) or effective_cat in CATEGORY_SYNONYMS.get(t_cat, set()):
                cat_score = 0.85
                cat_reason = f"compatible category '{t_cat}' ~ '{effective_cat}'"
            else:
                cat_score = 0.20
                cat_reason = f"category mismatch '{t_cat}' != '{effective_cat}'"

        ctx_score = 0.50
        if planner_text:
            step_toks = [tok for tok in re.findall(r"\w+", planner_text.lower()) if len(tok) > 2 and tok not in common_words]
            if step_toks:
                matched_step_toks = [tok for tok in step_toks if tok in text_corpus]
                ctx_score = min(max(len(matched_step_toks) / 2.0, 0.40), 1.0)

        has_planner_info = bool(effective_cap or effective_cat or planner_text)
        if has_planner_info:
            if effective_cap and effective_cat:
                s_planner = (0.50 * cap_score) + (0.30 * cat_score) + (0.20 * ctx_score)
            elif effective_cap:
                s_planner = (0.75 * cap_score) + (0.25 * ctx_score)
            elif effective_cat:
                s_planner = (0.75 * cat_score) + (0.25 * ctx_score)
            else:
                s_planner = ctx_score
            # Weighted synthesis: 50% planner fit + 25% keyword heuristic + 25% text overlap
            s_fit = (0.50 * s_planner) + (0.25 * s_keyword) + (0.25 * s_overlap)
        else:
            # Baseline when no planner context is provided (pure goal text)
            s_planner = 0.50
            s_fit = (0.45 * s_overlap) + (0.55 * s_keyword)

        score = min(max(s_fit, 0.15), 1.0)

        # Build informative rationale
        reasons_list = []
        if effective_cap and cap_reason:
            reasons_list.append(f"plan_cap:{effective_cap} ({cap_reason}) [{cap_score:.2f}]")
        if effective_cat and cat_reason:
            reasons_list.append(f"plan_cat:{effective_cat} ({cat_reason}) [{cat_score:.2f}]")
        if matched_tokens:
            reasons_list.append(f"matched {len(matched_tokens)} semantic terms ({', '.join(matched_tokens[:4])})")
        if bonus_reasons:
            reasons_list.append(f"kw_boost: {', '.join(bonus_reasons)} (+{keyword_boosts:.2f})")

        raw_str = "; ".join(reasons_list) if reasons_list else f"baseline semantic fit {score:.2f}"
        return score, raw_str

    # -------------------------------------------------------------------------
    # Factor 2: Capability Coverage (0.20)
    # -------------------------------------------------------------------------
    def _calc_capability_coverage(
        self, tool: ToolSpec, required_capability: Optional[str], goal: str
    ) -> Tuple[float, str]:
        if not required_capability:
            # Try to match capability from tool's declared capabilities against goal
            matching_caps = [c for c in tool.capabilities if c.replace("_", " ") in goal.lower()]
            if matching_caps:
                score = min(0.6 + (0.15 * len(matching_caps)), 1.0)
                return score, f"covers {len(matching_caps)} capabilities mentioned in goal ({', '.join(matching_caps)})"
            return 0.50, f"general alignment with {len(tool.capabilities)} declared capabilities"

        req_clean = required_capability.lower().strip()

        # Direct exact match
        if req_clean in tool.capabilities or req_clean.replace("_", "") in [c.replace("_", "") for c in tool.capabilities]:
            return 1.00, f"exact match for capability '{required_capability}'"

        # Check affinity table
        preferred_tools = CAPABILITY_TOOL_AFFINITY.get(req_clean, [])
        if tool.id in preferred_tools:
            idx = preferred_tools.index(tool.id)
            score = 1.0 - (idx * 0.1)
            return score, f"tool is designated primary/secondary adapter for '{required_capability}'"

        # Partial substring match
        for cap in tool.capabilities:
            if cap in req_clean or req_clean in cap:
                return 0.80, f"partial match: tool capability '{cap}' covers '{required_capability}'"

        # Category match
        if tool.category in req_clean:
            return 0.60, f"category match: tool belongs to '{tool.category}'"

        return 0.20, f"tool capabilities ({', '.join(tool.capabilities[:2])}) do not cover '{required_capability}'"

    # -------------------------------------------------------------------------
    # Factor 3: Environment Compatibility (0.15)
    # -------------------------------------------------------------------------
    def _calc_environment_compatibility(self, tool: ToolSpec) -> Tuple[float, str]:
        now = time.time()
        if not hasattr(self, "_cached_vm_stat") or (now - getattr(self, "_vm_stat_time", 0)) > 10.0:
            self._cached_vm_stat = vm_manager.get_status()
            self._vm_stat_time = now
        vm_stat = self._cached_vm_stat
        is_vm_online = vm_stat.get("worker_online", False)

        supported_os = tool.version_compatibility.get("os", ["linux"])
        is_linux_tool = "linux" in [s.lower() for s in supported_os]

        if is_linux_tool and is_vm_online:
            priv = tool.privilege or "user"
            return 1.00, f"compatible with Linux (Kali VM online), privilege '{priv}' supported, prerequisites verified"
        elif not is_linux_tool:
            return 0.85, f"cross-platform tool, runnable on host ({sys.platform})"
        else:
            # VM offline or fallback
            return 0.70, f"Kali worker offline; fallback command execution required"

    # -------------------------------------------------------------------------
    # Factor 4: Expected Signal (0.10)
    # -------------------------------------------------------------------------
    def _calc_expected_signal(self, tool: ToolSpec) -> Tuple[float, str]:
        parser_cfg = tool.parser
        if isinstance(parser_cfg, str) and parser_cfg:
            return 0.88, f"Tier 2 custom parser ({parser_cfg}) transforms raw stdout into structured schema"
        elif isinstance(parser_cfg, dict):
            is_structured = parser_cfg.get("structured", False)
            fmt = parser_cfg.get("format", "text")
            parser_type = parser_cfg.get("type", "regex")

            if fmt in ["xml", "json"] and is_structured:
                return 1.00, f"Tier 1 native structured {fmt.upper()} output parsed into typed observation records"
            elif is_structured:
                return 0.88, f"Tier 2 custom parser ({parser_type}) transforms raw stdout into structured schema"

        return 0.55, f"unstructured text stdout stream; regex extraction only"

    # -------------------------------------------------------------------------
    # Factor 5: Reliability History (0.10) - Read from Tool Memory Store
    # -------------------------------------------------------------------------
    def _calc_reliability_history(self, tool: ToolSpec) -> Tuple[float, str]:
        mem = get_tool_memory(tool.id, self.db_path)
        rel_score = float(mem.get("reliability_score", 1.0))
        tot = mem.get("total_runs", 0)
        succ = mem.get("successful_runs", 0)
        avg_ms = mem.get("avg_duration_ms", 0.0)

        if tot == 0:
            return 0.90, "no prior execution history recorded (baseline neutral prior 0.90)"

        raw = f"succeeded {succ}/{tot} prior runs (avg duration {avg_ms/1000.0:.1f}s, {mem.get('timeout_runs', 0)} timeouts)"
        return rel_score, raw

    # -------------------------------------------------------------------------
    # Factor 6: Execution Cost (0.05)
    # -------------------------------------------------------------------------
    def _calc_execution_cost(self, tool: ToolSpec) -> Tuple[float, str]:
        cat = tool.category.lower()
        timeout_ms = tool.timeout_ms or 30000

        # Passive OSINT / local parsing = very low cost
        if cat in ["osint", "reporting", "recon"] and any(x in tool.id for x in ["whois", "dig", "exiftool", "hashid"]):
            return 0.95, f"very low overhead, passive OSINT (timeout {timeout_ms//1000}s, minimal network footprint)"

        # Standard port / web recon = moderate cost
        if any(x in tool.id for x in ["nmap", "whatweb", "searchsploit", "system_ping"]):
            return 0.82, f"moderate cost, active reconnaissance probe (timeout {timeout_ms//1000}s, bounded probes)"

        # Heavy fuzzing / brute-force / active exploit = higher cost
        if any(x in tool.id for x in ["ffuf", "gobuster", "hydra", "nikto", "sqlmap", "metasploit"]):
            return 0.68, f"elevated compute & bandwidth cost (timeout {timeout_ms//1000}s, high traffic volume)"

        return 0.80, f"standard execution profile (timeout {timeout_ms//1000}s)"

    # -------------------------------------------------------------------------
    # Factor 7: Prior Task Success in Current Session (0.10)
    # -------------------------------------------------------------------------
    def _calc_prior_task_success(self, tool: ToolSpec, session_id: str) -> Tuple[float, str]:
        try:
            session_events = get_events_by_session(session_id, self.db_path)
            tool_events = [e for e in session_events if e.get("tool_id") == tool.id]

            if not tool_events:
                return 0.75, f"tool has not yet run in session '{session_id}' (neutral prior 0.75)"

            successes = [e for e in tool_events if e.get("exit_code") == 0]
            rate = len(successes) / len(tool_events)

            if rate >= 0.8:
                return 1.00, f"succeeded {len(successes)}/{len(tool_events)} times in current session '{session_id}'"
            elif rate >= 0.5:
                return 0.65, f"partial success ({len(successes)}/{len(tool_events)}) in session '{session_id}'"
            else:
                return 0.25, f"repeated failures ({len(successes)}/{len(tool_events)}) in current session '{session_id}'"
        except Exception:
            return 0.75, "session event lookup unavailable (neutral prior 0.75)"

    # -------------------------------------------------------------------------
    # Argument Inference Helper
    # -------------------------------------------------------------------------
    def _infer_arguments(self, tool: ToolSpec, goal: str, target_override: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {}

        # 1. Target extraction
        target = target_override
        if not target:
            # IP address match
            ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", goal)
            if ip_match:
                target = ip_match.group(0)
            else:
                # URL host extraction
                url_match = re.search(r"https?://([a-zA-Z0-9.-]+)", goal)
                if url_match:
                    target = url_match.group(1)
                else:
                    # Domain match (exclude common file extensions)
                    domain_match = re.search(r"\b(?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|local|internal|edu|gov|lab)\b", goal)
                    if domain_match:
                        target = domain_match.group(0)
                    else:
                        target = "127.0.0.1"

        tid = tool.id
        clean_target = target
        if target.endswith((".php", ".html", ".htm", ".asp", ".aspx", ".jsp", ".txt", ".bak")):
            clean_target = "127.0.0.1"
        host_only = clean_target.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]



        if tid == "nmap.scan.v1":
            args = {"target": host_only or "127.0.0.1", "ports": "22,80,443,8080", "scan_type": "sV", "timing": 3}
        elif tid in ["gobuster.dir.v1", "ffuf.fuzz.v1"]:
            url = f"http://{target}" if not target.startswith("http") else target
            args = {"url": url, "wordlist": "/usr/share/wordlists/dirb/common.txt"}
        elif tid == "nikto.scan.v1":
            args = {"host": host_only or "127.0.0.1", "format": "json"}
        elif tid == "whatweb.scan.v1":
            url = f"http://{target}" if not target.startswith("http") else target
            args = {"url": url, "aggression": 1}
        elif tid == "sqlmap.scan.v1":
            url = f"http://{target}/index.php?id=1" if not target.startswith("http") else target
            args = {"url": url, "batch": True, "level": 1}
        elif tid == "hydra.brute.v1":
            args = {"target": host_only or "127.0.0.1", "protocol": "ssh", "username": "admin", "wordlist": "/usr/share/wordlists/rockyou.txt"}
        elif tid == "whois.lookup.v1":
            args = {"target": target}
        elif tid == "dig.lookup.v1":
            args = {"target": target, "record_type": "A"}
        elif tid == "dnsenum.enum.v1":
            args = {"target": host_only or "target.local", "noreverse": True}
        elif tid == "searchsploit.search.v1":
            args = {"query": "Apache 2.4", "json_output": True}
        elif tid == "tcpdump.capture.v1":
            args = {"interface": "eth0", "packet_count": 50, "duration_sec": 10}
        elif tid == "exiftool.extract.v1":
            args = {"file_path": target if ("." in target and not target.startswith("http")) else "/tmp/evidence.jpg"}
        elif tid == "hashid.identify.v1":
            args = {"hash": target if len(target) >= 16 else "5f4dcc3b5aa765d61d8327deb882cf99"}
        elif tid == "metasploit.rpc.v1":
            args = {"module": "auxiliary/scanner/portscan/tcp", "rhosts": host_only or "127.0.0.1"}
        elif tid == "kali.exec.v1":
            args = {"command": "uname", "args": ["-a"]}
        elif tid == "shell.run.v1":
            args = {"command": f"ping -c 2 {host_only or '127.0.0.1'}"}
        elif tid == "system_ping":
            args = {"target": host_only or "127.0.0.1", "count": 3}
        elif tid == "zap.gui.v1":
            target_url = target if target.startswith("http") else f"http://{target}"
            gl = goal.lower()
            if any(w in gl for w in ["report", "compliance", "export"]):
                wf = "export_report"
            elif any(w in gl for w in ["spider", "crawl"]):
                wf = "run_spider"
            elif any(w in gl for w in ["alert", "inspect", "finding", "vulnerability"]):
                wf = "inspect_alerts"
            else:
                wf = "quick_start"
            args = {
                "action": "workflow",
                "workflow": wf,
                "target_url": target_url,
                "params": {"target_url": target_url, "format": "html"},
            }
        elif tid in ("burpsuite.gui.v1", "burp.gui.v1"):
            gl = goal.lower()
            if any(w in gl for w in ["history", "proxy"]):
                wf = "inspect_proxy_history"
            elif any(w in gl for w in ["repeater", "replay"]):
                wf = "send_to_repeater"
            elif any(w in gl for w in ["sitemap", "map"]):
                wf = "export_target_sitemap"
            else:
                wf = "init_project"
            args = {"action": "workflow", "workflow": wf, "params": {}}
        elif tid == "wireshark.gui.v1":
            gl = goal.lower()
            if any(w in gl for w in ["filter", "display"]):
                wf = "apply_display_filter"
            elif any(w in gl for w in ["packet", "inspect"]):
                wf = "inspect_packet"
            elif any(w in gl for w in ["save", "pcap", "stop"]):
                wf = "stop_and_save_pcap"
            else:
                wf = "start_capture"
            args = {"action": "workflow", "workflow": wf, "params": {"interface": "eth0"}}
        elif tid == "dnsrecon.enum.v1":
            args = {"target": host_only or target or "target.lab", "scan_type": "std"}
        elif tid == "subfinder.enum.v1":
            args = {"target": host_only or target or "127.0.0.1"}
        elif tid == "trivy.fs.v1":
            args = {
                "target": target if target.startswith(("/", ".")) else "/home/kali",
                "severity": "HIGH,CRITICAL",
                "scanners": "vuln,secret",
                "format": "json",
            }
        elif tid == "wpscan.audit.v1":
            target_url = target if target.startswith("http") else f"http://{target}"
            args = {"target": target_url, "detection_mode": "passive", "enumerate": "vp,u"}
        elif tid == "browser.security.v1":
            target_url = target if target.startswith("http") else f"http://{target}"
            args = {"url": target_url, "action": "navigate"}
        elif tid == "hello_world":
            args = {"name": "kairo"}
        else:
            args = {"target": target}

        return args



# Global singleton instance
tool_selector = HybridToolSelector()
