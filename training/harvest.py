"""
Harvesting Engine for Kairo Data Pipeline (Task 3.1).
Harvests:
  (a) Every ToolSpec + its docs/man-page/--help text from registry/tools/
  (b) Every logged event from the Event Store (events/events.db) as a (goal, tool_call, outcome) triple
  (c) Counterfactual recovery chains as explicit (bad_attempt -> corrected_attempt -> verified_result) sequences
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Monorepo Root
ROOT_DIR = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT_DIR / "registry" / "tools"
DEFAULT_DB_PATH = ROOT_DIR / "events" / "events.db"

from events.db import get_tool_tier

logger = logging.getLogger("training.harvest")


# ==============================================================================
# (a) ToolSpec + Documentation / Man-Page Harvester
# ==============================================================================

@dataclass
class ToolSpecDoc:
    tool_id: str
    name: str
    version: str
    description: str
    category: str
    binary: str
    tier: int
    noise_level: str
    capabilities: List[str]
    inputs_schema: Dict[str, Any]
    required_inputs: List[str]
    outputs_schema: Dict[str, Any]
    command_template: Optional[str]
    man_page_text: str
    help_text: str
    examples: List[Dict[str, Any]]
    raw_spec: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ToolSpecHarvester:
    """Harvests all YAML ToolSpecs from the registry and synthesizes man-page/help documentation."""

    def __init__(self, registry_dir: Path = REGISTRY_DIR):
        self.registry_dir = Path(registry_dir)

    def harvest_all(self) -> Dict[str, ToolSpecDoc]:
        specs: Dict[str, ToolSpecDoc] = {}
        for yaml_path in sorted(self.registry_dir.glob("*.yaml")):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue

                tool_id = data.get("id") or yaml_path.stem.replace("_", ".")
                doc = self._build_doc(data, tool_id)
                specs[tool_id] = doc
            except Exception as e:
                logger.warning(f"Error parsing ToolSpec {yaml_path.name}: {e}")
        return specs

    def _build_doc(self, spec: Dict[str, Any], tool_id: str) -> ToolSpecDoc:
        name = spec.get("name", tool_id)
        version = spec.get("version", "1.0.0")
        description = spec.get("description", "")
        category = spec.get("category", "general")
        binary = spec.get("binary", tool_id.split(".")[0])
        tier = get_tool_tier(tool_id)
        noise_level = spec.get("noise_level", "low" if tier == 1 else ("medium" if tier == 2 else "high"))
        capabilities = spec.get("capabilities", [])

        inputs = spec.get("inputs", {})
        properties = inputs.get("properties", {})
        required = inputs.get("required", [])
        outputs = spec.get("outputs", {})
        cmd_template = spec.get("command_template")

        # Synthesize CLI man-page synopsis
        synopsis_args = []
        for prop_name, prop_data in properties.items():
            is_req = prop_name in required
            p_type = prop_data.get("type", "string")
            p_default = prop_data.get("default")
            arg_fmt = f"--{prop_name}=<{p_type}>"
            if not is_req:
                arg_fmt = f"[{arg_fmt}]"
            synopsis_args.append(arg_fmt)

        synopsis_str = f"{binary} " + " ".join(synopsis_args[:6])
        if len(synopsis_args) > 6:
            synopsis_str += " [OPTIONS...]"

        # Build Man-Page Text
        man_lines = [
            f"NAME",
            f"    {binary} - {name} (Version {version})",
            f"",
            f"SYNOPSIS",
            f"    {synopsis_str}",
            f"",
            f"DESCRIPTION",
            f"    {description}",
            f"    Category: {category.upper()} | Security Tier: {tier} | Noise Rating: {noise_level.upper()}",
            f"    Capabilities: {', '.join(capabilities)}",
            f"",
            f"OPTIONS & PARAMETERS",
        ]

        for p_name, p_data in properties.items():
            req_tag = "REQUIRED" if p_name in required else "OPTIONAL"
            p_desc = p_data.get("description", "No description provided.")
            p_type = p_data.get("type", "string")
            p_def = f" (default: {p_data.get('default')})" if "default" in p_data else ""
            enum_str = f" [Choices: {', '.join(str(x) for x in p_data.get('enum'))}]" if "enum" in p_data else ""
            man_lines.append(f"    --{p_name} <{p_type}> [{req_tag}]{p_def}{enum_str}")
            man_lines.append(f"        {p_desc}")

        man_page_text = "\n".join(man_lines)

        # Build CLI --help output
        help_lines = [
            f"Usage: {binary} [OPTIONS]",
            f"",
            f"{description}",
            f"",
            f"Options:",
        ]
        for p_name, p_data in properties.items():
            p_desc = p_data.get("description", "")
            p_def = f" [default: {p_data.get('default')}]" if "default" in p_data else ""
            help_lines.append(f"  --{p_name:<20} {p_desc}{p_def}")
        help_text = "\n".join(help_lines)

        # Generate realistic default example
        examples = []
        sample_args: Dict[str, Any] = {}
        for p_name, p_data in properties.items():
            if p_name in required:
                if p_data.get("type") == "string":
                    if "url" in p_name:
                        sample_args[p_name] = "http://192.168.1.50/"
                    elif "target" in p_name or "host" in p_name:
                        sample_args[p_name] = "192.168.1.50"
                    elif "command" in p_name:
                        sample_args[p_name] = "uname -a"
                    else:
                        sample_args[p_name] = "sample_value"
                elif p_data.get("type") == "integer":
                    sample_args[p_name] = p_data.get("default", 1)
                elif p_data.get("type") == "array":
                    sample_args[p_name] = []
            elif "default" in p_data and p_data["default"] not in ("", None, [], {}):
                sample_args[p_name] = p_data["default"]

        examples.append({
            "description": f"Standard {name} invocation",
            "arguments": sample_args,
        })

        return ToolSpecDoc(
            tool_id=tool_id,
            name=name,
            version=version,
            description=description,
            category=category,
            binary=binary,
            tier=tier,
            noise_level=noise_level,
            capabilities=capabilities,
            inputs_schema=properties,
            required_inputs=required,
            outputs_schema=outputs,
            command_template=cmd_template,
            man_page_text=man_page_text,
            help_text=help_text,
            examples=examples,
            raw_spec=spec,
        )


# ==============================================================================
# (b) Logged Events from Event Store as (goal, tool_call, outcome) Triples
# ==============================================================================

@dataclass
class EventTriple:
    triple_id: str
    session_id: str
    task_id: str
    goal: str
    task_graph: Dict[str, Any]
    tool_call: Dict[str, Any]
    outcome: Dict[str, Any]
    parent_event: Optional[str]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventStoreHarvester:
    """Harvests logged execution events from events.db into (goal, tool_call, outcome) triples."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def harvest_triples(self) -> List[EventTriple]:
        if not self.db_path.exists():
            logger.warning(f"Database {self.db_path} does not exist.")
            return []

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        triples: List[EventTriple] = []

        try:
            # Query events joined with task_graphs and task_nodes
            query = """
            SELECT 
                e.id AS event_id,
                e.session_id,
                e.task_id,
                e.timestamp,
                e.actor,
                e.tool_id,
                e.tool_version,
                e.requested_args,
                e.normalized_args,
                e.exit_code,
                e.result_summary,
                e.parent_event,
                g.plan_id,
                g.goal AS graph_goal,
                tn.node_id,
                tn.label AS node_label,
                tn.description AS node_desc,
                tn.capability AS node_cap,
                tn.dependencies AS node_deps,
                tn.status AS node_status,
                tn.result AS node_result
            FROM events e
            LEFT JOIN task_nodes tn ON (e.task_id = tn.node_id OR e.task_id = tn.plan_id)
            LEFT JOIN task_graphs g ON (tn.plan_id = g.plan_id OR e.session_id = g.session_id)
            WHERE e.tool_id IS NOT NULL AND e.tool_id != ''
            ORDER BY e.id ASC
            """
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()

            for r in rows:
                row_dict = dict(r)
                ev_id = str(row_dict["event_id"])
                tool_id = row_dict["tool_id"]

                # Parse arguments
                args_dict = {}
                raw_args = row_dict.get("normalized_args") or row_dict.get("requested_args")
                if raw_args:
                    if isinstance(raw_args, dict):
                        args_dict = raw_args
                    elif isinstance(raw_args, str):
                        try:
                            args_dict = json.loads(raw_args)
                        except Exception:
                            args_dict = {"raw": raw_args}

                # Construct Goal
                goal = row_dict.get("graph_goal")
                if not goal or not str(goal).strip():
                    if row_dict.get("node_desc"):
                        goal = row_dict["node_desc"]
                    elif row_dict.get("node_label"):
                        goal = f"Execute {row_dict['node_label']}"
                    else:
                        goal = f"Execute capability {row_dict.get('node_cap') or tool_id}"

                # Construct Task Graph context
                deps = []
                if row_dict.get("node_deps"):
                    try:
                        deps = json.loads(row_dict["node_deps"])
                    except Exception:
                        deps = []

                task_graph = {
                    "plan_id": row_dict.get("plan_id") or "plan_standalone",
                    "current_node": row_dict.get("node_id") or row_dict.get("task_id") or "node_01",
                    "label": row_dict.get("node_label") or tool_id,
                    "capability": row_dict.get("node_cap") or "security_execution",
                    "dependencies": deps,
                    "status": row_dict.get("node_status") or "completed",
                }

                # Construct Tool Call
                tool_call = {
                    "tool_id": tool_id,
                    "tool_version": row_dict.get("tool_version") or "1.0.0",
                    "arguments": args_dict,
                    "tier": get_tool_tier(tool_id),
                }

                # Construct Outcome
                outcome = {
                    "exit_code": row_dict.get("exit_code", 0),
                    "result_summary": row_dict.get("result_summary") or "Command completed successfully.",
                    "status": "success" if row_dict.get("exit_code") == 0 else "failed",
                }
                if row_dict.get("node_result"):
                    try:
                        outcome["details"] = json.loads(row_dict["node_result"])
                    except Exception:
                        pass

                triples.append(
                    EventTriple(
                        triple_id=f"triple_{ev_id}",
                        session_id=row_dict.get("session_id") or "session_default",
                        task_id=row_dict.get("task_id") or f"task_{ev_id}",
                        goal=goal,
                        task_graph=task_graph,
                        tool_call=tool_call,
                        outcome=outcome,
                        parent_event=str(row_dict["parent_event"]) if row_dict.get("parent_event") else None,
                        timestamp=str(row_dict.get("timestamp") or ""),
                    )
                )
        except Exception as e:
            logger.error(f"Error harvesting event triples from {self.db_path}: {e}")
        finally:
            conn.close()

        return triples


# ==============================================================================
# (c) Counterfactual Recovery Chains Harvester
# ==============================================================================

@dataclass
class RecoveryChain:
    chain_id: str
    goal: str
    capability: str
    strategy: str
    bad_attempt: Dict[str, Any]
    recovery_action: str
    corrected_attempt: Dict[str, Any]
    verified_result: Dict[str, Any]
    parent_event_link: Optional[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecoveryChainHarvester:
    """Harvests explicit (bad_attempt -> corrected_attempt -> verified_result) recovery sequences."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def harvest_chains(self) -> List[RecoveryChain]:
        chains: List[RecoveryChain] = []

        # 1. Harvest from real DB event lineages
        if self.db_path.exists():
            db_chains = self._harvest_from_db()
            chains.extend(db_chains)

        # 2. Add grounded counterfactual templates from Task 2.5 self-healing rules
        synthetic_chains = self._generate_grounded_counterfactual_chains()
        chains.extend(synthetic_chains)

        return chains

    def _harvest_from_db(self) -> List[RecoveryChain]:
        chains: List[RecoveryChain] = []
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Query task nodes with recovery_path in result
            cursor.execute("SELECT plan_id, node_id, capability, label, description, result FROM task_nodes WHERE result LIKE '%recovery_path%'")
            rows = cursor.fetchall()

            for r in rows:
                raw_res = r["result"]
                res_dict = {}
                try:
                    res_dict = json.loads(raw_res) if isinstance(raw_res, str) else raw_res
                except Exception:
                    continue

                rec_path = res_dict.get("recovery_path", [])
                if len(rec_path) >= 2:
                    step_fail = rec_path[0]
                    step_succ = rec_path[1]

                    chains.append(
                        RecoveryChain(
                            chain_id=f"chain_node_{r['plan_id']}_{r['node_id']}",
                            goal=r["description"] or f"Execute {r['label']}",
                            capability=r["capability"],
                            strategy="TOOL_SUBSTITUTION_AND_RATE_BACKOFF",
                            bad_attempt={
                                "tool": step_fail.get("tool") or "unknown_tool",
                                "args": step_fail.get("args") or {},
                                "exit_code": step_fail.get("exit_code", 124),
                                "failure_reason": step_fail.get("failure_reason") or "Timeout / rate limited",
                            },
                            recovery_action=step_succ.get("action_taken") or "Autonomously substitute tool and reduce thread concurrency",
                            corrected_attempt={
                                "tool": step_succ.get("tool") or "ffuf.fuzz.v1",
                                "args": step_succ.get("args") or {"threads": 5},
                                "exit_code": 0,
                            },
                            verified_result={
                                "status": "success",
                                "result_summary": res_dict.get("summary") or "Discovered administrative endpoints autonomously.",
                                "facts": res_dict.get("facts", {}),
                            },
                            parent_event_link=step_succ.get("parent_event"),
                            metadata={
                                "source": "database_task_nodes",
                                "plan_id": r["plan_id"],
                                "node_id": r["node_id"],
                            },
                        )
                    )

            # Query events table for parent_event pairs
            cursor.execute(
                """
                SELECT 
                    e2.id AS retry_id, e2.tool_id AS retry_tool, e2.requested_args AS retry_args, e2.exit_code AS retry_code, e2.result_summary AS retry_sum, e2.parent_event,
                    e1.tool_id AS fail_tool, e1.requested_args AS fail_args, e1.exit_code AS fail_code, e1.result_summary AS fail_sum
                FROM events e2
                JOIN events e1 ON e2.parent_event = CAST(e1.id AS TEXT)
                WHERE e1.exit_code != 0 AND e2.exit_code == 0
                """
            )
            ev_pairs = cursor.fetchall()
            for ep in ev_pairs:
                chains.append(
                    RecoveryChain(
                        chain_id=f"chain_ev_{ep['retry_id']}",
                        goal=f"Execute {ep['retry_tool']} with autonomous error correction",
                        capability="autonomous_recovery",
                        strategy="RATE_LIMIT_BACKOFF_OR_TOOL_SUBSTITUTION",
                        bad_attempt={
                            "tool": ep["fail_tool"],
                            "args": ep["fail_args"],
                            "exit_code": ep["fail_code"],
                            "failure_reason": ep["fail_sum"] or "Command failed with non-zero exit code",
                        },
                        recovery_action="Critic flagged failure -> Recovery agent re-executed with corrected parameters",
                        corrected_attempt={
                            "tool": ep["retry_tool"],
                            "args": ep["retry_args"],
                            "exit_code": ep["retry_code"],
                        },
                        verified_result={
                            "status": "success",
                            "result_summary": ep["retry_sum"],
                        },
                        parent_event_link=str(ep["parent_event"]),
                        metadata={"source": "database_event_pair"},
                    )
                )
        except Exception as e:
            logger.warning(f"Error extracting DB recovery chains: {e}")
        finally:
            conn.close()

        return chains

    def _generate_grounded_counterfactual_chains(self) -> List[RecoveryChain]:
        """
        Generates grounded counterfactual recovery chains reflecting the 5 core recovery
        strategies defined in Task 2.5 and the Evaluation Framework blueprint.
        """
        templates = [
            # 1. WAF 429 Rate Limiting -> Thread reduction & backoff
            RecoveryChain(
                chain_id="rec_cf_waf_rate_limit",
                goal="Enumerate web application routes on http://192.168.1.50/admin",
                capability="web_directory_enumeration",
                strategy="RATE_LIMIT_BACKOFF",
                bad_attempt={
                    "tool": "ffuf.fuzz.v1",
                    "args": {"url": "http://192.168.1.50/admin/FUZZ", "threads": 100},
                    "exit_code": 1,
                    "failure_reason": "HTTP 429 Too Many Requests: Target WAF actively throttled scanner threads.",
                },
                recovery_action="Back off concurrency from 100 to 5 threads and insert 150ms inter-request delay.",
                corrected_attempt={
                    "tool": "ffuf.fuzz.v1",
                    "args": {"url": "http://192.168.1.50/admin/FUZZ", "threads": 5, "extra_args": ["-p", "0.15"]},
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Discovered 3 valid endpoints: /admin/login.php, /admin/dashboard, /admin/config.",
                },
                parent_event_link=None,
                metadata={"strategy": "RATE_LIMIT_BACKOFF", "counterfactual": True},
            ),

            # 2. Tool Starvation / Socket Timeout -> Tool Substitution
            RecoveryChain(
                chain_id="rec_cf_tool_sub_gobuster_ffuf",
                goal="Discover hidden administrative backup archives",
                capability="web_directory_enumeration",
                strategy="TOOL_SUBSTITUTION",
                bad_attempt={
                    "tool": "gobuster.dir.v1",
                    "args": {"url": "http://192.168.1.50/", "wordlist": "/usr/share/wordlists/dirb/big.txt"},
                    "exit_code": 124,
                    "failure_reason": "Process timed out after 30s. Gobuster stalled on slow socket responses.",
                },
                recovery_action="Substitute stalled tool 'gobuster.dir.v1' with high-performance fuzzer 'ffuf.fuzz.v1' with compact wordlist.",
                corrected_attempt={
                    "tool": "ffuf.fuzz.v1",
                    "args": {"url": "http://192.168.1.50/FUZZ", "wordlist": "/usr/share/wordlists/dirb/common.txt", "threads": 20},
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Found /backup.zip (200 OK, 14.2MB) and /internal/ (301 Redirect).",
                },
                parent_event_link=None,
                metadata={"strategy": "TOOL_SUBSTITUTION", "counterfactual": True},
            ),

            # 3. Connection Refused on Default Port -> Port / Param Mutation
            RecoveryChain(
                chain_id="rec_cf_param_mutation_port",
                goal="Fingerprint web application daemon on 192.168.1.50",
                capability="web_technology_fingerprint",
                strategy="PARAM_MUTATION",
                bad_attempt={
                    "tool": "whatweb.scan.v1",
                    "args": {"url": "http://192.168.1.50"},
                    "exit_code": 7,
                    "failure_reason": "Connection refused: Port 80 is closed on target host.",
                },
                recovery_action="Mutate target parameter using discovered active HTTP port (8080) from port scan evidence.",
                corrected_attempt={
                    "tool": "whatweb.scan.v1",
                    "args": {"url": "http://192.168.1.50:8080"},
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Apache/2.4.41 (Ubuntu) with Tomcat/9.0.31 identified on port 8080.",
                },
                parent_event_link=None,
                metadata={"strategy": "PARAM_MUTATION", "counterfactual": True},
            ),

            # 4. Scope Contract Tier Violation -> Tier Downgrade / Passive Recon
            RecoveryChain(
                chain_id="rec_cf_tier_downgrade_stealth",
                goal="Enumerate technology stack and services on production host 192.168.1.10",
                capability="web_vulnerability_scan",
                strategy="TIER_DOWNGRADE_STEALTH",
                bad_attempt={
                    "tool": "nikto.scan.v1",
                    "args": {"host": "192.168.1.10"},
                    "exit_code": 403,
                    "failure_reason": "SCOPE_TIER_VIOLATION: Active Scope Contract permits Tiers 1-2 only; noisy Tier 3 Nikto scan blocked.",
                },
                recovery_action="Downgrade from intrusive active scanning to passive Tier 1 technology fingerprinting.",
                corrected_attempt={
                    "tool": "whatweb.scan.v1",
                    "args": {"url": "http://192.168.1.10"},
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Identified Nginx 1.18.0, PHP 7.4, and OpenSSL 1.1.1f within permitted Tier 1 boundary.",
                },
                parent_event_link=None,
                metadata={"strategy": "TIER_DOWNGRADE_STEALTH", "counterfactual": True},
            ),

            # 5. SQLMap Injection Parameter Syntax Failure -> Explicit Parameter Flagging
            RecoveryChain(
                chain_id="rec_cf_sqlmap_param_repair",
                goal="Assess login authentication form for SQL injection vulnerabilities",
                capability="sql_injection_testing",
                strategy="SYNTAX_ARGUMENT_REPAIR",
                bad_attempt={
                    "tool": "sqlmap.scan.v1",
                    "args": {"url": "http://192.168.1.50/login.php"},
                    "exit_code": 1,
                    "failure_reason": "No testable parameter found in URL query string for GET request.",
                },
                recovery_action="Provide explicit POST body data parameter and testable injection point ('username').",
                corrected_attempt={
                    "tool": "sqlmap.scan.v1",
                    "args": {
                        "url": "http://192.168.1.50/login.php",
                        "data": "username=admin&password=password&submit=Login",
                        "extra_args": ["-p", "username"],
                    },
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Vulnerability identified: POST parameter 'username' is vulnerable to time-based blind SQL injection.",
                },
                parent_event_link=None,
                metadata={"strategy": "SYNTAX_ARGUMENT_REPAIR", "counterfactual": True},
            ),

            # 6. Hydra Login Timeout -> Lower Concurrency & Specific Protocol Target
            RecoveryChain(
                chain_id="rec_cf_hydra_rate_limit",
                goal="Verify SSH authentication security against default passwords",
                capability="password_brute_force",
                strategy="RATE_LIMIT_BACKOFF",
                bad_attempt={
                    "tool": "hydra.brute.v1",
                    "args": {"target": "192.168.1.50", "protocol": "ssh", "tasks": 32},
                    "exit_code": 255,
                    "failure_reason": "Max SSH connection attempts reached; remote sshd closed connection.",
                },
                recovery_action="Reduce parallel hydra workers from 32 to 4 and add connection wait delay.",
                corrected_attempt={
                    "tool": "hydra.brute.v1",
                    "args": {"target": "192.168.1.50", "protocol": "ssh", "tasks": 4},
                    "exit_code": 0,
                },
                verified_result={
                    "status": "success",
                    "result_summary": "Discovered valid credential: 'msfadmin:msfadmin' on SSH service.",
                },
                parent_event_link=None,
                metadata={"strategy": "RATE_LIMIT_BACKOFF", "counterfactual": True},
            ),
        ]

        return templates


# ==============================================================================
# Unified Harvester Facade
# ==============================================================================

class DataHarvestPipeline:
    """Orchestrates harvesting of ToolSpecs, Event Triples, and Counterfactual Recovery Chains."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, registry_dir: Path = REGISTRY_DIR):
        self.toolspec_harvester = ToolSpecHarvester(registry_dir)
        self.event_harvester = EventStoreHarvester(db_path)
        self.recovery_harvester = RecoveryChainHarvester(db_path)

    def harvest_all(self) -> Dict[str, Any]:
        logger.info("Harvesting (a) ToolSpecs & Man-Pages...")
        toolspecs = self.toolspec_harvester.harvest_all()

        logger.info("Harvesting (b) Event Store (goal, tool_call, outcome) triples...")
        triples = self.event_harvester.harvest_triples()

        logger.info("Harvesting (c) Counterfactual recovery chains...")
        recovery_chains = self.recovery_harvester.harvest_chains()

        return {
            "toolspecs": toolspecs,
            "event_triples": triples,
            "recovery_chains": recovery_chains,
            "counts": {
                "toolspecs_count": len(toolspecs),
                "event_triples_count": len(triples),
                "recovery_chains_count": len(recovery_chains),
            },
        }


harvester = DataHarvestPipeline()
