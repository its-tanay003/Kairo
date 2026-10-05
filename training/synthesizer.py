"""
SFT Conversation Synthesizer for Kairo Data Pipeline (Task 3.1).
Converts harvested ToolSpecs, event triples, and counterfactual recovery chains
into validated SFT conversation examples matching the standard format:
{user_goal, task_graph, tool_call, observation, next_step, conversation, metadata}
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from events.db import get_tool_tier
from training.harvest import EventTriple, RecoveryChain, ToolSpecDoc

logger = logging.getLogger("training.synthesizer")

# Standard System Prompt for Tool-Calling Agent Core
SYSTEM_PROMPT = """You are Kairo Agent Core, an autonomous security planner and tool execution engine bounded by a strict Scope Contract.
Your role: Given a security goal and task graph context, select the optimal tool, generate schema-valid arguments, execute within scope boundaries, interpret observations, and autonomously recover from failures."""

# Common Authorized Targets in Lab Scope
LAB_TARGETS = [
    {"ip": "192.168.1.50", "host": "vuln-target.internal", "url": "http://192.168.1.50"},
    {"ip": "192.168.1.10", "host": "app-server.internal", "url": "http://192.168.1.10:8080"},
    {"ip": "192.168.56.101", "host": "metasploit-lab.internal", "url": "http://192.168.56.101"},
    {"ip": "127.0.0.1", "host": "localhost", "url": "http://127.0.0.1:3000"},
    {"ip": "10.0.0.45", "host": "staging.corp.internal", "url": "https://staging.corp.internal"},
    {"ip": "192.168.1.25", "host": "db-primary.internal", "url": "http://192.168.1.25"},
]

COMMON_WORDLISTS = [
    "/usr/share/wordlists/dirb/common.txt",
    "/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt",
    "/usr/share/seclists/Discovery/Web-Content/raft-small-words.txt",
    "/usr/share/wordlists/rockyou-top500.txt",
]


@dataclass
class SFTExample:
    id: str
    source_type: str  # "event_store_triple" | "counterfactual_recovery" | "toolspec_scenario"
    user_goal: str
    task_graph: Dict[str, Any]
    tool_call: Dict[str, Any]
    observation: str
    next_step: str
    conversation: List[Dict[str, Any]]
    scope_contract: Dict[str, Any]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SFTDataSynthesizer:
    """Transforms raw harvested artifacts into diverse, high-quality SFT conversation datasets."""

    def __init__(self, toolspecs: Dict[str, ToolSpecDoc]):
        self.toolspecs = toolspecs
        self.rng = random.Random(42)  # Deterministic seed for reproducible generation

    def synthesize_all(
        self,
        event_triples: List[EventTriple],
        recovery_chains: List[RecoveryChain],
        target_total_count: int = 2500,
    ) -> List[SFTExample]:
        examples: List[SFTExample] = []

        # 1. Guaranteed baseline: Generate ToolSpec scenarios ensuring 100% of the 18 tools are covered
        min_scenarios = max(len(self.toolspecs) * 3, int(target_total_count * 0.45))
        logger.info(f"Generating baseline of {min_scenarios} scenarios to guarantee 100% tool coverage...")
        scenario_examples = self._generate_toolspec_scenarios(count=min_scenarios)
        examples.extend(scenario_examples)

        # 2. Convert Event Store Triples
        logger.info(f"Synthesizing from raw event triples...")
        triple_examples = self._convert_event_triples(event_triples)
        max_triples = min(len(triple_examples), max(10, int(target_total_count * 0.25)))
        examples.extend(triple_examples[:max_triples])
        logger.info(f"Added {max_triples} event triple examples.")

        # 3. Convert Counterfactual Recovery Chains
        max_rec = min(700, max(10, int(target_total_count * 0.3)))
        logger.info(f"Synthesizing from counterfactual recovery chains (target: {max_rec})...")
        recovery_examples = self._convert_recovery_chains(recovery_chains, target_count=max_rec)
        examples.extend(recovery_examples)
        logger.info(f"Added {len(recovery_examples)} counterfactual recovery examples.")

        # 4. Fill remainder with additional diverse scenarios to reach exact target_total_count
        needed = target_total_count - len(examples)
        if needed > 0:
            logger.info(f"Adding {needed} additional diverse scenario examples to reach target...")
            examples.extend(self._generate_toolspec_scenarios(count=needed))

        # Shuffle deterministically
        self.rng.shuffle(examples)
        return examples

    # --------------------------------------------------------------------------
    # 1. Event Store Triples Conversion
    # --------------------------------------------------------------------------
    def _convert_event_triples(self, triples: List[EventTriple]) -> List[SFTExample]:
        results: List[SFTExample] = []
        for idx, tr in enumerate(triples):
            tool_id = tr.tool_call.get("tool_id")
            if not tool_id or tool_id not in self.toolspecs:
                continue

            args = dict(tr.tool_call.get("arguments", {}))
            spec = self.toolspecs[tool_id]

            # Ensure all required inputs are present
            self._ensure_required_inputs(tool_id, args)

            node_id = tr.task_graph.get("current_node", f"node_{idx}")
            label = tr.task_graph.get("label", spec.name)
            cap = tr.task_graph.get("capability", spec.capabilities[0] if spec.capabilities else "execution")

            obs_str = json.dumps(tr.outcome, ensure_ascii=False)
            next_step = self._infer_next_step(spec.category, tr.outcome.get("status") == "success")

            call_id = f"call_{uuid.uuid4().hex[:8]}"
            conversation = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Goal: {tr.goal}\nTask Node: {label} (ID: {node_id})\nRequired Capability: {cap}",
                },
                {
                    "role": "assistant",
                    "content": f"Selected tool '{tool_id}' (Tier {spec.tier}, {spec.noise_level} noise) to fulfill capability '{cap}'. Emitting tool execution call.",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_id,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_id,
                    "content": obs_str,
                },
                {
                    "role": "assistant",
                    "content": f"Execution of {tool_id} completed with exit code {tr.outcome.get('exit_code', 0)}. Result: {tr.outcome.get('result_summary', 'Success')}. Transitioning to {next_step}.",
                },
            ]

            results.append(
                SFTExample(
                    id=f"kairo_sft_triple_{idx:05d}",
                    source_type="event_store_triple",
                    user_goal=tr.goal,
                    task_graph=tr.task_graph,
                    tool_call={
                        "tool_id": tool_id,
                        "arguments": args,
                        "tier": spec.tier,
                    },
                    observation=obs_str,
                    next_step=next_step,
                    conversation=conversation,
                    scope_contract={
                        "network_scope": "authorized_lab",
                        "allowed_tool_tiers": [1, 2, 3],
                    },
                    metadata={
                        "session_id": tr.session_id,
                        "parent_event": tr.parent_event,
                        "is_recovery": bool(tr.parent_event),
                    },
                )
            )

        return results

    # --------------------------------------------------------------------------
    # 2. Counterfactual Recovery Conversion
    # --------------------------------------------------------------------------
    def _convert_recovery_chains(
        self, base_chains: List[RecoveryChain], target_count: int = 700
    ) -> List[SFTExample]:
        results: List[SFTExample] = []
        if not base_chains:
            return results

        idx = 0
        while len(results) < target_count:
            base = self.rng.choice(base_chains)
            target_obj = self.rng.choice(LAB_TARGETS)

            bad_tool = base.bad_attempt["tool"]
            corr_tool = base.corrected_attempt["tool"]
            strategy = base.strategy

            bad_args = dict(base.bad_attempt.get("args") or {})
            corr_args = dict(base.corrected_attempt.get("args") or {})

            # Standardize and adapt arguments
            self._adapt_tool_args(bad_tool, bad_args, target_obj)
            self._adapt_tool_args(corr_tool, corr_args, target_obj)

            bad_call_id = f"call_{uuid.uuid4().hex[:8]}"
            corr_call_id = f"call_{uuid.uuid4().hex[:8]}"

            bad_obs = {
                "exit_code": base.bad_attempt.get("exit_code", 1),
                "error": base.bad_attempt.get("failure_reason", "Command failed"),
                "status": "failed",
            }
            corr_obs = {
                "exit_code": 0,
                "status": "success",
                "result_summary": base.verified_result.get("result_summary", "Autonomous recovery succeeded."),
                "facts": base.verified_result.get("facts", {}),
            }

            conversation = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Goal: {base.goal} (Target: {target_obj['ip']})\nCapability: {base.capability}",
                },
                {
                    "role": "assistant",
                    "content": f"Attempting initial execution using tool '{bad_tool}'.",
                    "tool_calls": [
                        {
                            "id": bad_call_id,
                            "type": "function",
                            "function": {
                                "name": bad_tool,
                                "arguments": json.dumps(bad_args),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": bad_call_id,
                    "name": bad_tool,
                    "content": json.dumps(bad_obs),
                },
                {
                    "role": "assistant",
                    "content": f"CRITIC INTERVENTION: Tool '{bad_tool}' failed with exit code {bad_obs['exit_code']} ({bad_obs['error']}).\n"
                    f"Applying recovery strategy '{strategy}': {base.recovery_action}.\n"
                    f"Executing corrected tool call with '{corr_tool}'.",
                    "tool_calls": [
                        {
                            "id": corr_call_id,
                            "type": "function",
                            "function": {
                                "name": corr_tool,
                                "arguments": json.dumps(corr_args),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": corr_call_id,
                    "name": corr_tool,
                    "content": json.dumps(corr_obs),
                },
                {
                    "role": "assistant",
                    "content": f"Recovery successful! {corr_tool} succeeded without error. Discovered facts verified. Transitioning to next DAG assessment node.",
                },
            ]

            results.append(
                SFTExample(
                    id=f"kairo_sft_rec_{idx:05d}",
                    source_type="counterfactual_recovery",
                    user_goal=base.goal,
                    task_graph={
                        "plan_id": f"plan_recovery_{idx:03d}",
                        "current_node": f"node_rec_{idx}",
                        "capability": base.capability,
                        "recovery_strategy": strategy,
                        "healed": True,
                    },
                    tool_call={
                        "tool_id": corr_tool,
                        "arguments": corr_args,
                        "tier": get_tool_tier(corr_tool),
                    },
                    observation=json.dumps(corr_obs),
                    next_step="node_subsequent_assessment",
                    conversation=conversation,
                    scope_contract={
                        "network_scope": "authorized_lab",
                        "allowed_tool_tiers": [1, 2, 3],
                    },
                    metadata={
                        "strategy": strategy,
                        "bad_attempt": base.bad_attempt,
                        "recovery_action": base.recovery_action,
                        "is_recovery": True,
                    },
                )
            )
            idx += 1

        return results

    # --------------------------------------------------------------------------
    # 3. High-Diversity ToolSpec Scenario Generation
    # --------------------------------------------------------------------------
    def _generate_toolspec_scenarios(self, count: int) -> List[SFTExample]:
        results: List[SFTExample] = []
        tool_ids = list(self.toolspecs.keys())
        if not tool_ids:
            return results

        for idx in range(count):
            tool_id = tool_ids[idx % len(tool_ids)] if idx < len(tool_ids) * 2 else self.rng.choice(tool_ids)
            spec = self.toolspecs[tool_id]
            target_obj = self.rng.choice(LAB_TARGETS)

            goal, args, obs, cap = self._synthesize_tool_scenario(spec, target_obj)
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            next_step = self._infer_next_step(spec.category, True)

            conversation = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Goal: {goal}\nTarget Asset: {target_obj['ip']}\nRequired Capability: {cap}",
                },
                {
                    "role": "assistant",
                    "content": f"Selected tool '{tool_id}' (Tier {spec.tier}, Noise Rating {spec.noise_level}) to satisfy '{cap}'. Emitting tool execution request.",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_id,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_id,
                    "content": json.dumps(obs),
                },
                {
                    "role": "assistant",
                    "content": f"Completed execution of {tool_id}. Observation verified: {obs.get('summary', 'Execution succeeded')}. Moving to next phase: {next_step}.",
                },
            ]

            results.append(
                SFTExample(
                    id=f"kairo_sft_synth_{idx:05d}",
                    source_type="toolspec_scenario",
                    user_goal=goal,
                    task_graph={
                        "plan_id": f"plan_synth_{idx:04d}",
                        "current_node": f"node_synth_{idx}",
                        "capability": cap,
                        "category": spec.category,
                        "status": "success",
                    },
                    tool_call={
                        "tool_id": tool_id,
                        "arguments": args,
                        "tier": spec.tier,
                    },
                    observation=json.dumps(obs),
                    next_step=next_step,
                    conversation=conversation,
                    scope_contract={
                        "network_scope": "authorized_lab",
                        "allowed_tool_tiers": [1, 2, 3],
                    },
                    metadata={
                        "category": spec.category,
                        "tier": spec.tier,
                        "is_recovery": False,
                    },
                )
            )

        return results

    # --------------------------------------------------------------------------
    # Helper: Adapt tool arguments to target and schema
    # --------------------------------------------------------------------------
    def _adapt_tool_args(self, tool_id: str, args: Dict[str, Any], target_obj: Dict[str, str]) -> None:
        if tool_id in ("ffuf.fuzz.v1", "gobuster.dir.v1"):
            args["url"] = f"{target_obj['url']}/admin/FUZZ" if tool_id == "ffuf.fuzz.v1" else f"{target_obj['url']}/admin"
            if "wordlist" not in args:
                args["wordlist"] = "/usr/share/wordlists/dirb/common.txt"
        elif tool_id == "whatweb.scan.v1":
            args["url"] = target_obj["url"]
            args.pop("target", None)
        elif tool_id == "nikto.scan.v1":
            args["host"] = target_obj["ip"]
            args.pop("target", None)
            args["port"] = 80
        elif tool_id == "sqlmap.scan.v1":
            args["url"] = f"{target_obj['url']}/login.php"
        elif tool_id == "hydra.brute.v1":
            args["target"] = target_obj["ip"]
            args["protocol"] = "ssh"
            if "username" not in args:
                args["username"] = "admin"
        elif tool_id == "nmap.scan.v1":
            args["target"] = target_obj["ip"]
        elif tool_id == "exiftool.extract.v1":
            args["file_path"] = "/var/tmp/backup_archive.pdf"
            args.pop("filepath", None)
        elif tool_id == "hashid.identify.v1":
            args["hash"] = "098f6bcd4621d373cade4e832627b4f6"
            args.pop("hash_string", None)
        elif tool_id == "dig.lookup.v1":
            args["target"] = target_obj["host"]
            args.pop("domain", None)
        elif tool_id == "whois.lookup.v1":
            args["target"] = target_obj["host"]
        elif tool_id == "kali.exec.v1":
            if "command" not in args:
                args["command"] = "uname -a"
        elif tool_id == "shell.run.v1":
            if "command" not in args:
                args["command"] = "python -c 'print(\"ready\")'"
        elif tool_id == "hello_world":
            if "message" not in args:
                args["message"] = f"Hello Kairo on {target_obj['ip']}"
        elif tool_id == "tcpdump.capture.v1":
            if "interface" not in args:
                args["interface"] = "eth0"
        elif tool_id == "metasploit.rpc.v1":
            args["module"] = "auxiliary/scanner/http/dir_scanner"
            args["rhosts"] = target_obj["ip"]

    def _ensure_required_inputs(self, tool_id: str, args: Dict[str, Any]) -> None:
        target_obj = LAB_TARGETS[0]
        self._adapt_tool_args(tool_id, args, target_obj)

    # --------------------------------------------------------------------------
    # Tool-Specific Parameter & Observation Synthesizers
    # --------------------------------------------------------------------------
    def _synthesize_tool_scenario(
        self, spec: ToolSpecDoc, target: Dict[str, str]
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
        t_id = spec.tool_id
        cap = spec.capabilities[0] if spec.capabilities else "execution"

        if t_id == "nmap.scan.v1":
            ports = self.rng.choice(["1-1000", "22,80,443,3306,8080", "1-65535", "top-100"])
            scan_type = self.rng.choice(["-sS", "-sT", "-sV", "-sC"])
            goal = f"Perform {scan_type} network port discovery against target {target['ip']}"
            args = {
                "target": target["ip"],
                "ports": ports,
                "scan_type": scan_type,
            }
            obs = {
                "exit_code": 0,
                "open_ports": [22, 80, 443],
                "services": {"22": "OpenSSH 8.2p1", "80": "Apache httpd 2.4.41", "443": "ssl/http"},
                "summary": f"Discovered 3 open ports on {target['ip']}",
            }
            return goal, args, obs, "port_scan"

        elif t_id == "ffuf.fuzz.v1":
            wlist = self.rng.choice(COMMON_WORDLISTS)
            threads = self.rng.choice([10, 20, 40])
            goal = f"Enumerate hidden web application routes and administrative scripts on {target['url']}"
            args = {
                "url": f"{target['url']}/FUZZ",
                "wordlist": wlist,
                "threads": threads,
                "filter_status": "404",
            }
            obs = {
                "exit_code": 0,
                "results": [
                    {"url": f"{target['url']}/admin", "status": 200, "length": 4512},
                    {"url": f"{target['url']}/login.php", "status": 200, "length": 2189},
                    {"url": f"{target['url']}/api", "status": 301, "length": 182},
                ],
                "summary": "Discovered 3 valid endpoints via FFUF fuzzing",
            }
            return goal, args, obs, "directory_enumeration"

        elif t_id == "gobuster.dir.v1":
            goal = f"Execute directory enumeration on {target['url']} using gobuster"
            args = {
                "url": target["url"],
                "wordlist": "/usr/share/wordlists/dirb/common.txt",
                "threads": 15,
            }
            obs = {
                "exit_code": 0,
                "discovered": ["/admin", "/robots.txt", "/images"],
                "summary": "Gobuster discovered 3 routes",
            }
            return goal, args, obs, "directory_enumeration"

        elif t_id == "whatweb.scan.v1":
            goal = f"Fingerprint web server software, headers, and CMS frameworks for {target['url']}"
            args = {
                "url": target["url"],
                "aggression": self.rng.choice([1, 2, 3]),
            }
            obs = {
                "exit_code": 0,
                "plugins": {
                    "HTTPServer": ["Apache/2.4.41 (Ubuntu)"],
                    "PHP": ["7.4.3"],
                    "X-Powered-By": ["PHP/7.4.3"],
                },
                "summary": f"Target {target['url']} is running Apache 2.4.41 with PHP 7.4.3",
            }
            return goal, args, obs, "technology_fingerprinting"

        elif t_id == "sqlmap.scan.v1":
            param = self.rng.choice(["id", "category", "search", "user_id"])
            goal = f"Test URL parameter '{param}' for SQL injection vulnerabilities on {target['url']}/search.php"
            args = {
                "url": f"{target['url']}/search.php?{param}=1",
                "level": self.rng.choice([1, 2]),
                "risk": 1,
            }
            obs = {
                "exit_code": 0,
                "vulnerable": True,
                "dbms": "MySQL >= 8.0",
                "injection_types": ["Boolean-based blind", "Time-based blind"],
                "summary": f"Parameter '{param}' is vulnerable to MySQL blind SQL injection",
            }
            return goal, args, obs, "sql_injection_detection"

        elif t_id == "nikto.scan.v1":
            goal = f"Run web vulnerability and security misconfiguration audit against {target['ip']}"
            args = {
                "host": target["ip"],
                "port": 80,
                "timeout": 30,
            }
            obs = {
                "exit_code": 0,
                "items": [
                    "Retrieved X-Powered-By header: PHP/7.4.3",
                    "The anti-clickjacking X-Frame-Options header is not present.",
                    "The X-Content-Type-Options header is not set.",
                ],
                "summary": "Nikto identified 3 web misconfiguration findings",
            }
            return goal, args, obs, "web_vulnerability_scan"

        elif t_id == "searchsploit.search.v1":
            query = self.rng.choice(["Apache 2.4.41", "OpenSSH 8.2", "WordPress 5.8", "vsftpd 2.3.4", "MySQL 8.0"])
            goal = f"Query exploit database for known public vulnerabilities affecting '{query}'"
            args = {
                "query": query,
            }
            obs = {
                "exit_code": 0,
                "exploits": [
                    {"title": f"{query} - Remote Code Execution", "edb_id": "49821", "type": "remote"},
                    {"title": f"{query} - Privilege Escalation", "edb_id": "48119", "type": "local"},
                ],
                "summary": f"Found 2 potential public exploits for {query}",
            }
            return goal, args, obs, "exploit_search"

        elif t_id == "hydra.brute.v1":
            service = self.rng.choice(["ssh", "ftp", "http-get"])
            goal = f"Audit password resilience on {target['ip']} {service.upper()} service against default credentials"
            args = {
                "target": target["ip"],
                "protocol": service,
                "username": "admin",
                "password_list": "/usr/share/wordlists/rockyou-top500.txt",
                "tasks": 4,
            }
            obs = {
                "exit_code": 0,
                "valid_credentials": [{"login": "admin", "password": "password123"}],
                "summary": f"Hydra found valid credential on {service} service",
            }
            return goal, args, obs, "password_brute_force"

        elif t_id == "exiftool.extract.v1":
            goal = f"Extract EXIF and document metadata from uploaded backup file 'backup_archive.pdf'"
            args = {
                "file_path": "/var/tmp/backup_archive.pdf",
            }
            obs = {
                "exit_code": 0,
                "metadata": {
                    "Creator": "admin@kairo.internal",
                    "Software": "LibreOffice 7.0",
                    "Author": "Tanay Lead Architect",
                },
                "summary": "Extracted internal author and software details from file metadata",
            }
            return goal, args, obs, "metadata_extraction"

        elif t_id == "hashid.identify.v1":
            sample_hash = self.rng.choice([
                "098f6bcd4621d373cade4e832627b4f6",  # MD5
                "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",  # SHA256
                "$2y$12$DHYtNqI3L1N6K6lqB4rGkO",  # Bcrypt
            ])
            goal = f"Identify cryptographic hash algorithm and Hashcat cracking mode for extracted token '{sample_hash[:16]}...'"
            args = {
                "hash": sample_hash,
            }
            obs = {
                "exit_code": 0,
                "possible_modes": ["MD5 (Mode 0)", "NTLM (Mode 1000)"] if len(sample_hash) == 32 else ["SHA-256 (Mode 1400)"],
                "summary": "Hash algorithm identified successfully",
            }
            return goal, args, obs, "hash_identification"

        elif t_id == "dig.lookup.v1":
            goal = f"Query DNS A and MX records for target domain {target['host']}"
            args = {
                "target": target["host"],
                "record_type": "A",
            }
            obs = {
                "exit_code": 0,
                "records": [target["ip"]],
                "summary": f"Resolved {target['host']} to {target['ip']}",
            }
            return goal, args, obs, "dns_resolution"

        elif t_id == "whois.lookup.v1":
            goal = f"Perform WHOIS registration lookup for target domain {target['host']}"
            args = {
                "target": target["host"],
            }
            obs = {
                "exit_code": 0,
                "registrar": "Example Registrar LLC",
                "created_date": "2021-03-15",
                "summary": f"WHOIS data retrieved for {target['host']}",
            }
            return goal, args, obs, "domain_registration_lookup"

        elif t_id == "tcpdump.capture.v1":
            goal = f"Capture raw network packets on interface eth0 with BPF filter 'tcp port 80'"
            args = {
                "interface": "eth0",
                "count": 50,
                "filter": "tcp port 80",
            }
            obs = {
                "exit_code": 0,
                "captured_packets": 50,
                "summary": "Captured 50 TCP HTTP packets on eth0",
            }
            return goal, args, obs, "packet_capture"

        elif t_id == "kali.exec.v1":
            cmd = self.rng.choice(["id", "uname -a", "ip a", "ss -tlpn"])
            goal = f"Execute diagnostic command '{cmd}' inside isolated Kali Linux VM sandbox"
            args = {
                "command": cmd,
                "snapshot_before": True,
            }
            obs = {
                "exit_code": 0,
                "stdout": f"uid=1000(kali) gid=1000(kali) groups=1000(kali),27(sudo)",
                "summary": f"Command '{cmd}' executed successfully in guest sandbox",
            }
            return goal, args, obs, "vm_snapshot_isolation"

        elif t_id == "metasploit.rpc.v1":
            goal = f"Launch auxiliary scanner 'scanner/http/dir_scanner' on {target['ip']}"
            args = {
                "module": "auxiliary/scanner/http/dir_scanner",
                "rhosts": target["ip"],
                "rport": 80,
            }
            obs = {
                "exit_code": 0,
                "discovered": ["/admin/ (301)", "/doc/ (200)"],
                "summary": "MSF auxiliary scanner completed",
            }
            return goal, args, obs, "vulnerability_scanning"

        elif t_id == "hello_world":
            goal = f"Verify communication boundary with hello_world on {target['ip']}"
            args = {"message": f"Hello Kairo on {target['ip']}"}
            obs = {"exit_code": 0, "summary": "Boundary verification success"}
            return goal, args, obs, "greeting"

        elif t_id == "system_ping":
            goal = f"Run system ping health check on {target['ip']}"
            args = {"echo_token": "ping_check_01"}
            obs = {"exit_code": 0, "summary": "System alive and responsive"}
            return goal, args, obs, "diagnostic"

        else:
            # shell.run.v1
            goal = f"Execute supervised diagnostic command on {target['ip']}"
            args = {"command": f"python -c 'print(\"target {target['ip']} active\")'"}
            obs = {"exit_code": 0, "summary": f"target {target['ip']} active"}
            return goal, args, obs, cap

    def _infer_next_step(self, category: str, success: bool) -> str:
        if not success:
            return "node_recovery_agent"
        cat_lower = category.lower()
        if "recon" in cat_lower or "dns" in cat_lower:
            return "node_service_fingerprinting"
        elif "service" in cat_lower or "port" in cat_lower:
            return "node_web_enumeration"
        elif "fuzz" in cat_lower or "web" in cat_lower:
            return "node_vulnerability_analysis"
        elif "vuln" in cat_lower or "sql" in cat_lower:
            return "node_exploit_correlation"
        elif "exploit" in cat_lower or "brute" in cat_lower:
            return "node_evidence_synthesis"
        return "node_security_report"
