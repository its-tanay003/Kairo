"""
Kairo Preference Pair Generator for Task-Graph Alignment (DPO / Preference Learning).

Authors grounded preference pairs (better vs. worse plans) comparing the agent's
task-graph choices across:
1. Phased reconnaissance before active exploitation vs. blind aggressive scanning
2. Scope Contract & tier compliance vs. unauthorized / noisy tool execution
3. Bounded concurrency & rate limiting vs. WAF throttling & socket exhaustion
4. Explicit error recovery branches vs. unhandled failures and blind continuation
5. Cryptographic evidence linking (SHA-256) vs. ephemeral / unverified outputs
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("training.preferences")


@dataclass
class PreferencePair:
    id: str
    scenario: str
    user_goal: str
    target: Dict[str, str]
    prompt: str
    chosen: str          # Better plan (structured DAG, scoped, verified, recovery-aware)
    rejected: str        # Worse plan (flat, noisy, unhandled errors, out-of-scope)
    task_graph_comparison: Dict[str, Any]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskGraphPreferenceAuthor:
    """Generates structured preference pairs comparing agent task-graph choices."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def generate_all(self, count_per_category: int = 60) -> List[PreferencePair]:
        pairs: List[PreferencePair] = []
        generators = [
            self._web_vulnerability_pairs,
            self._network_audit_pairs,
            self._auth_and_browser_pairs,
            self._dast_pipeline_pairs,
            self._packet_inspection_pairs,
            self._gui_workflow_pairs,
        ]

        pair_idx = 0
        for gen in generators:
            cat_pairs = gen(count=count_per_category, start_idx=pair_idx)
            pairs.extend(cat_pairs)
            pair_idx += len(cat_pairs)

        logger.info(f"Generated {len(pairs)} preference pairs across {len(generators)} categories.")
        return pairs

    # --------------------------------------------------------------------------
    # 1. Web Vulnerability Assessment Preference Pairs
    # --------------------------------------------------------------------------
    def _web_vulnerability_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.50", "host": "app-stage.internal", "url": "http://192.168.1.50"},
            {"ip": "10.0.0.45", "host": "corp-portal.internal", "url": "https://corp-portal.internal"},
            {"ip": "192.168.56.101", "host": "metasploit-lab.internal", "url": "http://192.168.56.101"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_web_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Assess web application on {t['url']} for input validation vulnerabilities and hidden routes.\n"
                f"Scope Contract: Authorized targets only ({t['ip']}), allowed tool tiers: [1, 2]. Max concurrency: 20 threads.\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_{start_idx + i}",
                "strategy": "PHASED_DISCOVERY_THROTTLED_SCAN_VERIFIED_EVIDENCE",
                "nodes": [
                    {
                        "node_id": "step_1_recon",
                        "capability": "web_technology_fingerprint",
                        "tool": "whatweb.scan.v1",
                        "args": {"url": t["url"]},
                        "tier": 1,
                        "dependencies": [],
                    },
                    {
                        "node_id": "step_2_fuzz",
                        "capability": "web_directory_enumeration",
                        "tool": "ffuf.fuzz.v1",
                        "args": {"url": f"{t['url']}/FUZZ", "threads": 15, "wordlist": "/usr/share/wordlists/dirb/common.txt"},
                        "tier": 2,
                        "dependencies": ["step_1_recon"],
                    },
                    {
                        "node_id": "step_3_browser_xss",
                        "capability": "xss_testing",
                        "tool": "browser.security.v1",
                        "args": {"workflow": "xss_check", "target_url": f"{t['url']}/search.php", "selector": "#q", "payload": "<script>alert(1)</script>"},
                        "tier": 2,
                        "dependencies": ["step_2_fuzz"],
                    },
                ],
                "recovery_branches": [
                    {"on_failure": "ffuf.fuzz.v1:429", "action": "backoff_threads_to_5"},
                    {"on_failure": "browser.security.v1:waf_blocked", "action": "mutate_payload_to_img_tag"},
                ],
                "rationale": "Phased recon before fuzzing prevents blind requests. Bounded concurrency (15 threads) respects scope limits. Browser-based verification captures visual evidence.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_{start_idx + i}",
                "strategy": "UNCOORDINATED_AGGRESSIVE_DIRECT_INJECTION",
                "nodes": [
                    {
                        "node_id": "step_1_sqli",
                        "capability": "sql_injection_testing",
                        "tool": "sqlmap.scan.v1",
                        "args": {"url": t["url"], "extra_args": ["--batch", "--threads", "30"]},
                        "tier": 2,
                        "dependencies": [],
                    },
                    {
                        "node_id": "step_2_nikto",
                        "capability": "web_vulnerability_scan",
                        "tool": "nikto.scan.v1",
                        "args": {"host": t["ip"]},
                        "tier": 3,  # Scope violation!
                        "dependencies": [],
                    },
                ],
                "flaws": [
                    "Direct aggressive SQL injection without knowing active technologies or routes",
                    "Violates Scope Contract: Nikto (Tier 3) attempted when only Tiers 1-2 authorized",
                    "Thread concurrency (30) exceeds Scope limit (20)",
                    "No error recovery or fallback handlers",
                    "Zero visual or structured evidence linking",
                ],
            }

            chosen_text = (
                f"### Recommended Autonomous Task Graph\n"
                f"1. **Reconnaissance (`whatweb.scan.v1`)**: Fingerprint web server, CMS, and active frameworks at Tier 1 (passive/low noise).\n"
                f"2. **Throttled Fuzzing (`ffuf.fuzz.v1`)**: Discover valid routes using 15 threads (below scope cap of 20) with automated 429 backoff handler.\n"
                f"3. **Visual Verification (`browser.security.v1`)**: Execute visible browser walkthrough for reflected inputs with SHA-256 evidence logging.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Uncoordinated Execution Plan\n"
                f"Run SQLMap directly on the root URL with 30 threads, and run Nikto scan simultaneously:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="web_vulnerability_assessment",
                    user_goal=f"Assess web application on {t['url']} for input validation vulnerabilities and hidden routes",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "web_security",
                        "better_plan_strengths": ["scope_compliance", "phased_dag", "rate_limiting", "visual_evidence"],
                        "worse_plan_flaws": ["scope_violation", "unthrottled_concurrency", "missing_recon"],
                    },
                )
            )
        return pairs

    # --------------------------------------------------------------------------
    # 2. Network Service Audit Preference Pairs
    # --------------------------------------------------------------------------
    def _network_audit_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.10", "host": "app-server.internal", "url": "http://192.168.1.10"},
            {"ip": "192.168.1.25", "host": "db-primary.internal", "url": "http://192.168.1.25"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_net_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Perform network service audit on host {t['ip']}.\n"
                f"Scope Contract: Permitted subnet 192.168.1.0/24, allowed tool tiers: [1, 2]. Noise limit: medium.\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_net_{start_idx + i}",
                "strategy": "ICMP_TO_PORT_SCAN_TO_SERVICE_FINGERPRINT",
                "nodes": [
                    {"node_id": "n1_ping", "tool": "system_ping", "args": {"echo_token": "probe"}, "tier": 1, "dependencies": []},
                    {"node_id": "n2_portscan", "tool": "nmap.scan.v1", "args": {"target": t["ip"], "ports": "top-100", "scan_type": "-sS"}, "tier": 2, "dependencies": ["n1_ping"]},
                    {"node_id": "n3_service", "tool": "whatweb.scan.v1", "args": {"url": f"http://{t['ip']}:8080"}, "tier": 1, "dependencies": ["n2_portscan"]},
                ],
                "recovery_branches": [
                    {"on_failure": "n1_ping:timeout", "action": "try_arp_or_tcp_syn_ping"},
                ],
                "rationale": "Verifies host availability before launching syn port scan. Focuses on top-100 ports to stay within medium noise boundaries.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_net_{start_idx + i}",
                "strategy": "BLIND_ALL_PORTS_AND_BRUTE_FORCE",
                "nodes": [
                    {"node_id": "n1_full_nmap", "tool": "nmap.scan.v1", "args": {"target": t["ip"], "ports": "1-65535", "scan_type": "-sV -sC -T5"}, "tier": 2, "dependencies": []},
                    {"node_id": "n2_hydra", "tool": "hydra.brute.v1", "args": {"target": t["ip"], "protocol": "ssh", "tasks": 64}, "tier": 2, "dependencies": []},
                ],
                "flaws": [
                    "Scans 65535 ports at maximum timing (-T5) without verifying host status, generating extreme noise",
                    "Runs aggressive brute-force (64 tasks) simultaneously before verifying SSH port is even open",
                    "Causes firewall connection drop / IDS alert",
                ],
            }

            chosen_text = (
                f"### Recommended Phased Network Audit Plan\n"
                f"1. **Host Verification (`system_ping`)**: Non-intrusive reachability check.\n"
                f"2. **Scoped Port Scan (`nmap.scan.v1`)**: Top-100 ports scan under medium noise profile.\n"
                f"3. **Targeted Fingerprinting (`whatweb.scan.v1`)**: Fingerprint active services discovered.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Flawed High-Noise Plan\n"
                f"Scan all 65,535 ports at T5 speed and simultaneously run 64-thread brute force:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="network_service_audit",
                    user_goal=f"Perform network service audit on host {t['ip']}",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "network_security",
                        "better_plan_strengths": ["low_noise_recon", "dependency_ordering", "reachability_precheck"],
                        "worse_plan_flaws": ["extreme_noise", "concurrency_abuse", "missing_dependencies"],
                    },
                )
            )
        return pairs

    # --------------------------------------------------------------------------
    # 3. Authentication & Security Browser Preference Pairs
    # --------------------------------------------------------------------------
    def _auth_and_browser_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.50", "host": "target.local", "url": "http://target.local"},
            {"ip": "127.0.0.1", "host": "localhost", "url": "http://localhost:3000"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_auth_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Walkthrough user authentication on {t['url']}/login.php, audit session cookies, and intercept requests.\n"
                f"Scope Contract: Authorized targets ({t['host']}), tool tiers: [1, 2, 3].\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_auth_{start_idx + i}",
                "strategy": "VISIBLE_BROWSER_WALKTHROUGH_AND_BURP_PROXY_INTEGRATION",
                "nodes": [
                    {
                        "node_id": "step_1_launch_burp",
                        "tool": "burpsuite.gui.v1",
                        "args": {"workflow": "init_project", "params": {"project_name": "AuthAudit"}},
                        "tier": 3,
                        "dependencies": [],
                    },
                    {
                        "node_id": "step_2_browser_auth",
                        "tool": "browser.security.v1",
                        "args": {
                            "workflow": "auth_walkthrough",
                            "target_url": f"{t['url']}/login.php",
                            "username": "admin",
                            "password": "P@ssw0rd2026!",
                            "submit_selector": "button[type='submit']",
                        },
                        "tier": 2,
                        "dependencies": ["step_1_launch_burp"],
                    },
                    {
                        "node_id": "step_3_cookie_audit",
                        "tool": "browser.security.v1",
                        "args": {"workflow": "cookie_audit"},
                        "tier": 2,
                        "dependencies": ["step_2_browser_auth"],
                    },
                    {
                        "node_id": "step_4_proxy_history",
                        "tool": "burpsuite.gui.v1",
                        "args": {"workflow": "inspect_proxy_history", "params": {"host": t["host"]}},
                        "tier": 3,
                        "dependencies": ["step_2_browser_auth"],
                    },
                ],
                "rationale": "Uses visible Playwright security browser for authentic DOM interaction with cookies inspection, paired with Burp Suite proxy for full HTTP transaction audit.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_auth_{start_idx + i}",
                "strategy": "OPAQUE_HEADLESS_CURL_NO_COOKIES",
                "nodes": [
                    {
                        "node_id": "step_1_raw_curl",
                        "tool": "shell.run.v1",
                        "args": {"command": f"curl -X POST {t['url']}/login.php -d 'user=admin&pass=P@ssw0rd2026!'"},
                        "tier": 1,
                        "dependencies": [],
                    },
                ],
                "flaws": [
                    "Uses opaque curl without cookie jars or redirect handling",
                    "Fails to verify session cookie HttpOnly/Secure flags",
                    "Produces zero visual evidence in the Activity Rail",
                    "Cannot interact with dynamic JavaScript forms or single-page applications",
                ],
            }

            chosen_text = (
                f"### Recommended Visible Browser & Proxy Audit Plan\n"
                f"1. **Burp Suite Initialization (`burpsuite.gui.v1`)**: Pre-configure listener on 127.0.0.1:8080.\n"
                f"2. **Playwright Visible Walkthrough (`browser.security.v1`)**: Submit credentials, trace redirects, extract DOM snapshots.\n"
                f"3. **Cookie Flag Audit (`browser.security.v1`)**: Inspect HttpOnly, Secure, and SameSite attributes.\n"
                f"4. **Proxy History Inspection (`burpsuite.gui.v1`)**: Review captured transactions and export visual evidence.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Rejected Opaque Curl Plan\n"
                f"Execute a raw curl command without cookie tracking or visual verification:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="auth_and_browser_testing",
                    user_goal=f"Walkthrough user authentication on {t['url']}/login.php, audit session cookies, and intercept requests",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "browser_and_gui",
                        "better_plan_strengths": ["visible_state", "cookie_flag_audit", "gui_integration", "activity_rail_evidence"],
                        "worse_plan_flaws": ["opaque_execution", "missing_cookie_jar", "no_visual_evidence"],
                    },
                )
            )
        return pairs

    # --------------------------------------------------------------------------
    # 4. DAST Pipeline Preference Pairs
    # --------------------------------------------------------------------------
    def _dast_pipeline_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.50", "host": "target.local", "url": "http://target.local"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_dast_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Execute automated DAST assessment against {t['url']}.\n"
                f"Scope Contract: Authorized target {t['host']}, tool tiers: [1, 2, 3].\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_dast_{start_idx + i}",
                "strategy": "PIPELINED_SPIDER_THEN_ACTIVE_SCAN_WITH_DEPTH_LIMIT",
                "nodes": [
                    {"node_id": "n1_zap_spider", "tool": "zap.gui.v1", "args": {"workflow": "run_spider", "target_url": t["url"], "max_depth": 3}, "tier": 3, "dependencies": []},
                    {"node_id": "n2_zap_alerts", "tool": "zap.gui.v1", "args": {"workflow": "inspect_alerts"}, "tier": 3, "dependencies": ["n1_zap_spider"]},
                    {"node_id": "n3_zap_report", "tool": "zap.gui.v1", "args": {"workflow": "export_report", "format": "html"}, "tier": 3, "dependencies": ["n2_zap_alerts"]},
                ],
                "recovery_branches": [
                    {"on_failure": "zap.gui.v1:spider_recursion", "action": "apply_regex_exclusion_and_retry"},
                ],
                "rationale": "Constrained spider depth (3) avoids recursive loops. Sequential dependency ensures alerts are inspected only after crawling completes.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_dast_{start_idx + i}",
                "strategy": "CONCURRENT_CRAWL_AND_EXPLOIT_NO_LIMITS",
                "nodes": [
                    {"node_id": "n1_unbounded_spider", "tool": "zap.gui.v1", "args": {"workflow": "run_spider", "target_url": t["url"], "max_depth": 99}, "tier": 3, "dependencies": []},
                    {"node_id": "n2_blind_sqlmap", "tool": "sqlmap.scan.v1", "args": {"url": f"{t['url']}/", "extra_args": ["--crawl", "10", "--risk", "3", "--level", "5"]}, "tier": 2, "dependencies": []},
                ],
                "flaws": [
                    "Unbounded spider depth (99) leads to infinite crawling loops on dynamic calendars/session links",
                    "Runs aggressive Level 5 SQLMap crawl concurrently with ZAP, causing severe server load and socket exhaustion",
                    "No structured report export step",
                ],
            }

            chosen_text = (
                f"### Recommended Structured DAST Pipeline\n"
                f"1. **Bounded Spider (`zap.gui.v1`)**: Max depth 3 with recursion trap recovery handler.\n"
                f"2. **Alert Triaging (`zap.gui.v1`)**: Parse vulnerabilities categorized by risk level.\n"
                f"3. **Artifact Provenance (`zap.gui.v1`)**: Export HTML report with SHA-256 digest.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Flawed Unbounded DAST Plan\n"
                f"Launch unconstrained spider with depth 99 and run Level 5 SQLMap crawler simultaneously:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="dast_vulnerability_pipeline",
                    user_goal=f"Execute automated DAST assessment against {t['url']}",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "dast_security",
                        "better_plan_strengths": ["depth_limits", "sequential_phases", "report_generation"],
                        "worse_plan_flaws": ["infinite_recursion_risk", "server_exhaustion", "no_report_step"],
                    },
                )
            )
        return pairs

    # --------------------------------------------------------------------------
    # 5. Packet Inspection Preference Pairs
    # --------------------------------------------------------------------------
    def _packet_inspection_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.50", "host": "target.local", "url": "http://target.local"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_pcap_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Capture and analyze network traffic during an HTTP authentication handshake on {t['ip']}.\n"
                f"Scope Contract: Host {t['ip']}, allowed tool tiers: [1, 2, 3].\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_pcap_{start_idx + i}",
                "strategy": "FILTERED_CAPTURE_SYNCHRONIZED_WITH_TARGET_PROBE",
                "nodes": [
                    {"node_id": "p1_start_capture", "tool": "wireshark.gui.v1", "args": {"workflow": "start_capture", "interface": "eth0", "capture_filter": f"host {t['ip']} and tcp port 80"}, "tier": 3, "dependencies": []},
                    {"node_id": "p2_dispatch_probe", "tool": "whatweb.scan.v1", "args": {"url": f"http://{t['ip']}"}, "tier": 1, "dependencies": ["p1_start_capture"]},
                    {"node_id": "p3_stop_and_save", "tool": "wireshark.gui.v1", "args": {"workflow": "stop_and_save_pcap", "output_path": f"/evidence_artifacts/handshake_{start_idx + i}.pcap"}, "tier": 3, "dependencies": ["p2_dispatch_probe"]},
                ],
                "rationale": "Applies precise BPF capture filter before firing probe. Strictly stops capture after probe completes and registers PCAP with SHA-256.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_pcap_{start_idx + i}",
                "strategy": "UNFILTERED_INFINITE_CAPTURE",
                "nodes": [
                    {"node_id": "p1_infinite_wireshark", "tool": "wireshark.gui.v1", "args": {"workflow": "start_capture", "interface": "eth0"}, "tier": 3, "dependencies": []},
                ],
                "flaws": [
                    "No capture filter: captures arbitrary unrelated network traffic, leaking sensitive host data",
                    "No stop action or probe trigger: runs forever until disk fills up",
                    "No exported evidence file or cryptographic provenance",
                ],
            }

            chosen_text = (
                f"### Recommended Synchronized Packet Analysis Plan\n"
                f"1. **Start Filtered Capture (`wireshark.gui.v1`)**: Filter strictly on `host {t['ip']} and tcp port 80`.\n"
                f"2. **Dispatch Probe (`whatweb.scan.v1`)**: Trigger the traffic event.\n"
                f"3. **Stop & Save PCAP (`wireshark.gui.v1`)**: Terminate capture and register SHA-256 provenance in EvidenceStore.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Rejected Unfiltered Plan\n"
                f"Start Wireshark with no filter or stop condition:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="packet_capture_and_analysis",
                    user_goal=f"Capture and analyze network traffic during an HTTP authentication handshake on {t['ip']}",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "network_evidence",
                        "better_plan_strengths": ["bpf_capture_filter", "probe_synchronization", "pcap_provenance"],
                        "worse_plan_flaws": ["unfiltered_sniffing", "infinite_capture", "missing_pcap_export"],
                    },
                )
            )
        return pairs

    # --------------------------------------------------------------------------
    # 6. GUI Workflow Preference Pairs
    # --------------------------------------------------------------------------
    def _gui_workflow_pairs(self, count: int, start_idx: int) -> List[PreferencePair]:
        pairs = []
        targets = [
            {"ip": "192.168.1.50", "host": "target.local", "url": "http://target.local"},
        ]

        for i in range(count):
            t = targets[i % len(targets)]
            p_id = f"pref_gui_{start_idx + i:04d}"

            prompt = (
                f"User Goal: Use Burp Suite Repeater to craft and test SQL injection payloads on {t['host']}.\n"
                f"Scope Contract: Host {t['host']}, tool tiers: [1, 2, 3].\n"
                f"Provide an autonomous task graph plan."
            )

            chosen_plan = {
                "plan_id": f"plan_chosen_repeater_{start_idx + i}",
                "strategy": "INITIALIZE_PROJECT_SEND_TO_REPEATER_AND_INSPECT",
                "nodes": [
                    {"node_id": "b1_init", "tool": "burpsuite.gui.v1", "args": {"workflow": "init_project"}, "tier": 3, "dependencies": []},
                    {"node_id": "b2_send_repeater", "tool": "burpsuite.gui.v1", "args": {"workflow": "send_to_repeater", "params": {"host": t["host"], "url": "/api/v1/auth", "method": "POST", "body": "{\"user\":\"admin' OR '1'='1\"}"}}, "tier": 3, "dependencies": ["b1_init"]},
                ],
                "rationale": "Initializes Burp environment cleanly, routes payload through Repeater with bounded interaction, and verifies response snippet.",
            }

            rejected_plan = {
                "plan_id": f"plan_rejected_repeater_{start_idx + i}",
                "strategy": "DIRECT_REPEATER_WITHOUT_LIFECYCLE",
                "nodes": [
                    {"node_id": "b1_send_repeater", "tool": "burpsuite.gui.v1", "args": {"workflow": "send_to_repeater"}, "tier": 3, "dependencies": []},
                ],
                "flaws": [
                    "Attempts to send request to Repeater before launching or initializing Burp Suite project",
                    "Missing target parameters (host, url, body) required by schema",
                    "Causes unhandled null-reference exception in uninitialized UI state",
                ],
            }

            chosen_text = (
                f"### Recommended Burp Repeater Plan\n"
                f"1. **Initialize Project (`burpsuite.gui.v1`)**: Launch workspace with default proxy listener.\n"
                f"2. **Send to Repeater (`burpsuite.gui.v1`)**: Dispatch parameterized probe and capture screenshot evidence.\n\n"
                f"```json\n{json.dumps(chosen_plan, indent=2)}\n```"
            )

            rejected_text = (
                f"### Rejected Uninitialized Plan\n"
                f"Attempt to send to Repeater without initializing project or supplying target parameters:\n"
                f"```json\n{json.dumps(rejected_plan, indent=2)}\n```"
            )

            pairs.append(
                PreferencePair(
                    id=p_id,
                    scenario="gui_repeater_fuzzing",
                    user_goal=f"Use Burp Suite Repeater to craft and test SQL injection payloads on {t['host']}",
                    target=t,
                    prompt=prompt,
                    chosen=chosen_text,
                    rejected=rejected_text,
                    task_graph_comparison={"chosen": chosen_plan, "rejected": rejected_plan},
                    metadata={
                        "category": "gui_tools",
                        "better_plan_strengths": ["lifecycle_management", "schema_valid_parameters", "visual_evidence"],
                        "worse_plan_flaws": ["uninitialized_state", "missing_arguments"],
                    },
                )
            )
        return pairs


preference_author = TaskGraphPreferenceAuthor()
