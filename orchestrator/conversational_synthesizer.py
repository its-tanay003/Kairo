"""
Conversational Chat Synthesis & Proactive Next-Step Recommendation Engine for Kairo.

Transforms raw multi-step tool execution outputs, verified findings, and evidence artifacts
into a clean, natural, chat-first markdown response following the mandatory 4-section architecture:
1. Executive Summary: Direct conversational answer to what the user asked.
2. Step-by-Step Tool Execution Breakdown: Tools executed, exact commands/parameters, duration, and key parsed outputs.
3. Verified Findings & Evidence: Live-probed ports, services, routes, and validated vulnerability findings.
4. What We Can Do Next (Actionable Recommendations): 3 to 5 concrete next steps with click-to-run prompts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("orchestrator.conversational_synthesizer")

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class NextStepRecommendation:
    """Actionable recommendation card with click-to-run prompt."""
    title: str
    rationale: str
    recommended_tools: List[str]
    suggested_prompt: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["prompt"] = self.suggested_prompt
        d["tool_id"] = self.recommended_tools[0] if self.recommended_tools else ""
        priority = "medium"
        txt = (self.title + " " + self.rationale).lower()
        if any(w in txt for w in ["cve", "vuln", "exploit", "critical", "admin", "sensitive", "vulnerability"]):
            priority = "high"
        elif any(w in txt for w in ["passive", "header", "traffic", "capture"]):
            priority = "low"
        d["priority"] = priority
        d["description"] = self.rationale
        return d


class ConversationalSynthesizer:
    """
    Unified Conversational Synthesis Pipeline for Kairo.
    Integrates raw tool outputs, verified findings, and the tool registry
    to build rich chat responses and context-aware follow-up recommendations.
    """

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = db_path

    def generate_recommendations(
        self,
        target: str,
        goal: str,
        context: Any,
        executed_tools: List[str],
        findings: Optional[List[Dict[str, Any]]] = None,
    ) -> List[NextStepRecommendation]:
        """
        Generates 3 to 5 concrete, context-aware next steps based on the actual findings.
        Every recommendation includes title, rationale, recommended_tools, and suggested_prompt.
        """
        recommendations: List[NextStepRecommendation] = []
        clean_target = re.sub(r"^https?://", "", target).split("/")[0].split(":")[0] or "127.0.0.1"
        is_ip = bool(re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", clean_target))
        is_domain = not is_ip and ("." in clean_target)

        findings_str = ""
        if findings:
            for f in findings:
                if isinstance(f, str):
                    findings_str += f + " "
                elif isinstance(f, dict):
                    findings_str += " ".join(str(v) for v in f.values()) + " "
        combined_text = f"{goal} {findings_str} {target}".lower()

        # Extract attributes from context
        open_ports = list(getattr(context, "open_ports", []) or [])
        web_urls = list(getattr(context, "web_urls", []) or [])
        web_endpoints = list(getattr(context, "web_endpoints", []) or [])
        technologies = list(getattr(context, "technologies", []) or [])
        services = getattr(context, "services", {}) or {}

        if not open_ports:
            for m in re.finditer(r"(?:port|ports)\s*[:=]?\s*(\d+)", combined_text):
                try:
                    open_ports.append(int(m.group(1)))
                except ValueError:
                    pass
            for m in re.finditer(r"(\d+)/(?:tcp|udp)", combined_text):
                try:
                    open_ports.append(int(m.group(1)))
                except ValueError:
                    pass

        has_web = (
            bool(web_urls)
            or any(p in (80, 443, 8000, 8080, 8443, 3000, 5000) for p in open_ports)
            or any("http" in str(s).lower() or "web" in str(s).lower() for s in (services.values() if isinstance(services, dict) else services))
            or target.lower().startswith(("http://", "https://"))
            or any(w in combined_text for w in ["web", "http", "apache", "nginx", "endpoint", "/admin", "port 80", "8080", "443"])
        )

        primary_web_url = getattr(context, "get_primary_web_url", lambda: "")() or (
            f"https://{clean_target}" if 443 in open_ports else f"http://{clean_target}"
        )

        executed_lower = [t.lower() for t in executed_tools]

        # 1. Web Directory Fuzzing & Content Discovery
        if has_web and not any("dir" in t or "gobuster" in t or "ffuf" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Fuzz Hidden Web Directories & API Routes",
                rationale=f"Active web service verified on {primary_web_url}. Fuzzing discovers hidden administrative panels, API endpoints, and backup artifacts.",
                recommended_tools=["gobuster.dir.v1", "ffuf.fuzz.v1"],
                suggested_prompt=f"Fuzz web directories on {primary_web_url} with common wordlist",
            ))

        # 2. Web Technology & Header Fingerprinting
        if has_web and not any("whatweb" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Fingerprint Web Technologies & HTTP Server Headers",
                rationale=f"Identify underlying web framework, CMS, reverse proxy, and HTTP headers on {primary_web_url} to assess exposed attack surfaces.",
                recommended_tools=["whatweb.scan.v1"],
                suggested_prompt=f"Profile web technologies and HTTP server headers on {primary_web_url}",
            ))

        # 3. Web Vulnerability & Misconfiguration Audit (Nikto)
        if has_web and not any("nikto" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Scan Web Server Misconfigurations & Dangerous Files",
                rationale=f"Audit {primary_web_url} for insecure HTTP headers, default installation files, and obsolete server software advisories.",
                recommended_tools=["nikto.scan.v1"],
                suggested_prompt=f"Run a web vulnerability scan on {primary_web_url}",
            ))

        # 4. WordPress Security Audit (if WordPress detected or in technologies)
        is_wp = any("wordpress" in str(t).lower() or "wp" in str(t).lower() for t in technologies) or any("wp-" in ep for ep in web_endpoints)
        if is_wp and not any("wpscan" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Audit WordPress Plugins, Themes & User Accounts",
                rationale=f"WordPress components detected on {primary_web_url}. Check for vulnerable plugins, themes, and timthumb vulnerabilities.",
                recommended_tools=["wpscan.audit.v1"],
                suggested_prompt=f"Audit WordPress plugins, themes, and users on {primary_web_url}",
            ))

        # 5. Parameter Fuzzing & SQL Injection Testing
        if (web_endpoints or has_web) and not any("sqlmap" in t for t in executed_lower):
            ep_preview = f" on {web_endpoints[0]}" if web_endpoints else ""
            recommendations.append(NextStepRecommendation(
                title=f"Audit Web Input Parameters for SQL Injection",
                rationale=f"Test exposed web endpoints{ep_preview} for blind, time-based, and error-based SQL injection vectors.",
                recommended_tools=["sqlmap.scan.v1"],
                suggested_prompt=f"Audit web endpoints on {primary_web_url} for SQL injection vulnerabilities",
            ))

        # 6. Authentication Service Audit (SSH / FTP / SMB)
        has_auth = any(p in (21, 22, 23, 445, 3389, 3306, 5432) for p in open_ports)
        if has_auth and not any("hydra" in t for t in executed_lower):
            auth_svc = "ssh" if 22 in open_ports else ("ftp" if 21 in open_ports else "smb")
            auth_port = 22 if 22 in open_ports else (21 if 21 in open_ports else 445)
            recommendations.append(NextStepRecommendation(
                title=f"Audit {auth_svc.upper()} Authentication & Credential Hygiene",
                rationale=f"Port {auth_port} ({auth_svc}) is exposed. Test for default accounts, weak credential policies, and brute-force resilience.",
                recommended_tools=["hydra.brute.v1"],
                suggested_prompt=f"Test common credential security for {auth_svc} on {clean_target} port {auth_port}",
            ))

        # 7. CVE and Exploit Correlation (SearchSploit)
        if (open_ports or technologies or services) and not any("searchsploit" in t for t in executed_lower):
            query = ""
            if isinstance(services, dict):
                for s_info in services.values():
                    if isinstance(s_info, dict) and s_info.get("product"):
                        query = f"{s_info.get('product')} {s_info.get('version', '')}".strip()
                        break
            if not query and technologies:
                query = technologies[0]
            if not query:
                query = "Apache" if has_web else "OpenSSH"
            recommendations.append(NextStepRecommendation(
                title=f"Search Disclosed Vulnerabilities for Detected Services",
                rationale=f"Query Exploit-DB and vulnerability archives for exploits matching detected versions: '{query}'.",
                recommended_tools=["searchsploit.search.v1"],
                suggested_prompt=f"Search known CVEs and exploits for {query}",
            ))

        # 8. Subdomain & DNS Enumeration (if domain)
        if is_domain and not any("subfinder" in t or "dnsrecon" in t or "dns" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Enumerate Subdomains & DNS Architecture",
                rationale=f"Enumerate all associated subdomains, mail exchangers, and DNS records for domain '{clean_target}'.",
                recommended_tools=["subfinder.enum.v1", "dnsrecon.enum.v1"],
                suggested_prompt=f"Enumerate subdomains and DNS records for {clean_target}",
            ))

        # 9. WHOIS & ASN Scope Reconnaissance
        if is_domain and not any("whois" in t for t in executed_lower):
            recommendations.append(NextStepRecommendation(
                title=f"Lookup Domain Registration & WHOIS Records",
                rationale=f"Retrieve registrar information, netblocks, and administrative attribution records for '{clean_target}'.",
                recommended_tools=["whois.lookup.v1"],
                suggested_prompt=f"Lookup WHOIS ownership and ASN records for {clean_target}",
            ))

        # 10. Deep Port Sweep & Network Packet Capture (Fallbacks to ensure 3-5 recommendations)
        fallback_candidates = [
            NextStepRecommendation(
                title=f"Run Full-Port TCP & UDP Service Sweep",
                rationale=f"Perform a comprehensive 1-65535 port audit on {clean_target} with aggressive service version detection.",
                recommended_tools=["nmap.scan.v1"],
                suggested_prompt=f"Run full port scan on {clean_target} across all TCP ports with service detection",
            ),
            NextStepRecommendation(
                title=f"Capture Live Network Protocol Traffic",
                rationale=f"Record raw network packets to analyze protocol handshakes, TLS parameters, and anomalous traffic streams.",
                recommended_tools=["tcpdump.capture.v1", "wireshark.gui.v1"],
                suggested_prompt=f"Capture network traffic on interface eth0 for 20 packets",
            ),
            NextStepRecommendation(
                title=f"Audit Host TLS/SSL Configuration & Cipher Suites",
                rationale=f"Verify SSL/TLS protocols, certificates, cipher suites, and cryptographic posture on {clean_target}.",
                recommended_tools=["testssl.audit.v1"],
                suggested_prompt=f"Audit TLS/SSL configuration and cipher suite vulnerabilities on {clean_target}",
            ),
            NextStepRecommendation(
                title=f"Scan for Common Service Misconfigurations",
                rationale=f"Run vulnerability templates and misconfiguration checks against network listeners on {clean_target}.",
                recommended_tools=["nuclei.scan.v1"],
                suggested_prompt=f"Run nuclei vulnerability templates against {clean_target}",
            ),
        ]
        existing_titles = {r.title for r in recommendations}
        for fb in fallback_candidates:
            if len(recommendations) >= 3:
                break
            if fb.title not in existing_titles:
                recommendations.append(fb)
                existing_titles.add(fb.title)

        # Cap recommendations between 3 and 5
        return recommendations[:5]

    def synthesize(
        self,
        goal: str,
        target: str,
        nodes_executed: List[Any],
        context: Any,
        overall_status: str = "completed",
        duration_s: float = 0.0,
        plan_id: Optional[str] = None,
        verified_findings: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes the complete conversational response matching the mandatory 4-section architecture:
        1. Executive Summary
        2. Step-by-Step Tool Execution Breakdown
        3. Verified Findings & Evidence
        4. What We Can Do Next (Actionable Recommendations)
        """
        executed_tools: List[str] = []
        for n in nodes_executed:
            tid = getattr(n, "tool_id", None) or (n.get("tool_id") if isinstance(n, dict) else None)
            if tid:
                executed_tools.append(tid)

        recommendations = self.generate_recommendations(
            target=target,
            goal=goal,
            context=context,
            executed_tools=executed_tools,
            findings=verified_findings,
        )

        completed_count = sum(1 for n in nodes_executed if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else "")) == "success")
        failed_count = sum(1 for n in nodes_executed if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else "")) == "failed")
        skipped_count = sum(1 for n in nodes_executed if (getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else "")) in ("skipped", "blocked"))

        status_emoji = "✅" if overall_status == "completed" else ("⚠️" if overall_status == "partial" else "❌")
        status_label = "Completed Successfully" if overall_status == "completed" else ("Partially Completed" if overall_status == "partial" else "Assessment Failed")

        open_ports = getattr(context, "open_ports", []) or []
        web_endpoints = getattr(context, "web_endpoints", []) or []
        technologies = getattr(context, "technologies", []) or []
        vulnerabilities = getattr(context, "vulnerabilities", []) or []

        # --- Section 1: Executive Summary ---
        exec_summary = (
            f"## 1. Executive Summary\n\n"
            f"### {status_emoji} Overview\n\n"
            f"I have completed the autonomous security assessment for target **`{target}`** "
            f"to accomplish the objective: *\"{goal}\"*.\n\n"
            f"- **Execution Result:** {status_label} in **{duration_s:.1f}s**\n"
            f"- **Workflow Orchestration:** {completed_count} steps completed successfully"
            f"{f', {failed_count} steps encountered failures' if failed_count else ''}"
            f"{f', {skipped_count} steps skipped by prerequisite gate' if skipped_count else ''}.\n"
        )
        if open_ports:
            exec_summary += f"- **Attack Surface Discovered:** Found **{len(open_ports)} open service ports** (`{', '.join(str(p) for p in sorted(open_ports))}`).\n"
        else:
            exec_summary += f"- **Perimeter Status:** No open listening ports were exposed.\n"

        # --- Section 2: Step-by-Step Tool Execution Breakdown ---
        breakdown_lines = [
            f"## 2. Step-by-Step Breakdown\n",
            f"### ⛓️ Step-by-Step Tool Execution Breakdown\n",
        ]
        for idx, n in enumerate(nodes_executed, 1):
            nid = getattr(n, "node_id", None) or (n.get("node_id") if isinstance(n, dict) else f"step_{idx}")
            cap = getattr(n, "capability", None) or (n.get("capability") if isinstance(n, dict) else "")
            tid = getattr(n, "tool_id", None) or (n.get("tool_id") if isinstance(n, dict) else "unknown_tool")
            status = getattr(n, "status", None) or (n.get("status") if isinstance(n, dict) else "unknown")
            cmd = getattr(n, "command_line", None) or (n.get("command_line") if isinstance(n, dict) else "")
            dur = getattr(n, "duration_ms", None) or (n.get("duration_ms") if isinstance(n, dict) else 0.0)
            reason = getattr(n, "skipped_reason", None) or (n.get("skipped_reason") if isinstance(n, dict) else "")
            stdout = getattr(n, "stdout", "") or (n.get("stdout") if isinstance(n, dict) else "")

            rec_path = getattr(n, "recovery_path", []) or (n.get("recovery_path") if isinstance(n, dict) else [])
            rec_badge = " *(Recovered via fallback)*" if len(rec_path) > 1 else ""

            if status == "success":
                icon = "✅"
                summary_info = f"completed in {dur:.0f}ms{rec_badge}"
            elif status in ("skipped", "blocked"):
                icon = "⏭️"
                summary_info = f"skipped ({reason})"
            else:
                icon = "❌"
                summary_info = f"failed (exit code {getattr(n, 'exit_code', 1)})"

            breakdown_lines.append(f"**Step {idx}: `{nid}` ({cap})** — {icon} {summary_info}")
            breakdown_lines.append(f"- **Tool:** `{tid}`")
            if cmd:
                breakdown_lines.append(f"- **Command Invocation:** `{cmd}`")
            if stdout:
                stdout_preview = stdout.strip().split("\n")[:3]
                breakdown_lines.append(f"- **Key Extracted Output:** {'; '.join(s.strip() for s in stdout_preview if s.strip())[:160]}")
            breakdown_lines.append("")

        step_breakdown = "\n".join(breakdown_lines)

        # --- Section 3: Verified Findings & Evidence ---
        findings_lines = [
            f"## 3. Verified Findings & Evidence\n",
            f"### 🛡️ Verified Findings & Evidence\n",
        ]
        if open_ports:
            findings_lines.append(f"#### 🌐 Network & Service Ports")
            findings_lines.append(f"| Port | Service | Product / Version | Verification |")
            findings_lines.append(f"|---|---|---|---|")
            services_dict = getattr(context, "services", {}) or {}
            for p in sorted(open_ports):
                s_info = services_dict.get(f"{p}/tcp", {}) if isinstance(services_dict, dict) else {}
                svc = s_info.get("service", "open") if isinstance(s_info, dict) else "open"
                prod = f"{s_info.get('product', '')} {s_info.get('version', '')}".strip() if isinstance(s_info, dict) else ""
                findings_lines.append(f"| `{p}/tcp` | **{svc}** | {prod or 'Discovered'} | Active Handshake ✅ |")
            findings_lines.append("")

        if technologies:
            findings_lines.append(f"- **Detected Technologies:** `{', '.join(technologies)}`")

        if web_endpoints:
            findings_lines.append(f"- **Identified Web Endpoints ({len(web_endpoints)}):** `{', '.join(web_endpoints[:5])}`" + (f" *(+{len(web_endpoints)-5} more)*" if len(web_endpoints) > 5 else ""))

        if vulnerabilities:
            findings_lines.append(f"- ⚠️ **Identified Security Advisories ({len(vulnerabilities)}):**")
            for v in vulnerabilities[:3]:
                v_title = v.get("title") or v.get("cve") or "Vulnerability"
                v_sev = v.get("severity", "MEDIUM")
                findings_lines.append(f"  - `[{v_sev}]` **{v_title}**")
        elif not open_ports and not web_endpoints:
            findings_lines.append(f"- *No vulnerabilities or accessible listeners were detected during this phase.*")
        else:
            findings_lines.append(f"- **Baseline Posture:** Service listeners mapped cleanly without immediate critical exposure.")

        findings_lines.append("")
        verified_evidence = "\n".join(findings_lines)

        # --- Section 4: What We Can Do Next (Actionable Recommendations) ---
        recs_lines = [
            f"## 4. What We Can Do Next\n",
            f"### 💡 What We Can Do Next (Actionable Recommendations)\n",
            f"Based on the discoveries from this execution, here are **{len(recommendations)} recommended follow-up actions** you can trigger immediately:\n",
        ]
        for idx, rec in enumerate(recommendations, 1):
            tools_str = ", ".join(f"`{t}`" for t in rec.recommended_tools)
            recs_lines.append(f"#### {idx}. {rec.title}")
            recs_lines.append(f"- **Rationale:** {rec.rationale}")
            recs_lines.append(f"- **Recommended Tools:** {tools_str}")
            recs_lines.append(f"- **Click to Run:** `{rec.suggested_prompt}`\n")

        recommendations_section = "\n".join(recs_lines)

        # Combine into complete conversational reply
        full_reply = f"# Security Assessment Synthesis\n\n{exec_summary}\n{step_breakdown}\n{verified_evidence}\n{recommendations_section}"

        recs_dicts = [r.to_dict() for r in recommendations]

        findings_table = []
        for p in open_ports:
            s_dict = getattr(context, "services", {}) or {}
            p_info = s_dict.get(f"{p}/tcp", {}) if isinstance(s_dict, dict) else {}
            svc_name = p_info.get("service", "open") if isinstance(p_info, dict) else "open"
            findings_table.append({
                "item": f"Port {p}",
                "value": svc_name,
                "status": "Verified",
            })
        for ep in web_endpoints[:4]:
            findings_table.append({
                "item": "Web Endpoint",
                "value": ep,
                "status": "Discovered",
            })

        return {
            "reply": full_reply,
            "next_step_recommendations": recs_dicts,
            "executive_summary": exec_summary,
            "step_breakdown": step_breakdown,
            "verified_evidence": verified_evidence,
            "recommendations": recs_dicts,
            "process": {
                "title": "Autonomous Security Assessment",
                "tool_id": "orchestrator:dag_controller",
                "tool_name": "Autonomous DAG Controller",
                "intent": goal,
                "target": target,
                "duration_s": duration_s,
                "status": "success" if overall_status == "completed" else "warning",
                "status_label": status_label,
            },
            "output": {
                "summary_metrics": [
                    {"label": "Nodes Run", "value": f"{completed_count}/{len(nodes_executed)}", "type": "success"},
                    {"label": "Open Ports", "value": str(len(open_ports)), "type": "info"},
                    {"label": "Status", "value": status_label, "type": "success" if overall_status == "completed" else "warning"},
                ],
                "findings_table": findings_table,
                "raw_stdout": full_reply,
                "has_raw_terminal": False,
            },
            "result": {
                "headline": f"Security Assessment for {target}: {status_label}",
                "status": overall_status,
                "security_posture": "Assessment Completed",
                "key_takeaways": [
                    f"Executed {completed_count} steps on target {target}",
                    f"Identified {len(open_ports)} open service ports",
                    f"Generated {len(recommendations)} follow-up recommendations",
                ],
                "recommended_actions": [
                    {"label": r.title, "prompt": r.suggested_prompt}
                    for r in recommendations
                ],
            },
        }


# Singleton instance
conversational_synthesizer = ConversationalSynthesizer()


def generate_conversational_synthesis(
    goal: str,
    target: str,
    nodes_executed: List[Any],
    context: Any,
    overall_status: str = "completed",
    duration_s: float = 0.0,
    plan_id: Optional[str] = None,
    verified_findings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Top-level helper to generate full 4-section conversational synthesis."""
    return conversational_synthesizer.synthesize(
        goal=goal,
        target=target,
        nodes_executed=nodes_executed,
        context=context,
        overall_status=overall_status,
        duration_s=duration_s,
        plan_id=plan_id,
        verified_findings=verified_findings,
    )


def generate_next_step_recommendations(
    target: str,
    goal: str = "",
    context: Any = None,
    executed_tools: Optional[List[str]] = None,
    findings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Top-level helper returning 3-5 recommendation dictionaries with click-to-run prompts."""
    recs = conversational_synthesizer.generate_recommendations(
        target=target,
        goal=goal,
        context=context,
        executed_tools=executed_tools or [],
        findings=findings,
    )
    return [r.to_dict() for r in recs]


__all__ = [
    "NextStepRecommendation",
    "ConversationalSynthesizer",
    "conversational_synthesizer",
    "generate_conversational_synthesis",
    "generate_next_step_recommendations",
]
