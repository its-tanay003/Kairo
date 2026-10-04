"""
Recovery Agent for Kairo.

Implements the Reliability & Error Recovery table from the blueprint:
- timeout: increase timeout / lighten flags or select alternate tool
- malformed args: repair args against schema, clean formatting, retry
- missing tool: automatically select alternate tool via Tool Selector
- parser mismatch: invoke fallback extraction or select alternate tool
- no-progress: switch tool candidate or adjust scan scope

Caps recovery attempts per node (default: 3) before marking the node failed
and surfacing the diagnostic to the user rather than looping silently.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from registry.loader import ToolRegistry, ToolSpec
from events.db import Event, insert_event, DEFAULT_DB_PATH
from orchestrator.tool_selector import tool_selector, ToolSelectionResult

logger = logging.getLogger("orchestrator.recovery_agent")

DEFAULT_MAX_RECOVERY_ATTEMPTS = 3


@dataclass
class RecoveryPlan:
    """
    Actionable recovery plan formulated by the Recovery Agent.
    """
    can_recover: bool
    attempt: int
    max_attempts: int
    error_type: str  # "timeout" | "malformed_args" | "missing_tool" | "parser_mismatch" | "no_progress" | "cap_exceeded"
    strategy: str    # "repair_args" | "retry_timeout" | "switch_tool" | "abort_cap_exceeded"
    tool_id: str
    repaired_args: Dict[str, Any]
    reason: str
    alternate_candidates: List[str] = field(default_factory=list)
    failure_surfaced_to_user: bool = False
    diagnostic_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecoveryAgent:
    """
    Autonomous Recovery Agent: repairs execution failures, switches tools,
    and enforces maximum recovery attempt caps.
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
        registry: Optional[ToolRegistry] = None,
        db_path=None,
    ):
        self.max_attempts = max_attempts
        self.registry = registry or tool_selector.registry
        self.db_path = db_path or DEFAULT_DB_PATH
        # In-memory attempt tracking per (plan_id, node_id)
        self._node_attempts: Dict[str, int] = {}
        self._node_history: Dict[str, List[Dict[str, Any]]] = {}

    def get_attempts(self, plan_id: str, node_id: str) -> int:
        key = f"{plan_id}_{node_id}"
        return self._node_attempts.get(key, 0)

    def record_attempt(self, plan_id: str, node_id: str, details: Dict[str, Any]) -> int:
        key = f"{plan_id}_{node_id}"
        current = self._node_attempts.get(key, 0) + 1
        self._node_attempts[key] = current
        if key not in self._node_history:
            self._node_history[key] = []
        self._node_history[key].append({"attempt": current, **details})
        return current

    def reset_node(self, plan_id: str, node_id: str):
        key = f"{plan_id}_{node_id}"
        self._node_attempts.pop(key, None)
        self._node_history.pop(key, None)

    def classify_error(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
        parser_mismatch: bool = False,
        critic_status: str = "",
    ) -> str:
        """Classifies execution failure into one of the 5 canonical recovery error types."""
        combined_err = f"{stderr}\n{stdout}".lower()

        # 1. Hard Timeout
        if timed_out or exit_code == 124 or "timed out" in combined_err or "timeout exceeded" in combined_err:
            return "timeout"

        # 2. Missing Tool / Binary
        if (
            exit_code == 127
            or "command not found" in combined_err
            or "not found" in combined_err
            or "no such file or directory" in combined_err
            or "is not installed" in combined_err
        ):
            return "missing_tool"

        # 3. Parser Mismatch
        if parser_mismatch or "parse_error" in combined_err:
            return "parser_mismatch"

        # 4. Malformed Args / Invalid CLI Syntax
        if (
            exit_code in (1, 2)
            and any(
                phrase in combined_err
                for phrase in [
                    "unrecognized option",
                    "invalid option",
                    "missing required",
                    "illegal option",
                    "usage:",
                    "argument error",
                    "invalid argument",
                    "unknown flag",
                    "flag provided but not defined",
                ]
            )
        ):
            return "malformed_args"

        # 5. No-Progress (from Critic)
        if critic_status == "no_progress":
            return "no_progress"

        # Default: if non-zero exit, check for arg errors or treat as malformed/retry
        if exit_code != 0:
            return "malformed_args"

        return "no_progress"

    def formulate_recovery(
        self,
        plan_id: str,
        node: Dict[str, Any],
        current_tool: str,
        current_args: Dict[str, Any],
        stdout: str,
        stderr: str,
        exit_code: int,
        timed_out: bool = False,
        parser_mismatch: bool = False,
        critic_status: str = "",
        critique_msg: str = "",
        session_id: str = "recovery_session",
    ) -> RecoveryPlan:
        """
        Formulates a concrete recovery strategy or enforces the cap if attempts >= 3.
        """
        node_id = node.get("node_id", "unknown")
        capability = node.get("capability", "general_execution")

        # Classify the error
        err_type = self.classify_error(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            parser_mismatch=parser_mismatch,
            critic_status=critic_status,
        )

        # Track attempt number
        attempt = self.record_attempt(
            plan_id=plan_id,
            node_id=node_id,
            details={
                "tool": current_tool,
                "error_type": err_type,
                "exit_code": exit_code,
                "critique": critique_msg,
            },
        )

        logger.info(
            f"[RecoveryAgent] Node #{node_id} ({capability}): Attempt {attempt}/{self.max_attempts} "
            f"for error '{err_type}' on tool '{current_tool}'"
        )

        # =========================================================================
        # RECOVERY CAP ENFORCEMENT (Strict Maximum Attempts e.g. 3)
        # =========================================================================
        if attempt >= self.max_attempts:
            abort_msg = (
                f"RECOVERY_EXHAUSTED (Attempt {attempt}/{self.max_attempts}): "
                f"Node #{node_id} marked failed after exhausting all recovery strategies. "
                f"Last error: {err_type} (exit code {exit_code}). "
                f"Critic diagnostic: {critique_msg or stderr.strip() or 'Zero progress detected'}."
            )

            # Log audit event for surfaced failure
            self._log_cap_exceeded_event(
                session_id=session_id,
                plan_id=plan_id,
                node_id=node_id,
                tool_id=current_tool,
                attempt=attempt,
                reason=abort_msg,
            )

            return RecoveryPlan(
                can_recover=False,
                attempt=attempt,
                max_attempts=self.max_attempts,
                error_type="cap_exceeded",
                strategy="abort_cap_exceeded",
                tool_id=current_tool,
                repaired_args=current_args,
                reason=abort_msg,
                failure_surfaced_to_user=True,
                diagnostic_details={
                    "last_error": err_type,
                    "last_tool": current_tool,
                    "history": self._node_history.get(f"{plan_id}_{node_id}", []),
                    "stderr": stderr[:500],
                },
            )

        # =========================================================================
        # RECOVERY STRATEGIES PER RELIABILITY & ERROR RECOVERY TABLE
        # =========================================================================

        # Strategy 1: TIMEOUT
        if err_type == "timeout":
            if attempt == 1:
                # Retry with increased timeout and optimized flags
                repaired = dict(current_args)
                cur_to = int(repaired.get("timeout_ms", 30000))
                repaired["timeout_ms"] = min(cur_to * 2, 120000)

                # Lighten tool-specific load if possible
                if "nmap" in current_tool:
                    repaired["timing"] = 4  # faster timing -T4
                    repaired["ports"] = "1-1024"  # reduce from full range
                elif "gobuster" in current_tool:
                    repaired["threads"] = 20  # increase concurrency
                    repaired["timeout_s"] = 5

                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="timeout",
                    strategy="retry_timeout",
                    tool_id=current_tool,
                    repaired_args=repaired,
                    reason=(
                        f"Increased execution timeout to {repaired['timeout_ms']}ms "
                        f"and tuned scan aggressiveness to avoid hang."
                    ),
                )
            else:
                # On subsequent timeout, switch to alternate tool
                alt_tool, alt_args, alts = self._select_alternate_tool(
                    capability=capability,
                    failed_tool=current_tool,
                    goal=node.get("label", ""),
                    session_id=session_id,
                    target_hint=current_args.get("target") or current_args.get("url"),
                )
                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="timeout",
                    strategy="switch_tool",
                    tool_id=alt_tool,
                    repaired_args=alt_args,
                    alternate_candidates=alts,
                    reason=f"Repeated timeout on '{current_tool}'; switched to alternate candidate '{alt_tool}'.",
                )

        # Strategy 2: MISSING_TOOL
        elif err_type == "missing_tool":
            alt_tool, alt_args, alts = self._select_alternate_tool(
                capability=capability,
                failed_tool=current_tool,
                goal=node.get("label", ""),
                session_id=session_id,
                target_hint=current_args.get("target") or current_args.get("url"),
            )
            return RecoveryPlan(
                can_recover=True,
                attempt=attempt,
                max_attempts=self.max_attempts,
                error_type="missing_tool",
                strategy="switch_tool",
                tool_id=alt_tool,
                repaired_args=alt_args,
                alternate_candidates=alts,
                reason=(
                    f"Tool '{current_tool}' binary missing in environment (exit code 127). "
                    f"Selected alternate tool '{alt_tool}' via Tool Selector."
                ),
            )

        # Strategy 3: MALFORMED_ARGS
        elif err_type == "malformed_args":
            repaired_args, repaired_ok, repair_rationale = self._repair_arguments(
                tool_id=current_tool,
                args=current_args,
                node=node,
                stderr=stderr,
            )

            if repaired_ok and repaired_args != current_args:
                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="malformed_args",
                    strategy="repair_args",
                    tool_id=current_tool,
                    repaired_args=repaired_args,
                    reason=f"Repaired command arguments against tool schema: {repair_rationale}.",
                )
            else:
                # If cannot repair arguments, switch to alternate tool
                alt_tool, alt_args, alts = self._select_alternate_tool(
                    capability=capability,
                    failed_tool=current_tool,
                    goal=node.get("label", ""),
                    session_id=session_id,
                    target_hint=current_args.get("target") or current_args.get("url"),
                )
                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="malformed_args",
                    strategy="switch_tool",
                    tool_id=alt_tool,
                    repaired_args=alt_args,
                    alternate_candidates=alts,
                    reason=f"Arguments could not be reconciled for '{current_tool}'; switched to alternate candidate '{alt_tool}'.",
                )

        # Strategy 4: PARSER_MISMATCH
        elif err_type == "parser_mismatch":
            # First attempt: add structured output formatting flags
            repaired_args = dict(current_args)
            if "nmap" in current_tool:
                repaired_args["scan_type"] = "sV"
                repaired_args["extra_args"] = ["-oX", "-"]
            elif "ffuf" in current_tool:
                repaired_args["output_format"] = "json"

            if attempt == 1:
                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="parser_mismatch",
                    strategy="repair_args",
                    tool_id=current_tool,
                    repaired_args=repaired_args,
                    reason=f"Enforced structured output stream flags on '{current_tool}' to resolve parser mismatch.",
                )
            else:
                alt_tool, alt_args, alts = self._select_alternate_tool(
                    capability=capability,
                    failed_tool=current_tool,
                    goal=node.get("label", ""),
                    session_id=session_id,
                    target_hint=current_args.get("target") or current_args.get("url"),
                )
                return RecoveryPlan(
                    can_recover=True,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    error_type="parser_mismatch",
                    strategy="switch_tool",
                    tool_id=alt_tool,
                    repaired_args=alt_args,
                    alternate_candidates=alts,
                    reason=f"Persistent parser mismatch on '{current_tool}'; switched to alternative candidate '{alt_tool}'.",
                )

        # Strategy 5: NO_PROGRESS
        else:
            # Critic indicated no progress was made
            alt_tool, alt_args, alts = self._select_alternate_tool(
                capability=capability,
                failed_tool=current_tool,
                goal=node.get("label", ""),
                session_id=session_id,
                target_hint=current_args.get("target") or current_args.get("url"),
            )
            return RecoveryPlan(
                can_recover=True,
                attempt=attempt,
                max_attempts=self.max_attempts,
                error_type="no_progress",
                strategy="switch_tool",
                tool_id=alt_tool,
                repaired_args=alt_args,
                alternate_candidates=alts,
                reason=(
                    f"Critic detected no progress on '{current_tool}' ({critique_msg[:60]}). "
                    f"Switched to alternative tool '{alt_tool}' for capability '{capability}'."
                ),
            )

    def _select_alternate_tool(
        self,
        capability: str,
        failed_tool: str,
        goal: str,
        session_id: str,
        target_hint: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any], List[str]]:
        """Queries the Tool Selector with exclude=[failed_tool] to pick the next highest candidate."""
        try:
            sel_res: ToolSelectionResult = tool_selector.select(
                goal=f"{capability}: {goal}",
                required_capability=capability,
                session_id=session_id,
                target_override=target_hint,
                top_k=3,
                exclude=[failed_tool],
            )
            top_candidate = sel_res.selected_tool
            candidate_ids = [c.tool_id for c in sel_res.top_candidates]
            return top_candidate.tool_id, top_candidate.inferred_args, candidate_ids
        except Exception as e:
            logger.warning(f"[RecoveryAgent] Failed to query alternate tool via selector: {e}")
            # Fallback table
            fallbacks = {
                "network_port_scan": "system_ping",
                "web_directory_enum": "ffuf.fuzz.v1",
                "web_directory_enumeration": "ffuf.fuzz.v1",
                "web_fuzzing": "gobuster.dir.v1",
                "web_vulnerability_scan": "whatweb.scan.v1",
                "sql_injection_test": "nikto.scan.v1",
                "credential_testing": "shell.run.v1",
            }
            alt = fallbacks.get(capability, "hello_world")
            return alt, {"target": target_hint or "127.0.0.1"}, [alt]

    def _repair_arguments(
        self,
        tool_id: str,
        args: Dict[str, Any],
        node: Dict[str, Any],
        stderr: str,
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        Validates and heals arguments against known tool adapter schemas and common CLI issues.
        """
        repaired = dict(args)
        rationale_parts = []

        # 1. Target URL / Host Healing
        target = repaired.get("target") or repaired.get("url") or repaired.get("host")
        if not target:
            # Extract target from node description or label
            txt = f"{node.get('label', '')} {node.get('description', '')}"
            ip_m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", txt)
            if ip_m:
                target = ip_m.group(0)
                repaired["target"] = target
                rationale_parts.append(f"inferred target IP '{target}' from node description")
            else:
                domain_m = re.search(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", txt)
                if domain_m:
                    target = domain_m.group(0)
                    repaired["target"] = target
                    rationale_parts.append(f"inferred target domain '{target}' from node description")
                else:
                    repaired["target"] = "127.0.0.1"
                    rationale_parts.append("defaulted target to 127.0.0.1")

        # 2. Web tools requirement: ensure 'url' has schema
        if any(w in tool_id for w in ["gobuster", "nikto", "whatweb", "sqlmap", "ffuf"]):
            url = repaired.get("url") or repaired.get("target") or ""
            if url and not url.startswith("http://") and not url.startswith("https://"):
                fixed_url = f"http://{url}"
                repaired["url"] = fixed_url
                repaired["target"] = fixed_url
                rationale_parts.append(f"prepended 'http://' to web target '{url}'")

        # 3. Port sanitization for Nmap
        if "nmap" in tool_id:
            ports = repaired.get("ports")
            if not ports or str(ports).strip() in ("", "0", "none"):
                repaired["ports"] = "1-1024"
                rationale_parts.append("reset invalid port range to default '1-1024'")

        # 4. Wordlist validation for Gobuster / Ffuf
        if any(w in tool_id for w in ["gobuster", "ffuf"]):
            wl = repaired.get("wordlist")
            if not wl or not str(wl).strip():
                repaired["wordlist"] = "/usr/share/wordlists/dirb/common.txt"
                rationale_parts.append("set standard default wordlist path")

        # 5. Clean extraneous invalid arguments
        valid_keys_map = {
            "nmap.scan.v1": {"target", "ports", "scan_type", "scripts", "timing", "extra_args"},
            "gobuster.dir.v1": {"url", "mode", "wordlist", "threads", "status_codes", "extensions", "timeout_s", "extra_args"},
            "ffuf.fuzz.v1": {"url", "wordlist", "mode", "mc", "rate", "threads", "extra_args"},
            "nikto.scan.v1": {"target", "port", "ssl", "tuning", "plugins", "extra_args"},
            "sqlmap.scan.v1": {"url", "method", "data", "params", "level", "risk", "dbms", "technique", "dbs", "tables", "extra_args"},
        }
        known_keys = valid_keys_map.get(tool_id)
        if known_keys:
            stripped = [k for k in repaired.keys() if k not in known_keys and not k.startswith("_")]
            for k in stripped:
                repaired.pop(k, None)
            if stripped:
                rationale_parts.append(f"removed invalid parameter(s) {stripped}")

        if rationale_parts:
            return repaired, True, "; ".join(rationale_parts)
        return repaired, False, "no repairs required"

    def _log_cap_exceeded_event(
        self,
        session_id: str,
        plan_id: str,
        node_id: str,
        tool_id: str,
        attempt: int,
        reason: str,
    ):
        """Logs an explicit audit event into SQLite when recovery cap is exceeded."""
        try:
            evt = Event.create(
                session_id=session_id,
                task_id=f"{plan_id}_{node_id}",
                actor="recovery_agent:cap_exceeded",
                tool_id=tool_id,
                exit_code=1,
                result_summary=f"RECOVERY_CAP_EXCEEDED: Node #{node_id} failed after {attempt} attempts.",
                confidence=1.0,
                network_context={
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "attempts": attempt,
                    "max_attempts": self.max_attempts,
                    "reason": reason,
                    "surfaced_to_user": True,
                },
            )
            insert_event(evt, self.db_path)
        except Exception as e:
            logger.warning(f"[RecoveryAgent] Failed to log cap exceeded event: {e}")


# Global singleton
recovery_agent = RecoveryAgent()
