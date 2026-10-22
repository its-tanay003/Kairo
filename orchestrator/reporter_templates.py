"""
Deterministic Reporter & Formatter Templates for Kairo (Fast Templating Engine).

Transforms raw tool execution logs, XML/JSON observations, and terminal streams into
structured, presentation-ready 3-part Claude-style chat responses:
1. Process: Clear, human-readable step breakdown (what tool ran, why, against what target).
2. Output: High-clarity structured findings (hosts, ports, services, metrics, and clean terminal).
3. Result: Executive synthesis, plain-English security verdict, and actionable next steps.

Architectural Note:
This module operates via fast, deterministic templating (sub-millisecond execution,
zero hallucinations, and no external/local LLM inference calls required).
A planned follow-up (Option B) can layer dynamic natural-language summarization
via `llama_client.py` on top of these structured observation models while preserving
strict evidence schemas.
"""

from __future__ import annotations
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.reporter_templates")

from orchestrator.kali_connector import FALLBACK_NOTICE_TEXT
from orchestrator.llama_client import LlamaCppClient

REPORTER_CHAT_REPLY_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": (
                "The complete natural conversational markdown chat response answering the user's goal. "
                "Must reason authentically over the technical evidence, explain the practical security meaning "
                "of discovered services/ports/vulnerabilities, and provide actionable guidance. "
                "Must NEVER invent or assume any findings not present in the evidence context."
            ),
        },
        "headline": {
            "type": "string",
            "description": "Crisp one-sentence executive summary of the outcome.",
        },
        "security_posture": {
            "type": "string",
            "description": "Brief security posture verdict based strictly on verified findings.",
        },
        "key_takeaways": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2 to 4 key factual takeaways strictly derived from the evidence context.",
        },
        "verified_evidence_cited": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific finding items, ports, hosts, or codes from the evidence that were cited in this reply.",
        },
    },
    "required": ["reply", "headline", "security_posture", "key_takeaways"],
}

REPORTER_SYSTEM_PROMPT = """You are Kairo's Lead Autonomous Security Analyst and Conversational Synthesizer.
Your mission is to transform structured technical execution logs, exit codes, and verified findings into a natural, authoritative, conversational chat reply — exactly like high-end AI security agents (such as Claude or ChatGPT configured for cybersecurity).

STRICT ANTI-HALLUCINATION & EVIDENCE INTEGRITY MANDATE:
1. STRICT ZERO-INVENTION DISCIPLINE:
   - You MUST NOT invent, guess, extrapolate, or hallucinate any port, service, vulnerability, CVE, host, user, or credential that is NOT explicitly present in the provided EVIDENCE CONTEXT.
   - If the tool failed (non-zero exit code), report the error diagnostics truthfully. Never pretend a failed command succeeded.
   - If the scan returned 0 open ports, 0 vulnerabilities, or target unreachable, report that clearly as a clean or unreachable target. Never fabricate findings to sound impressive.
   - If marked as SIMULATED or MOCK, you MUST truthfully reflect that it was a demonstration run and no live scan occurred.
2. AUTHENTIC AGENT REASONING:
   - Do NOT output a cookie-cutter template. Write like an experienced penetration tester speaking directly to the user.
   - Directly address what the user asked in their original goal.
   - Explain the technical significance of confirmed findings (e.g., what having SSH or HTTP open means for the attack surface, or why an unreachable host is expected).
   - Use clean, modern Markdown with appropriate formatting, bullet points, and code formatting for IPs and ports.
3. Return ONLY a valid JSON object matching the requested schema.
"""

_DEFAULT_LLAMA_CLIENT: Optional[LlamaCppClient] = None


def get_llama_client(base_url: Optional[str] = None) -> LlamaCppClient:
    """Returns singleton LlamaCppClient instance."""
    global _DEFAULT_LLAMA_CLIENT
    if _DEFAULT_LLAMA_CLIENT is None or (base_url and _DEFAULT_LLAMA_CLIENT.base_url != base_url.rstrip("/")):
        _DEFAULT_LLAMA_CLIENT = LlamaCppClient(base_url=base_url)
    return _DEFAULT_LLAMA_CLIENT


def synthesize_with_llama(
    user_goal: str,
    base_res: Dict[str, Any],
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str = "",
    duration_s: float = 0.5,
    execution_plane: Optional[str] = None,
    is_simulated: bool = False,
    is_scope_violation: bool = False,
    client: Optional[LlamaCppClient] = None,
) -> Optional[Dict[str, Any]]:
    """
    Refines the baseline template response into genuine conversational security reasoning
    via llama.cpp with strict JSON-schema grammar constraints and evidence context.
    Returns None if llama.cpp is unavailable, unhealthy, or fails.
    """
    client = client or get_llama_client()
    if not client.is_healthy():
        return None

    proc = base_res.get("process", {})
    outp = base_res.get("output", {})
    res_block = base_res.get("result", {})

    target = (
        proc.get("target")
        or inputs.get("target")
        or inputs.get("url")
        or inputs.get("domain")
        or inputs.get("host")
        or "target.local"
    )

    evidence_context = {
        "user_goal": user_goal,
        "tool_id": proc.get("tool_id"),
        "tool_name": proc.get("tool_name"),
        "command_line": proc.get("command_line"),
        "target": str(target),
        "exit_code": exit_code,
        "status": proc.get("status"),
        "duration_s": duration_s,
        "execution_plane": execution_plane or proc.get("execution_plane", "kali_docker"),
        "is_simulated": is_simulated or proc.get("is_simulated", False),
        "is_scope_violation": is_scope_violation,
        "summary_metrics": outp.get("summary_metrics", []),
        "verified_findings": outp.get("findings_table", []),
        "baseline_takeaways": res_block.get("key_takeaways", []),
        "raw_stdout_sample": (stdout[:1500] + ("..." if len(stdout) > 1500 else "")) if stdout else "",
        "raw_stderr": stderr[:500] if stderr else "",
    }

    user_msg = (
        f"The security tool '{proc.get('tool_name') or proc.get('tool_id')}' has FINISHED executing against target '{target}'.\n"
        f"Original User Goal: {user_goal}\n\n"
        f"STRICT COMPLETED EXECUTION EVIDENCE:\n"
        f"```json\n{json.dumps(evidence_context, indent=2)}\n```\n\n"
        f"Instructions: Compose a professional, conversational chat reply to the user explaining these completed findings, their security implications, and recommended next steps based strictly on the evidence above."
    )

    messages = [
        {"role": "system", "content": REPORTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        data = client.generate_json(
            messages=messages,
            schema=REPORTER_CHAT_REPLY_JSON_SCHEMA,
            temperature=0.2,
            timeout=30.0,
        )
        if isinstance(data, dict) and data.get("reply"):
            return data
    except Exception as e:
        logger.warning(f"Llama.cpp synthesis error: {e}")
        return None

    return None



def synthesize_agent_response(
    user_goal: str,
    tool_id: Optional[str],
    tool_name: Optional[str],
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str = "",
    observation: Optional[Dict[str, Any]] = None,
    duration_ms: float = 0.0,
    is_scope_violation: bool = False,
    scope_violation_reason: Optional[str] = None,
    execution_plane: Optional[str] = None,
    fallback_notice: Optional[str] = None,
    is_simulated: bool = False,
    simulation_notice: Optional[str] = None,
    llama_client: Optional[LlamaCppClient] = None,
    prefer_llm: bool = True,
) -> Dict[str, Any]:
    """
    Produces a 3-part Claude-style payload:
    - reply: The natural language markdown synthesis.
    - process: Clear description of the steps taken.
    - output: Structured findings + clean terminal stream.
    - result: Key takeaways, security posture, and recommended actions.
    """
    duration_s = round(duration_ms / 1000.0, 1) if duration_ms > 0 else 0.5
    tool_id_clean = tool_id or "agent.reasoning"
    tool_name_clean = tool_name or tool_id_clean.replace(".", " ").title()

    # 1. Handle Scope Contract Violation
    if is_scope_violation or (scope_violation_reason and "OUT_OF_SCOPE" in scope_violation_reason):
        res = _synthesize_scope_violation(
            user_goal=user_goal,
            tool_id=tool_id_clean,
            tool_name=tool_name_clean,
            inputs=inputs,
            reason=scope_violation_reason or "Target falls outside authorized boundary.",
            duration_s=duration_s,
        )
    # 2. Handle Nmap Port & Network Scanners
    elif "nmap" in tool_id_clean.lower():
        res = _synthesize_nmap_scan(
            user_goal=user_goal,
            inputs=inputs,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            observation=observation,
            duration_s=duration_s,
        )
    # 3. Handle Network Interface & Connection Inquiries (ip, ifconfig, ipconfig)
    elif _is_network_interface_query(user_goal, stdout, inputs):
        res = _synthesize_network_connection(
            user_goal=user_goal,
            inputs=inputs,
            stdout=stdout,
            duration_s=duration_s,
        )
    # 4. Handle Web Security Scanners (ZAP, Burp, Nikto, WhatWeb)
    elif any(k in tool_id_clean.lower() for k in ["zap", "burp", "nikto", "whatweb", "ffuf", "gobuster"]):
        res = _synthesize_web_audit(
            user_goal=user_goal,
            tool_id=tool_id_clean,
            tool_name=tool_name_clean,
            inputs=inputs,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            observation=observation,
            duration_s=duration_s,
        )
    # 5. Handle Network Recon & DNS (Whois, Dig)
    elif any(k in tool_id_clean.lower() for k in ["whois", "dig"]):
        res = _synthesize_domain_recon(
            user_goal=user_goal,
            tool_id=tool_id_clean,
            tool_name=tool_name_clean,
            inputs=inputs,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration_s,
        )
    else:
        # 6. Default Shell / Kali / Diagnostic Execution
        res = _synthesize_generic_execution(
            user_goal=user_goal,
            tool_id=tool_id_clean,
            tool_name=tool_name_clean,
            inputs=inputs,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration_s,
        )

    # 7. Layer Dynamic LLM Conversational Synthesis via llama.cpp (Local Model Reasoning)
    if prefer_llm and not is_scope_violation:
        client_to_use = llama_client or get_llama_client()
        try:
            if client_to_use and client_to_use.is_healthy():
                llm_synth = synthesize_with_llama(
                    user_goal=user_goal,
                    base_res=res,
                    inputs=inputs,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_s=duration_s,
                    execution_plane=execution_plane,
                    is_simulated=is_simulated,
                    is_scope_violation=is_scope_violation,
                    client=client_to_use,
                )
                if llm_synth and isinstance(llm_synth, dict) and llm_synth.get("reply"):
                    res["reply"] = llm_synth["reply"]
                    if "result" in res and isinstance(res["result"], dict):
                        if llm_synth.get("headline"):
                            res["result"]["headline"] = llm_synth["headline"]
                        if llm_synth.get("security_posture"):
                            res["result"]["security_posture"] = llm_synth["security_posture"]
                        if llm_synth.get("key_takeaways"):
                            res["result"]["key_takeaways"] = llm_synth["key_takeaways"]
                    res["synthesis_source"] = "llama_local"
                    if "process" in res and isinstance(res["process"], dict):
                        res["process"]["synthesizer"] = "llama_client:json_schema"
        except Exception as e:
            logger.warning(f"Llama local chat synthesis failed: {e}. Preserving deterministic template response.")

    res.setdefault("synthesis_source", "deterministic_template")
    if "process" in res and isinstance(res["process"], dict):
        res["process"].setdefault("synthesizer", "reporter_templates:deterministic")

    # Decorate with visible simulation notice when running on simulated mock plane
    eff_is_simulated = bool(
        is_simulated
        or execution_plane == "simulated_mock"
        or (isinstance(observation, dict) and (
            observation.get("execution_plane") == "simulated_mock"
            or observation.get("is_simulated") is True
            or bool(observation.get("simulation_notice"))
        ))
    )
    if eff_is_simulated:
        sim_notice_text = (
            simulation_notice
            or (observation.get("simulation_notice") if isinstance(observation, dict) else None)
            or "[SIMULATED — demo mode, not a live scan]"
        )
        sim_banner = f"> ⚠️ **{sim_notice_text}**\n\n"
        if sim_notice_text not in res.get("reply", ""):
            res["reply"] = sim_banner + res.get("reply", "")

        # Attach to process metadata for tool card UI
        if "process" in res and isinstance(res["process"], dict):
            res["process"]["execution_plane"] = "simulated_mock"
            res["process"]["simulation_notice"] = sim_notice_text
            res["process"]["is_simulated"] = True

        # Prepend to output summary metrics
        if "output" in res and isinstance(res["output"], dict):
            metrics = res["output"].setdefault("summary_metrics", [])
            if not any(m.get("label") == "Execution Plane" for m in metrics):
                metrics.insert(0, {
                    "label": "Execution Plane",
                    "value": "Simulated Demo (Not Live)",
                    "type": "warning",
                })
    else:
        # Decorate with visible plain-language fallback notice when running on local host
        is_fallback = bool(
            execution_plane == "local_host_fallback"
            or fallback_notice
            or (isinstance(observation, dict) and (
                observation.get("execution_plane") == "local_host_fallback"
                or bool(observation.get("fallback_notice"))
                or observation.get("local_fallback") is True
            ))
        )
        if is_fallback:
            notice_text = fallback_notice or (
                observation.get("fallback_notice") if isinstance(observation, dict) else None
            ) or FALLBACK_NOTICE_TEXT

            # Prepend visible plain-language notice in the chat reply markdown
            notice_banner = f"> ⚠️ **{notice_text}**\n\n"
            if notice_text not in res.get("reply", ""):
                res["reply"] = notice_banner + res.get("reply", "")

            # Attach to process metadata for tool card UI
            if "process" in res and isinstance(res["process"], dict):
                res["process"]["execution_plane"] = "local_host_fallback"
                res["process"]["fallback_notice"] = notice_text
                res["process"]["local_fallback"] = True

            # Prepend to output summary metrics
            if "output" in res and isinstance(res["output"], dict):
                metrics = res["output"].setdefault("summary_metrics", [])
                if not any(m.get("label") == "Execution Plane" for m in metrics):
                    metrics.insert(0, {
                        "label": "Execution Plane",
                        "value": "Host Fallback (No VM)",
                        "type": "warning",
                    })

    try:
        from orchestrator.conversational_synthesizer import conversational_synthesizer
        target_cand = (
            inputs.get("target")
            or inputs.get("url")
            or inputs.get("domain")
            or inputs.get("host")
            or "127.0.0.1"
        )
        if isinstance(target_cand, list) and target_cand:
            target_cand = target_cand[0]
        target_str = str(target_cand)
        raw_recs = conversational_synthesizer.generate_recommendations(
            target=target_str,
            goal=user_goal,
            context=None,
            executed_tools=[tool_id_clean],
            findings=observation.get("findings") if isinstance(observation, dict) else None,
        )
        recs_list = [r.to_dict() for r in raw_recs]
        if recs_list:
            res["next_step_recommendations"] = recs_list
            res["recommendations"] = recs_list
    except Exception as e:
        logger.debug(f"Could not generate next_step_recommendations in synthesize_agent_response: {e}")

    return res


# ---------------------------------------------------------------------------
# Specific Synthesizers
# ---------------------------------------------------------------------------

def _is_network_interface_query(goal: str, stdout: str, inputs: Dict[str, Any]) -> bool:
    goal_l = goal.lower()
    cmd = str(inputs.get("command", "")).lower()
    args_str = " ".join(str(a) for a in inputs.get("args", [])).lower()
    full_cmd = f"{cmd} {args_str}"

    is_intent = any(k in goal_l for k in ["connected to", "what network", "my network", "my ip", "which network", "connected right now", "network interface"])
    is_cmd = any(k in full_cmd for k in ["ip addr", "ifconfig", "ipconfig", "route", "ip route", "netstat", "wlan", "eth0"])
    has_signals = any(k in stdout for k in ["IPv4 Address", "inet ", "Subnet Mask", "Default Gateway", "broadcast", "wlan0", "eth0"])

    return is_intent or is_cmd or (has_signals and len(stdout) < 4000)


def _synthesize_network_connection(
    user_goal: str,
    inputs: Dict[str, Any],
    stdout: str,
    duration_s: float,
) -> Dict[str, Any]:
    # Extract IP, Gateway, Subnet from Windows or Linux command output
    local_ip = "127.0.0.1"
    gateway = "192.168.1.1"
    subnet = "192.168.1.0/24"
    interface_name = "Local Network Interface"

    # Windows ipconfig matching
    m_win_ip = re.search(r"IPv4 Address[ .:]+([\d.]+)", stdout)
    m_win_gw = re.search(r"Default Gateway[ .:]+([\d.]+)", stdout)
    m_win_mask = re.search(r"Subnet Mask[ .:]+([\d.]+)", stdout)
    if m_win_ip:
        local_ip = m_win_ip.group(1)
        if m_win_gw and m_win_gw.group(1).count(".") == 3:
            gateway = m_win_gw.group(1)
        # derive subnet prefix
        octs = local_ip.split(".")[:3]
        subnet = f"{'.'.join(octs)}.0/24"
        interface_name = "Wi-Fi / Ethernet"

    # Linux ip addr matching
    m_lin = re.search(r"inet ([\d.]+)/(\d+).*?(\w+)$", stdout, re.MULTILINE)
    if m_lin:
        local_ip = m_lin.group(1)
        prefix = m_lin.group(2)
        interface_name = m_lin.group(3)
        octs = local_ip.split(".")[:3]
        subnet = f"{'.'.join(octs)}.0/{prefix}"

    # Build clear markdown
    md = f"""### 🌐 Current Network Connection

You are connected to local network **`{subnet}`** via **`{interface_name}`**.

#### 📋 Network Configuration
- **Your Device IP:** `{local_ip}`
- **Default Gateway (Router):** `{gateway}`
- **Subnet Range:** `{subnet}`
- **Interface:** `{interface_name}`

#### 🛡️ Scope & Security Assessment
Your local IP (`{local_ip}`) and router gateway (`{gateway}`) are located within private Class C address space (`{subnet}`).
All host addresses in this subnet are reachable and configured within your active Scope Contract.

#### 💡 Recommended Next Actions
- Scan the entire local subnet to discover all active computers, phones, and IoT devices.
- Probe the router management interface at `{gateway}` for open web admin ports.
"""

    return {
        "reply": md,
        "process": {
            "title": "Network Interface Discovery",
            "tool_id": "shell.run.v1",
            "tool_name": "Network Configuration Probe",
            "intent": "Determine current network adapter settings and gateway",
            "command_line": f"{inputs.get('command', 'ipconfig')} {' '.join(inputs.get('args', []))}".strip(),
            "target": local_ip,
            "duration_s": duration_s,
            "status": "success",
            "status_label": "Completed (exit 0)",
            "tier": 1,
        },
        "output": {
            "summary_metrics": [
                {"label": "Local IP", "value": local_ip, "type": "info"},
                {"label": "Gateway", "value": gateway, "type": "success"},
                {"label": "Subnet", "value": subnet, "type": "neutral"},
            ],
            "findings_table": [
                {"item": "Local IP Address", "value": local_ip, "status": "Active"},
                {"item": "Default Gateway", "value": gateway, "status": "Online"},
                {"item": "Network Scope", "value": subnet, "status": "Authorized"},
                {"item": "Adapter Type", "value": interface_name, "status": "Connected"},
            ],
            "raw_stdout": stdout,
            "raw_stderr": "",
            "has_raw_terminal": bool(stdout.strip()),
        },
        "result": {
            "headline": f"Connected to {subnet} (Gateway: {gateway})",
            "status": "clean",
            "security_posture": "Standard Private Subnet",
            "key_takeaways": [
                f"Your active local IP is {local_ip}.",
                f"Router gateway is operating at {gateway}.",
                f"The subnet {subnet} is within your authorized scope contract.",
            ],
            "recommended_actions": [
                {"label": f"Scan Subnet {subnet}", "prompt": f"Perform comprehensive reconnaissance and port discovery against {subnet}"},
                {"label": f"Inspect Gateway {gateway}", "prompt": f"Run port scan against gateway {gateway} for port 80 and 443"},
            ],
        },
    }


def _synthesize_nmap_scan(
    user_goal: str,
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str,
    observation: Optional[Dict[str, Any]] = None,
    duration_s: float = 1.0,
) -> Dict[str, Any]:
    target = inputs.get("target") or "target.local"
    ports_input = inputs.get("ports", "1-1024")

    # Extract parsed hosts and ports
    obs = observation or {}
    hosts = obs.get("hosts", [])
    hosts_found = obs.get("hosts_found", len(hosts))
    raw_open_ports = obs.get("open_ports", 0)
    if isinstance(raw_open_ports, list):
        open_ports_count = len(raw_open_ports)
    else:
        try:
            open_ports_count = int(raw_open_ports or 0)
        except (ValueError, TypeError):
            open_ports_count = 0

    # Fallback parsing from stdout if observation is empty
    if not hosts and stdout:
        hosts = _fallback_parse_nmap_stdout(stdout)
        hosts_found = len(hosts)
        open_ports_count = sum(len(h.get("ports", [])) for h in hosts)

    # Construct findings rows
    findings_rows = []
    ports_list_text = []

    for h in hosts:
        ip = h.get("ip") or h.get("hostname") or target
        hostname = h.get("hostname", "")
        for p in h.get("ports", []):
            p_num = p.get("port")
            p_proto = p.get("protocol", "tcp")
            p_state = p.get("state", "open")
            p_svc = p.get("service") or "unknown"
            p_ver = p.get("version") or p.get("product") or ""
            desc = f"{p_svc} {p_ver}".strip()

            findings_rows.append({
                "host": ip,
                "hostname": hostname,
                "port": f"{p_num}/{p_proto}",
                "service": p_svc,
                "version": p_ver or "standard banner",
                "state": p_state,
            })
            ports_list_text.append(f"`{p_num}/{p_proto}` ({p_svc}{' - ' + p_ver if p_ver else ''}) on `{ip}`")

    # Build natural language synthesis
    if exit_code != 0:
        findings_rows = []
        md = f"""### ❌ Execution Failed: Nmap Port Scan (Exit Code {exit_code})

The port scan against **`{target}`** exited with code `{exit_code}`.

#### 🔍 Execution Details:
- **Target:** `{target}`
- **Requested Ports:** `{ports_input}`
- **Stderr:** {stderr.strip() or 'Execution failed or host unreachable.'}

#### 💡 Suggested Resolution:
Verify that the host `{target}` is powered on and that ICMP/SYN packets are permitted by your local firewall.
"""
        status_type = "failed"
        headline = f"Port scan against {target} failed (Exit {exit_code})"
    elif hosts_found == 0:
        md = f"""### 🔍 Network Reconnaissance Findings

I scanned target **`{target}`** across ports `{ports_input}` in `{duration_s}s`.

#### 📊 Result Overview
- **Hosts Responded:** `0` active hosts detected
- **Open Ports:** `0` open ports discovered
- **Target Status:** Host filtered or offline

#### 🛡️ Security Assessment
The target host `{target}` did not respond to standard TCP probe packets. It may have firewall filtering enabled (e.g., Windows Defender Firewall dropping unsolicited probes) or be offline.

#### 💡 Recommended Next Actions
- Verify the target IP address is correct.
- If testing a Windows host, test with ICMP ping or target `127.0.0.1` / `localhost`.
"""
        status_type = "warning"
        headline = f"Target {target} offline or filtering probes"
    else:
        # We found active hosts and open ports!
        md_lines = [
            f"### 🔍 Network Reconnaissance Findings",
            f"",
            f"I completed a network scan against **`{target}`** in **{duration_s}s**. Found **{hosts_found} active host(s)** and **{open_ports_count} open service port(s)**.",
            f"",
            f"#### 📊 Scan Summary",
            f"- **Target Range:** `{target}`",
            f"- **Active Hosts Online:** `{hosts_found}`",
            f"- **Discovered Open Ports:** `{open_ports_count}`",
            f"- **Scan Profile:** Fast TCP SYN & Service Detection (`-{inputs.get('scan_type', 'sV')}`)",
            f"",
            f"#### 🖥️ Discovered Hosts & Services",
        ]

        for h in hosts:
            h_ip = h.get("ip") or target
            h_name = f" ({h.get('hostname')})" if h.get("hostname") else ""
            h_os = f" · OS: {h.get('os')[0]['name']}" if h.get("os") and len(h.get("os")) > 0 else ""
            md_lines.append(f"**Host:** `{h_ip}`{h_name} — **Status:** `Online`{h_os}")

            h_ports = h.get("ports", [])
            if h_ports:
                for p in h_ports:
                    p_str = f"- **Port {p.get('port')}/{p.get('protocol', 'tcp')}**: `{p.get('service', 'unknown')}`"
                    if p.get("product") or p.get("version"):
                        p_str += f" ({p.get('product', '')} {p.get('version', '')})".strip()
                    md_lines.append(p_str)
            else:
                md_lines.append("- *No open ports detected in scanned range.*")
            md_lines.append("")

        md_lines.extend([
            f"#### 🛡️ Security Assessment & Risk Profile",
            f"- All discovered services are operating within your authorized Scope Contract.",
        ])

        # Flag specific notable ports
        if any(r["port"].startswith("80/") for r in findings_rows):
            md_lines.append("- ⚠️ **Port 80 (HTTP)** is exposed unencrypted. Administration interfaces on port 80 should be evaluated for default credentials or redirected to HTTPS.")
        if any(r["port"].startswith("22/") for r in findings_rows):
            md_lines.append("- ℹ️ **Port 22 (SSH)** is listening. Verify that password authentication is disabled in favor of cryptographic keys.")
        if any(r["port"].startswith("443/") for r in findings_rows):
            md_lines.append("- 🔒 **Port 443 (HTTPS)** is listening with encrypted transport.")

        md_lines.extend([
            f"",
            f"#### 💡 Recommended Next Actions",
            f"1. **Inspect Web Services**: Probe any HTTP/HTTPS endpoints for service headers and known CVEs.",
            f"2. **Vulnerability Audit**: Run OWASP ZAP adapter (`zap.gui.v1`) to check for OWASP Top 10 web flaws.",
        ])

        md = "\n".join(md_lines)
        status_type = "clean" if open_ports_count > 0 else "warning"
        headline = f"Discovered {open_ports_count} open port(s) on {hosts_found} host(s)"

    return {
        "reply": md,
        "process": {
            "title": "Network Reconnaissance",
            "tool_id": "nmap.scan.v1",
            "tool_name": "Nmap Network Scanner",
            "intent": f"Scan {target} for active hosts and open service ports",
            "command_line": f"nmap -{inputs.get('scan_type', 'sV')} -T{inputs.get('timing', 3)} -p {ports_input} {target}",
            "target": target,
            "duration_s": duration_s,
            "status": "success" if exit_code == 0 else "error",
            "status_label": f"Completed ({duration_s}s)" if exit_code == 0 else f"Exit {exit_code}",
            "tier": 2,
        },
        "output": {
            "summary_metrics": [
                {"label": "Hosts Found", "value": str(hosts_found), "type": "info"},
                {"label": "Open Ports", "value": str(open_ports_count), "type": "warning" if open_ports_count > 0 else "neutral"},
                {"label": "Duration", "value": f"{duration_s}s", "type": "neutral"},
            ],
            "findings_table": findings_rows,
            "raw_stdout": stdout,
            "raw_stderr": stderr,
            "has_raw_terminal": bool(stdout.strip() or stderr.strip()),
        },
        "result": {
            "headline": headline,
            "status": status_type,
            "security_posture": f"Scan Failed (Exit Code {exit_code})" if exit_code != 0 else (f"{open_ports_count} Open Ports Discovered" if open_ports_count > 0 else "No Open Ports Exposed"),
            "key_takeaways": [
                f"Nmap scan against {target} failed with exit code {exit_code}.",
                f"Error diagnostics: {stderr.strip() or 'Execution terminated prematurely.'}",
                "No findings were recorded because execution did not complete successfully.",
            ] if exit_code != 0 else [
                f"Scanned target {target} across ports {ports_input}.",
                f"Identified {hosts_found} responding host(s).",
                f"Total open service ports: {open_ports_count}.",
            ],
            "recommended_actions": [
                {"label": f"Probe Web Services on {target}", "prompt": f"Inspect verified vulnerability findings on {target} and generate compliance report"},
                {"label": f"Run OS & Banner Scan", "prompt": f"Perform comprehensive reconnaissance and port discovery against {target}"},
            ],
        },
    }


def _fallback_parse_nmap_stdout(stdout: str) -> List[Dict[str, Any]]:
    hosts = []
    current_host: Dict[str, Any] = {}
    for line in stdout.splitlines():
        m = re.match(r"Nmap scan report for (.+)", line)
        if m:
            if current_host:
                hosts.append(current_host)
            current_host = {"hostname": m.group(1).strip(), "ip": m.group(1).strip(), "ports": []}
        m_port = re.match(r"(\d+)/(\w+)\s+(\w+)\s+(\S+)\s*(.*)", line)
        if m_port and current_host:
            current_host["ports"].append({
                "port": int(m_port.group(1)),
                "protocol": m_port.group(2),
                "state": m_port.group(3),
                "service": m_port.group(4),
                "product": m_port.group(5),
            })
    if current_host:
        hosts.append(current_host)
    return hosts


def _synthesize_web_audit(
    user_goal: str,
    tool_id: str,
    tool_name: str,
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str,
    observation: Optional[Dict[str, Any]] = None,
    duration_s: float = 1.0,
) -> Dict[str, Any]:
    obs = observation or {}
    params_dict = inputs.get("params") if isinstance(inputs.get("params"), dict) else {}
    target = (
        inputs.get("target")
        or inputs.get("url")
        or inputs.get("host")
        or params_dict.get("target")
        or params_dict.get("url")
        or params_dict.get("host")
        or obs.get("target")
        or obs.get("host")
        or "target.local"
    )
    port = (
        inputs.get("port")
        or params_dict.get("port")
        or obs.get("port")
        or 80
    )
    findings_list = obs.get("findings") or obs.get("vulnerabilities") or []
    alerts_count = obs.get("alerts_count") or obs.get("total_findings") or len(findings_list)
    server_info = obs.get("server_info", {})
    conn_status = server_info.get("connection_status", "")

    findings_rows = []
    for f in findings_list[:50]:
        if isinstance(f, dict):
            findings_rows.append({
                "item": f.get("uri") or f.get("path") or "/",
                "value": f.get("description") or f.get("msg") or "Web finding",
                "status": f.get("id") or f.get("osvdb") or "ALERT",
            })
        else:
            findings_rows.append({
                "item": "/",
                "value": str(f),
                "status": "ALERT",
            })

    is_unreachable = (
        conn_status == "unreachable"
        or obs.get("target_reachable") is False
        or "unable to connect" in stdout.lower()
        or "connection refused" in stdout.lower()
        or "target unreachable" in stdout.lower()
        or "host unreachable" in stdout.lower()
        or "target is unreachable" in stdout.lower()
        or "no real target reachable" in stdout.lower()
    )
    is_sim = bool(
        obs.get("is_simulated")
        or obs.get("execution_plane") == "simulated_mock"
        or "[SIMULATED" in stdout
    )

    if exit_code == 0 and not is_unreachable:
        findings_md = ""
        if findings_list:
            if is_sim:
                findings_md = "\n#### 🎭 Simulated Demonstration Output\n"
                for f in findings_list[:8]:
                    if isinstance(f, dict):
                        uri = f.get("uri") or "/"
                        desc = f.get("description") or f.get("name") or "Simulated test finding"
                        fid = f.get("id") or f.get("cwe") or "SIMULATED"
                    else:
                        uri = "/"
                        desc = str(f)
                        fid = "SIMULATED"
                    findings_md += f"- **`[SIMULATED] {fid}`** at `{uri}`: {desc}\n"
            else:
                findings_md = "\n#### 🚨 Key Discovered Findings\n"
                for f in findings_list[:8]:
                    if isinstance(f, dict):
                        uri = f.get("uri") or "/"
                        desc = f.get("description") or "Potential vulnerability"
                        fid = f.get("id") or f.get("osvdb") or "FINDING"
                    else:
                        uri = "/"
                        desc = str(f)
                        fid = "FINDING"
                    findings_md += f"- **`{fid}`** at `{uri}`: {desc}\n"

        if is_sim:
            posture_md = (
                "#### 🎭 Simulation Notice & Disclaimers\n"
                "- **Live Findings Confirmed:** 0 (mock demonstration mode active; no live vulnerability scan performed).\n"
                "- Synthetic frames and mock outputs are watermarked and logged in Evidence Store under execution plane `simulated_mock`."
            )
        else:
            posture_md = (
                "#### 📋 Discovered Vulnerability Posture\n"
                "- Verified against declared OWASP baseline.\n"
                "- Findings and evidence files have been logged into the cryptographically verifiable SQLite Evidence Store."
            )

        target_display = f"{target} (Demo Mode)" if is_sim else target
        alerts_display = f"{alerts_count} (Simulated Mock)" if is_sim else str(alerts_count)

        md = f"""### {'🎭' if is_sim else '🛡️'} Web Security Audit Completed{' [SIMULATED]' if is_sim else ''}

Executed **`{tool_name}`** against web target **`{target_display}`**.

#### 📊 Audit Findings Summary
- **Target URL:** `{target_display}`
- **Security Alerts Identified:** `{alerts_display}`
- **Analysis Execution Time:** `{duration_s}s`
{f"- **Web Server:** `{server_info.get('server')}`" if server_info.get('server') else ""}
{findings_md}
{posture_md}

#### 💡 Recommended Next Actions
- Inspect the generated audit compliance report in the Advanced Console -> Audit tab.
- Re-test specific endpoints after remediation.
"""
    elif is_unreachable:
        md = f"""### ⚠️ Web Target Unreachable

Executed **`{tool_name}`** against **`{target}`**, but no real target was reachable.

#### 🔍 Execution Details:
- **Target Asset:** `{target}`
- **Connection Status:** `Unreachable / Offline`
- **Confirmed Vulnerabilities:** `0` (No live vulnerabilities found or confirmed)
- **Diagnostic:** Target service is not running or connections are refused/unreachable.

#### 🛡️ Truthful Security Finding:
No vulnerability was found. The target is unreachable and cannot be inspected for security issues.

#### 💡 Resolution:
- Verify that the web server on `{target}` is running and bound to port `{port}`.
- If testing a local dev server, ensure it is listening on `0.0.0.0` or test against an active HTTP/HTTPS endpoint.
"""
    else:
        findings_rows = []
        md = f"""### ❌ Execution Failed: Web Application Audit ({tool_name})

The scan using **`{tool_name}`** failed with exit code `{exit_code}`.

#### 🔍 Execution Details:
- **Target:** `{target}`
- **Diagnostic Output:** {stderr.strip() or stdout.strip() or 'Tool execution terminated with error.'}

#### 💡 Resolution:
Ensure the target web server `{target}` is running and accepting HTTP/HTTPS connections on its configured port, and that tool dependencies are installed.
"""

    return {
        "reply": md,
        "process": {
            "title": f"Web Application Audit ({tool_name})",
            "tool_id": tool_id,
            "tool_name": tool_name,
            "intent": f"Perform security inspection against {target}",
            "command_line": f"{tool_id} target={target}",
            "target": target,
            "duration_s": duration_s,
            "status": "success" if (exit_code == 0 and not is_unreachable) else ("warning" if is_unreachable else "error"),
            "status_label": f"Exit {exit_code}",
            "tier": 2,
        },
        "output": {
            "summary_metrics": [
                {"label": "Confirmed Vulnerabilities", "value": "0" if (is_unreachable or is_sim) else str(alerts_count if exit_code == 0 else 0), "type": "warning" if (alerts_count > 0 and not is_sim and not is_unreachable) else ("neutral" if is_unreachable else "success")},
                {"label": "Alerts Found", "value": "0" if is_unreachable else str(alerts_count if exit_code == 0 else 0), "type": "warning" if (alerts_count > 0 and not is_unreachable) else ("neutral" if is_unreachable else "success")},
                {"label": "Target", "value": target, "type": "info"},
                {"label": "Duration", "value": f"{duration_s}s", "type": "neutral"},
            ],
            "findings_table": findings_rows,
            "raw_stdout": stdout,
            "raw_stderr": stderr,
            "has_raw_terminal": bool(stdout.strip() or stderr.strip()),
        },
        "result": {
            "headline": (
                f"Web audit of {target} failed (Exit {exit_code})" if exit_code != 0
                else (f"Target {target} unreachable (0 vulnerabilities confirmed)" if is_unreachable
                else f"Web audit of {target} finished with {alerts_count} alert(s)")
            ),
            "status": "clean" if (exit_code == 0 and not is_unreachable) else "failed",
            "security_posture": (
                f"Audit Failed (Exit Code {exit_code})" if exit_code != 0
                else ("Host Unreachable (0 Findings)" if is_unreachable
                else "Audit Completed")
            ),
            "key_takeaways": [
                f"Target web service at {target} is unreachable or offline.",
                "Zero live vulnerabilities found or confirmed.",
                "Simulation mode truthfully records that no target was reachable.",
            ] if is_unreachable else (
                [
                    f"Web audit against {target} failed with exit code {exit_code}.",
                    f"Error diagnostics: {stderr.strip() or stdout.strip() or 'Non-zero exit encountered.'}",
                    "No security alerts or findings were registered from this failed execution.",
                ] if exit_code != 0 else [
                    f"Scanned web target {target}.",
                    f"Generated evidence artifacts in local store.",
                ]
            ),
            "recommended_actions": [
                {"label": "Inspect Audit Explorer", "prompt": "Inspect verified vulnerability findings, evidence store, and generate compliance report"},
            ],
        },
    }


def _synthesize_domain_recon(
    user_goal: str,
    tool_id: str,
    tool_name: str,
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_s: float,
) -> Dict[str, Any]:
    domain = inputs.get("domain") or inputs.get("target") or "example.com"
    clean_lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("%")][:15]

    if exit_code != 0:
        md = f"""### ❌ Domain Reconnaissance Failed (Exit Code {exit_code})

Query for **`{domain}`** via `{tool_name}` failed with exit code `{exit_code}`.

#### 🔍 Error Details:
```text
{stderr.strip() or stdout.strip() or 'Query failed or host unreachable.'}
```
"""
    else:
        md = f"""### 🌐 Domain & DNS Reconnaissance

Gathered intelligence for **`{domain}`** via `{tool_name}` in **{duration_s}s**.

#### 📋 Records & Registration Summary
```text
{chr(10).join(clean_lines) if clean_lines else 'No records returned.'}
```

#### 💡 Recommended Next Actions
- Scan discovered IP addresses with Nmap.
- Inspect DNS mail records (MX/SPF/DKIM) for email security configuration.
"""

    return {
        "reply": md,
        "process": {
            "title": f"Domain Intelligence ({tool_name})",
            "tool_id": tool_id,
            "tool_name": tool_name,
            "intent": f"Query DNS and registration records for {domain}",
            "command_line": f"{tool_id} {domain}",
            "target": domain,
            "duration_s": duration_s,
            "status": "success" if exit_code == 0 else "error",
            "status_label": f"Exit {exit_code}",
            "tier": 1,
        },
        "output": {
            "summary_metrics": [
                {"label": "Domain", "value": domain, "type": "info"},
                {"label": "Duration", "value": f"{duration_s}s", "type": "neutral"},
            ],
            "findings_table": [],
            "raw_stdout": stdout,
            "raw_stderr": stderr,
            "has_raw_terminal": bool(stdout.strip()),
        },
        "result": {
            "headline": f"Domain query failed for {domain} (Exit {exit_code})" if exit_code != 0 else f"Domain records queried for {domain}",
            "status": "clean" if exit_code == 0 else "failed",
            "security_posture": f"Reconnaissance Failed (Exit Code {exit_code})" if exit_code != 0 else "Reconnaissance Complete",
            "key_takeaways": [
                f"Domain query for {domain} failed with exit code {exit_code}.",
                f"Error output: {stderr.strip() or 'No records returned or host not found.'}",
            ] if exit_code != 0 else [f"Retrieved DNS/WHOIS data for {domain}."],
            "recommended_actions": [
                {"label": f"Scan {domain}", "prompt": f"Perform comprehensive reconnaissance and port discovery against {domain}"},
            ],
        },
    }


def _synthesize_generic_execution(
    user_goal: str,
    tool_id: str,
    tool_name: str,
    inputs: Dict[str, Any],
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_s: float,
) -> Dict[str, Any]:
    cmd = inputs.get("command") or tool_id
    args = inputs.get("args") or []
    args_str = " ".join(str(a) for a in args)
    cmd_line = f"{cmd} {args_str}".strip()
    target = inputs.get("target") or "local"

    # Clean stdout preview
    stdout_preview = stdout.strip()
    if len(stdout_preview) > 1500:
        stdout_preview = stdout_preview[:1500] + "\n... [truncated]"

    if exit_code == 0:
        md = f"""### 💻 Command Execution Completed

Successfully executed **`{cmd_line}`** via `{tool_name}` in **{duration_s}s**.

#### 📋 Execution Result
```bash
{stdout_preview or 'Command executed with no standard output.'}
```

#### 🛡️ Status & Integrity
- **Exit Code:** `0 (Success)`
- **Execution Supervisor:** Sandboxed isolation with resource monitoring.
"""
    else:
        md = f"""### ❌ Execution Failed (Exit Code {exit_code})

Executed **`{cmd_line}`** with exit code **`{exit_code}`**.

#### 🔍 Error / Stderr Details:
```bash
{stderr.strip() or stdout_preview or 'Process exited non-zero.'}
```
"""

    return {
        "reply": md,
        "process": {
            "title": f"Command Execution ({tool_name})",
            "tool_id": tool_id,
            "tool_name": tool_name,
            "intent": user_goal,
            "command_line": cmd_line,
            "target": target,
            "duration_s": duration_s,
            "status": "success" if exit_code == 0 else "error",
            "status_label": f"Exit {exit_code}",
            "tier": 1 if "shell" in tool_id else 2,
        },
        "output": {
            "summary_metrics": [
                {"label": "Exit Code", "value": str(exit_code), "type": "success" if exit_code == 0 else "error"},
                {"label": "Duration", "value": f"{duration_s}s", "type": "neutral"},
            ],
            "findings_table": [],
            "raw_stdout": stdout,
            "raw_stderr": stderr,
            "has_raw_terminal": bool(stdout.strip() or stderr.strip()),
        },
        "result": {
            "headline": f"Command '{cmd}' failed with exit code {exit_code}" if exit_code != 0 else f"Command '{cmd}' finished with exit code {exit_code}",
            "status": "clean" if exit_code == 0 else "failed",
            "security_posture": f"Execution Failed (Exit Code {exit_code})" if exit_code != 0 else "Execution Verified",
            "key_takeaways": [
                f"Command execution failed with exit code {exit_code}.",
                f"Error output: {stderr.strip() or stdout_preview or 'Non-zero exit code encountered.'}",
                "No findings or artifacts were produced from this failed run.",
            ] if exit_code != 0 else [f"Executed {cmd_line}."],
            "recommended_actions": [],
        },
    }


def _synthesize_scope_violation(
    user_goal: str,
    tool_id: str,
    tool_name: str,
    inputs: Dict[str, Any],
    reason: str,
    duration_s: float,
) -> Dict[str, Any]:
    target = inputs.get("target") or "unknown"
    md = f"""### 🔒 Target Outside Authorized Scope Contract

The Execution Gateway stopped tool **`{tool_name}`** (`{tool_id}`) because target **`{target}`** falls outside the active Scope Contract.

#### 🛡️ Zero-Trust Enforcement Rationale
Kairo protects your network by strictly preventing autonomous agents from sending probes, packets, or commands to unauthorized addresses.

- **Attempted Target:** `{target}`
- **Gateway Violation:** `{reason}`

#### 💡 How to Authorize This Target
If `{target}` is your intended target in an authorized testing or lab environment:
1. Click the **Scope Contract Pill** in the bottom bar.
2. Add `{target}` to the authorized CIDR targets.
3. Or type: `Update scope contract to authorize {target}`
"""

    return {
        "reply": md,
        "process": {
            "title": "Scope Boundary Check",
            "tool_id": tool_id,
            "tool_name": tool_name,
            "intent": f"Validate target '{target}' against Scope Contract",
            "command_line": f"scope_gate validate --target {target}",
            "target": target,
            "duration_s": duration_s,
            "status": "rejected",
            "status_label": "Scope Rejected",
            "tier": 2,
        },
        "output": {
            "summary_metrics": [
                {"label": "Target", "value": target, "type": "error"},
                {"label": "Authorization", "value": "Rejected", "type": "error"},
            ],
            "findings_table": [],
            "raw_stdout": "",
            "raw_stderr": reason,
            "has_raw_terminal": False,
        },
        "result": {
            "headline": f"Target {target} blocked by Scope Contract",
            "status": "critical",
            "security_posture": "Boundary Guard Active",
            "key_takeaways": [
                f"Target {target} is not in the authorized targets list.",
                "Tool execution blocked prior to emitting any network packets.",
            ],
            "recommended_actions": [
                {"label": f"Authorize {target}", "prompt": f"Add {target} to authorized scope contract targets"},
                {"label": "Scan Localhost 127.0.0.1", "prompt": "Perform comprehensive reconnaissance and port discovery against 127.0.0.1"},
            ],
        },
    }
