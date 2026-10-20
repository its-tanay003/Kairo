"""
Agent Loop orchestrator for tool dispatch, execution, and structured event recording.
Integrated with llama.cpp server mode for grammar-constrained local model inference
and process supervisor for shell.run.v1 execution adapter with hard timeouts and SIGKILL switch.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Ensure root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dataclasses import asdict
from events.db import (
    Event,
    insert_event,
    init_db,
    record_tool_execution,
    get_tool_memory,
    validate_scope_request,
    extract_host_from_target,
    seed_default_scope_contract,
    get_active_scope_contract,
    create_scope_contract,
    get_ready_nodes,
    update_node_status,
)
from registry.loader import ToolRegistry, ToolSpec
from orchestrator.llama_client import LlamaCppClient
from orchestrator.models import LLMResponse
from orchestrator.process_supervisor import supervisor, ProcessResult
from orchestrator.vm_manager import vm_manager
from orchestrator.kali_connector import ExecutionPlaneType, FALLBACK_NOTICE_TEXT, SIMULATION_NOTICE_TEXT
from orchestrator.tool_selector import tool_selector
from orchestrator.adapters.registry import adapter_registry
from orchestrator.intent_classifier import (
    intent_classifier,
    IntentType,
    StepProvenance,
    generate_conversational_response,
    generate_plan_explanation,
)
from orchestrator.planner import planner, Planner

from orchestrator.claude_synthesis import synthesize_agent_response

logger = logging.getLogger("orchestrator.agent")


class AgentLoop:
    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        llama_url: Optional[str] = None,
    ):
        self.db_path = db_path or (ROOT_DIR / "events" / "events.db")
        self.registry = ToolRegistry(ROOT_DIR / "registry" / "tools")
        self.llama_client = LlamaCppClient(base_url=llama_url)
        self.supervisor = supervisor
        self.planner = Planner(llama_url=llama_url, db_path=self.db_path)
        init_db(self.db_path)
        seed_default_scope_contract(self.db_path)

    def _map_capability_to_tool(self, capability: str, target: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Maps an abstract DAG capability to a concrete security tool and arguments."""
        cap = (capability or "").lower()
        tgt = target or "127.0.0.1"

        if "port_scan" in cap or "port" in cap or "network" in cap:
            return "nmap.scan.v1", {"target": tgt, "profile": "quick", "ports": "top-100"}
        elif "whois" in cap:
            return "whois.lookup.v1", {"domain": tgt}
        elif "dig" in cap or "dns_lookup" in cap:
            return "dig.lookup.v1", {"target": tgt}
        elif "dns" in cap or "subdomain" in cap:
            return "subfinder.enum.v1", {"domain": tgt}
        elif "ffuf" in cap or "fuzz" in cap:
            return "ffuf.fuzz.v1", {"url": f"http://{tgt}" if not tgt.startswith("http") else tgt}
        elif "dir" in cap or "web_directory" in cap or "content" in cap or "route" in cap:
            return "gobuster.dir.v1", {"url": f"http://{tgt}" if not tgt.startswith("http") else tgt, "wordlist": "common.txt"}
        elif "wordpress" in cap or "wp" in cap:
            return "wpscan.audit.v1", {"url": f"http://{tgt}" if not tgt.startswith("http") else tgt}
        elif "fingerprint" in cap or "whatweb" in cap or "tech" in cap:
            return "whatweb.scan.v1", {"targets": [f"http://{tgt}" if not tgt.startswith("http") else tgt]}
        elif "nikto" in cap:
            return "nikto.scan.v1", {"target": tgt}
        elif "sql" in cap:
            return "sqlmap.scan.v1", {"url": f"http://{tgt}" if not tgt.startswith("http") else tgt}
        elif "tls" in cap or "ssl" in cap:
            return "testssl.audit.v1", {"target": tgt}
        elif "web_probe" in cap or "probe" in cap or "http" in cap:
            return "httpx.probe.v1", {"targets": [tgt]}
        elif "vuln" in cap or "cve" in cap or "exploit" in cap:
            return "nuclei.scan.v1", {"target": tgt, "severity": "medium,high,critical"}
        elif "traffic" in cap or "capture" in cap or "tcpdump" in cap:
            return "tcpdump.capture.v1", {"interface": "eth0", "packet_count": 100}
        elif "kali" in cap:
            return "kali.exec.v1", {"command": "uname", "args": ["-a"]}
        elif "shell" in cap:
            return "shell.run.v1", {"command": "python", "args": ["-c", "print('Executed via capability')"]}
        else:
            return "nmap.scan.v1", {"target": tgt, "profile": "quick", "ports": "top-100"}

    def _extract_target(self, text: str) -> Optional[str]:
        """Extracts IP address, domain, or URL target from message text."""
        import re
        url_match = re.search(r"https?://[a-zA-Z0-9\.\_\:\-]+(?:/[^\s]*)?", text)
        if url_match:
            return url_match.group(0)

        ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", text)
        if ip_match:
            return ip_match.group(0)

        domain_match = re.search(r"\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?\b", text)
        if domain_match:
            cand = domain_match.group(0).lower()
            if not cand.endswith((".py", ".pt", ".gguf", ".sh", ".json", ".md")):
                return cand

        if re.search(r"\b(?:this\s+host|localhost|local\s+host|local\s+machine|local\s+system|current\s+host|the\s+host)\b", text, re.IGNORECASE):
            return "127.0.0.1"

        return None

    def _execute_single_tool(
        self,
        session_id: str,
        task_id: str,
        tool_id: str,
        requested_args: Dict[str, Any],
        active_model_info: Dict[str, Any],
        exec_record: Any,
        message: str,
        t0: float,
        start_time_iso: str,
        parent_event: Optional[str] = None,
        tool_selection_data: Optional[Dict[str, Any]] = None,
        step_prov: Optional[Dict[str, Any]] = None,
        plan_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validates, authorizes, and safely executes a single tool adapter inside Kali VM sandbox / supervisor.
        Exposes full step provenance and records a verifiable 20-field SQLite event.
        """
        step_prov = dict(step_prov or {})
        spec: Optional[ToolSpec] = self.registry.get(tool_id)
        tool_version = spec.version if spec else "1.0.0"
        model_verif = exec_record.to_dict() if hasattr(exec_record, "to_dict") else {}

        # 0. Scope Contract Enforcement (Boundary & Tool Tier Gate):
        target_candidate = None
        if isinstance(requested_args, dict):
            for k in ("target", "host", "url", "domain", "ip", "filepath", "rhost", "rhosts"):
                if requested_args.get(k):
                    target_candidate = str(requested_args[k]).strip()
                    break
            if not target_candidate and "args" in requested_args and isinstance(requested_args["args"], list):
                for a in requested_args["args"]:
                    sa = str(a).strip()
                    if any(c in sa for c in [".", ":", "/"]) and not sa.startswith("-"):
                        clean_a = extract_host_from_target(sa)
                        if clean_a and not clean_a.endswith((".py", ".sh", ".json", ".pt")):
                            target_candidate = clean_a
                            break

        if not target_candidate:
            import re
            ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', message)
            if ip_match:
                target_candidate = ip_match.group(0)
            else:
                dm = re.search(r'\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}\b', message)
                if dm:
                    cand = dm.group(0)
                    if not cand.endswith((".py", ".sh", ".json", ".pt", ".yaml", ".yml", ".v1", ".v2")) and not cand.startswith(("shell.", "nmap.", "nikto.", "whatweb.", "wpscan.", "nuclei.", "sqlmap.", "kali.")):
                        target_candidate = cand

        scope_check = validate_scope_request(target=target_candidate, tool_id=tool_id, db_path=self.db_path)
        if not scope_check.get("authorized", False):
            rejection_reason = scope_check.get("reason", "Scope violation detected by execution gateway.")
            logger.warning(f"[ScopeGuard] Rejected tool call '{tool_id}' on target '{target_candidate}': {rejection_reason}")

            rejection_event = Event.create(
                session_id=session_id,
                task_id=task_id,
                actor="gateway:scope_guard",
                tool_id=tool_id,
                tool_version=tool_version,
                requested_args=requested_args,
                exit_code=403,
                result_summary=f"SCOPE_REJECTION: {rejection_reason}",
                confidence=0.0,
                network_context={
                    "target": target_candidate,
                    "tool_tier": scope_check.get("tool_tier"),
                    "scope_contract_id": scope_check.get("scope_contract_id"),
                    "rejection_reason": rejection_reason,
                    "authorized": False,
                },
            )
            rejection_event_id = insert_event(rejection_event, self.db_path)

            scope_synth = synthesize_agent_response(
                user_goal=message,
                tool_id=tool_id,
                tool_name=spec.name if spec else tool_id,
                inputs={"target": target_candidate},
                exit_code=403,
                stdout="",
                stderr=rejection_reason,
                duration_ms=0,
                is_scope_violation=True,
                scope_violation_reason=rejection_reason,
            )

            step_prov["validation_and_authorization"] = StepProvenance(
                stage="validation_and_authorization",
                handled_by="security_gateway:scope_guard",
                runtime="scope_contract",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"authorized": False, "target": target_candidate, "reason": rejection_reason},
            ).to_dict()
            step_prov["execution"] = StepProvenance(
                stage="execution",
                handled_by="none",
                runtime="none",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"blocked": True, "reason": f"Target {target_candidate} is outside authorized Scope Contract"},
            ).to_dict()

            return {
                "status": "rejected",
                "authorized": False,
                "error": "SCOPE_VIOLATION",
                "reply": scope_synth["reply"],
                "synthesis": scope_synth,
                "scope_violation": {
                    "reason": rejection_reason,
                    "scope_contract_id": scope_check.get("scope_contract_id"),
                    "target": target_candidate,
                    "tool_id": tool_id,
                    "tool_tier": scope_check.get("tool_tier"),
                },
                "tool_executed": {
                    "id": tool_id,
                    "name": spec.name if spec else tool_id,
                    "version": tool_version,
                },
                "execution": {
                    "adapter": tool_id,
                    "exit_code": 403,
                    "stdout": "",
                    "stderr": rejection_reason,
                    "duration_ms": 0,
                    "synthesis": scope_synth,
                },
                "event_id": rejection_event_id,
                "event": asdict(rejection_event),
                "tool_selection": tool_selection_data,
                "duration_ms": 0,
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": exec_record.actual_model_id,
                "inference_runtime": exec_record.inference_runtime,
                "processed_by_selected_model": exec_record.processed_by_selected_model,
                "structured_output": exec_record.structured_output,
                "selected_tool": tool_id,
                "validated_args": requested_args,
                "fallback_used": exec_record.fallback_used,
                "fallback_reason": exec_record.fallback_reason,
                "local_only": True,
                "step_provenance": list(step_prov.values()) if isinstance(step_prov, dict) else step_prov,
                "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                "handled_by_fallback": exec_record.fallback_used,
            }

        # 1. Workflow Approval Policy Gate for Broad Command Execution:
        from orchestrator.validation import is_workflow_approved, validate_tool_arguments
        active_contract = get_active_scope_contract(self.db_path)

        wf_approved, wf_reason = is_workflow_approved(
            tool_id=tool_id,
            requested_args=requested_args if isinstance(requested_args, dict) else {},
            scope_contract=active_contract,
        )
        if not wf_approved:
            logger.warning(f"[WorkflowGate] Blocked unrestricted execution for '{tool_id}': {wf_reason}")
            policy_synth = {
                "reply": f"### 🛡️ Unrestricted Command Execution Blocked\n\n{wf_reason}",
                "process": {
                    "title": "Workflow Policy Gate",
                    "tool_id": tool_id,
                    "tool_name": spec.name if spec else tool_id,
                    "intent": "Blocked unrestricted execution",
                    "status": "blocked",
                    "status_label": "Policy Blocked",
                },
                "output": {
                    "summary_metrics": [
                        {"label": "Policy Status", "value": "Restricted", "type": "error"},
                        {"label": "Tool", "value": tool_id, "type": "warning"},
                    ],
                    "raw_stdout": wf_reason,
                },
                "result": {
                    "headline": "Unrestricted command execution requires explicit workflow approval",
                    "status": "error",
                    "key_takeaways": [
                        "Broad command execution adapters (shell.run.v1, kali.exec.v1) are restricted.",
                        "Use typed, validated security tool adapters (e.g. nmap.scan.v1, gobuster.dir.v1, wpscan.audit.v1, etc.) for known operations.",
                    ],
                },
            }
            blocked_event = Event.create(
                session_id=session_id,
                task_id=task_id,
                actor="gateway:workflow_policy",
                tool_id=tool_id,
                tool_version=tool_version,
                requested_args=requested_args,
                exit_code=403,
                result_summary=f"WORKFLOW_POLICY_BLOCK: {wf_reason}",
                confidence=0.0,
                network_context={"reason": wf_reason, "authorized": False, "policy": "workflow_approval"},
            )
            b_event_id = insert_event(blocked_event, self.db_path)
            step_prov["validation_and_authorization"] = StepProvenance(
                stage="validation_and_authorization",
                handled_by="security_gateway:workflow_policy",
                runtime="policy_gate",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"authorized": False, "reason": wf_reason},
            ).to_dict()
            step_prov["execution"] = StepProvenance(
                stage="execution",
                handled_by="none",
                runtime="none",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"blocked": True, "reason": "Workflow approval policy rejected unrestricted execution"},
            ).to_dict()
            return {
                "status": "rejected",
                "authorized": False,
                "error": "UNAPPROVED_COMMAND_EXECUTION",
                "reply": policy_synth["reply"],
                "synthesis": policy_synth,
                "tool_executed": {"id": tool_id, "name": spec.name if spec else tool_id, "version": tool_version},
                "execution": {"adapter": tool_id, "exit_code": 403, "stderr": wf_reason, "duration_ms": 0},
                "event_id": b_event_id,
                "tool_selection": tool_selection_data,
                "duration_ms": 0,
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": exec_record.actual_model_id,
                "inference_runtime": exec_record.inference_runtime,
                "processed_by_selected_model": exec_record.processed_by_selected_model,
                "structured_output": exec_record.structured_output,
                "selected_tool": tool_id,
                "validated_args": requested_args,
                "fallback_used": exec_record.fallback_used,
                "fallback_reason": exec_record.fallback_reason,
                "local_only": True,
                "step_provenance": step_prov,
                "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                "handled_by_fallback": exec_record.fallback_used,
            }

        # 2. Typed Schema & Security Argument Validation
        if spec:
            is_valid_args, arg_errors = validate_tool_arguments(spec, requested_args if isinstance(requested_args, dict) else {})
            if not is_valid_args:
                arg_err_msg = "; ".join(arg_errors)
                logger.warning(f"[ArgValidator] Rejected arguments for '{tool_id}': {arg_err_msg}")
                val_synth = {
                    "reply": f"### ⚠️ Argument Validation Error for `{tool_id}`\n\n{arg_err_msg}",
                    "process": {"title": "Argument Validation", "tool_id": tool_id, "status": "error", "status_label": "Invalid Arguments"},
                    "output": {"summary_metrics": [{"label": "Status", "value": "Invalid Args", "type": "error"}], "raw_stdout": arg_err_msg},
                    "result": {"headline": "Tool execution rejected due to schema/validation errors", "status": "error", "key_takeaways": arg_errors},
                }
                val_event = Event.create(
                    session_id=session_id,
                    task_id=task_id,
                    actor="gateway:arg_validator",
                    tool_id=tool_id,
                    tool_version=tool_version,
                    requested_args=requested_args,
                    exit_code=400,
                    result_summary=f"ARG_VALIDATION_ERROR: {arg_err_msg}",
                    confidence=0.0,
                    network_context={"validation_errors": arg_errors},
                )
                v_event_id = insert_event(val_event, self.db_path)
                step_prov["argument_validation"] = StepProvenance(
                    stage="argument_validation",
                    handled_by="security_gateway:arg_validator",
                    runtime="schema_validator",
                    is_custom_model=False,
                    is_fallback=False,
                    executed=False,
                    details={"valid": False, "errors": arg_errors},
                ).to_dict()
                step_prov["execution"] = StepProvenance(
                    stage="execution",
                    handled_by="none",
                    runtime="none",
                    is_custom_model=False,
                    is_fallback=False,
                    executed=False,
                    details={"blocked": True, "reason": "Schema validation rejected invalid arguments"},
                ).to_dict()
                return {
                    "status": "rejected",
                    "authorized": False,
                    "error": "ARGUMENT_VALIDATION_ERROR",
                    "reply": val_synth["reply"],
                    "synthesis": val_synth,
                    "tool_executed": {"id": tool_id, "name": spec.name if spec else tool_id, "version": tool_version},
                    "execution": {"adapter": tool_id, "exit_code": 400, "stderr": arg_err_msg, "duration_ms": 0},
                    "event_id": v_event_id,
                    "tool_selection": tool_selection_data,
                    "duration_ms": 0,
                    "model_id": active_model_info.get("model_id"),
                    "model_role": active_model_info.get("role"),
                    "model_verification": model_verif,
                    "selected_model": exec_record.selected_model,
                    "actual_model_id": exec_record.actual_model_id,
                    "inference_runtime": exec_record.inference_runtime,
                    "processed_by_selected_model": exec_record.processed_by_selected_model,
                    "structured_output": exec_record.structured_output,
                    "selected_tool": tool_id,
                    "validated_args": requested_args,
                    "fallback_used": exec_record.fallback_used,
                    "fallback_reason": exec_record.fallback_reason,
                    "local_only": True,
                    "step_provenance": list(step_prov.values()) if isinstance(step_prov, dict) else step_prov,
                    "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                    "handled_by_fallback": exec_record.fallback_used,
                }
            else:
                step_prov["argument_validation"] = StepProvenance(
                    stage="argument_validation",
                    handled_by="security_gateway:arg_validator",
                    runtime="schema_validator",
                    is_custom_model=False,
                    is_fallback=False,
                    executed=True,
                    details={"valid": True, "tool_id": tool_id},
                ).to_dict()
        else:
            step_prov["argument_validation"] = StepProvenance(
                stage="argument_validation",
                handled_by="security_gateway:arg_validator",
                runtime="schema_validator",
                is_custom_model=False,
                is_fallback=False,
                executed=True,
                details={"valid": True, "tool_id": tool_id, "note": "No explicit schema"},
            ).to_dict()


        # Validation & Authorization Passed
        step_prov["validation_and_authorization"] = StepProvenance(
            stage="validation_and_authorization",
            handled_by="security_gateway:scope_contract",
            runtime="policy_and_schema",
            is_custom_model=False,
            is_fallback=False,
            executed=True,
            details={"authorized": True, "target": target_candidate, "tier": scope_check.get("tool_tier")},
        ).to_dict()

        # 4. Safe Execution inside Sandbox / Supervisor
        stdout_output = ""
        stderr_output: Optional[str] = None
        exit_code = 0
        process_id = os.getpid()
        execution_details: Dict[str, Any] = {}
        event_artifact_refs: List[str] = []
        real_status = "success"
        recorded_cmd = ""
        typed_invocation = {
            "tool": tool_id,
            "version": tool_version,
            "arguments": requested_args,
        }

        if tool_id == "shell.run.v1":
            command = requested_args.get("command") or "python"
            args = requested_args.get("args") or ["-c", "print('Executed via shell.run.v1 adapter')"]
            timeout_ms = int(requested_args.get("timeout_ms", 10000))
            resource_limits = requested_args.get("resource_limits")
            artifact_dir = requested_args.get("artifact_dir")

            proc_res: ProcessResult = self.supervisor.execute(
                task_id=task_id,
                command=command,
                args=args,
                timeout_ms=timeout_ms,
                limits=resource_limits,
                artifact_dir=artifact_dir,
            )

            process_id = proc_res.process_id
            exit_code = proc_res.exit_code
            stdout_output = proc_res.stdout
            stderr_output = proc_res.stderr if proc_res.stderr else None

            cmd_str = f"{command} {' '.join(str(a) for a in args)}"
            recorded_cmd = cmd_str
            real_status = "timeout" if proc_res.timed_out else ("failed" if exit_code != 0 else "success")
            status_str = "TIMED OUT" if proc_res.timed_out else (f"CAP VIOLATION ({proc_res.violation_reason})" if proc_res.resource_limit_exceeded else f"exit {exit_code}")
            reply_text = f"Adapter shell.run.v1 completed: `${cmd_str}` ({status_str}) in {proc_res.duration_ms}ms"
            result_summary = f"Executed shell.run.v1 ({cmd_str}) -> exit {exit_code}"
            event_artifact_refs = [f"sha256:{a['sha256']}:{a['filename']}" for a in proc_res.artifacts]

            execution_details = {
                "adapter": "shell.run.v1",
                "status": real_status,
                "command_line": recorded_cmd,
                "typed_invocation": typed_invocation,
                "command": command,
                "args": args,
                "exit_code": exit_code,
                "process_id": process_id,
                "stdout": stdout_output,
                "stderr": stderr_output or "",
                "duration_ms": proc_res.duration_ms,
                "timed_out": proc_res.timed_out,
                "resource_limit_exceeded": proc_res.resource_limit_exceeded,
                "violation_reason": proc_res.violation_reason,
                "artifacts": proc_res.artifacts,
            }
            actor = "orchestrator:adapter:shell.run.v1"

        elif tool_id == "kali.exec.v1":
            command = requested_args.get("command") or "uname"
            args = requested_args.get("args") or ["-a"]
            timeout_ms = int(requested_args.get("timeout_ms", 30000))
            snapshot_before = bool(requested_args.get("snapshot_before", True))
            rollback_after = bool(requested_args.get("rollback_after", False))
            rollback_on_failure = bool(requested_args.get("rollback_on_failure", False))
            resource_limits = requested_args.get("resource_limits")
            artifact_dir = requested_args.get("artifact_dir")

            vm_res = vm_manager.execute_in_vm(
                task_id=task_id,
                tool_id="kali.exec.v1",
                tool_version=tool_version,
                args={"command": command, "args": args, "cwd": requested_args.get("cwd", "/home/kali")},
                snapshot_before=snapshot_before,
                rollback_after=rollback_after,
                rollback_on_failure=rollback_on_failure,
                resource_limits=resource_limits,
                artifact_dir=artifact_dir,
                timeout_ms=timeout_ms,
            )

            process_id = vm_res.get("process_id", 0)
            exit_code = vm_res.get("exit_code", 0)
            stdout_output = vm_res.get("stdout", "")
            stderr_output = vm_res.get("stderr") if vm_res.get("stderr") else None

            cmd_str = f"{command} {' '.join(str(a) for a in args)}"
            recorded_cmd = cmd_str
            real_status = "timeout" if vm_res.get("timed_out") else ("failed" if exit_code != 0 else "success")
            status_str = "TIMED OUT" if vm_res.get("timed_out") else (f"CAP VIOLATION ({vm_res.get('violation_reason')})" if vm_res.get("resource_limit_exceeded") else f"exit {exit_code}")
            exec_plane = vm_res.get("execution_plane", "unknown")
            fallback_notice = vm_res.get("fallback_notice")
            local_fallback = bool(vm_res.get("local_fallback", False) or exec_plane == ExecutionPlaneType.LOCAL_HOST_FALLBACK.value)

            if local_fallback:
                fallback_notice = fallback_notice or FALLBACK_NOTICE_TEXT
                reply_text = f"Local Host Fallback [kali.exec.v1] completed: `{cmd_str}` ({status_str}) in {vm_res.get('duration_ms', 0)}ms"
                result_summary = f"[{FALLBACK_NOTICE_TEXT}] Executed `{cmd_str}` on local host fallback -> exit {exit_code}"
                actor = "orchestrator:host_fallback:kali.exec.v1"
            else:
                reply_text = f"Kali Sandbox [kali.exec.v1] completed: `{cmd_str}` ({status_str}) in {vm_res.get('duration_ms', 0)}ms"
                result_summary = f"Kali Sandbox executed `{cmd_str}` -> exit {exit_code}"
                if vm_res.get("rolled_back"):
                    result_summary += " [VM Rolled Back]"
                actor = "orchestrator:sandbox:kali.exec.v1"

            event_artifact_refs = [f"sha256:{a.get('sha256')}:{a.get('filename')}" for a in vm_res.get("artifacts", [])]
            if vm_res.get("snapshot_name"):
                event_artifact_refs.append(f"snapshot://{vm_res.get('snapshot_name')}")
            if vm_res.get("rolled_back"):
                event_artifact_refs.append(f"rollback://{vm_res.get('rollback_info', {}).get('snapshot_restored', 'kairo_worker_ready')}")

            execution_details = {
                "adapter": "kali.exec.v1",
                "status": real_status,
                "command_line": recorded_cmd,
                "typed_invocation": typed_invocation,
                "sandboxed": not local_fallback,
                "execution_plane": exec_plane,
                "fallback_notice": fallback_notice,
                "local_fallback": local_fallback,
                "vm": vm_manager.vm_name,
                "command": command,
                "args": args,
                "exit_code": exit_code,
                "process_id": process_id,
                "stdout": stdout_output,
                "stderr": stderr_output or "",
                "duration_ms": vm_res.get("duration_ms", 0),
                "timed_out": vm_res.get("timed_out", False),
                "pre_snapshot": vm_res.get("pre_snapshot"),
                "rollback_info": vm_res.get("rollback_info"),
                "rolled_back": vm_res.get("rolled_back", False),
                "resource_limit_exceeded": vm_res.get("resource_limit_exceeded", False),
                "violation_reason": vm_res.get("violation_reason"),
                "artifacts": vm_res.get("artifacts", []),
            }

        elif tool_id == "hello_world":
            greet_target = requested_args.get("target") or requested_args.get("input") or "World"
            recorded_cmd = f"echo 'Hello {greet_target}! Boundary verified.'"
            real_status = "success"
            stdout_output = f"[Tool:hello_world] Executed with target: '{greet_target}'."
            reply_text = f"Agent executed hello_world (v{tool_version}): Hello {greet_target}! Boundary verified."
            result_summary = f"Executed hello_world for target '{greet_target}'."
            actor = "orchestrator:agent:tool"
            exit_code = 0
            execution_details = {
                "tool": "hello_world",
                "status": real_status,
                "command_line": recorded_cmd,
                "typed_invocation": typed_invocation,
                "exit_code": 0,
                "stdout": stdout_output,
                "target": greet_target,
            }

        elif tool_id == "system_ping":
            recorded_cmd = "kairo-diag --self-test"
            real_status = "success"
            stdout_output = f"[Tool:system_ping] System healthy. Pid: {os.getpid()} Time: {start_time_iso}"
            reply_text = f"Agent executed system_ping (v{tool_version}): Core agent services operational."
            result_summary = "Executed system_ping diagnostic successfully."
            actor = "orchestrator:agent:tool"
            exit_code = 0
            execution_details = {
                "tool": "system_ping",
                "status": real_status,
                "command_line": recorded_cmd,
                "typed_invocation": typed_invocation,
                "exit_code": 0,
                "stdout": stdout_output,
            }

        elif adapter_registry.get(tool_id):
            adapter_cls = adapter_registry.get(tool_id)
            try:
                adapter = adapter_cls(vm_manager=vm_manager, supervisor=self.supervisor)
            except TypeError:
                try:
                    adapter = adapter_cls(vm_manager=vm_manager)
                except TypeError:
                    try:
                        adapter = adapter_cls(vm_manager)
                    except TypeError:
                        adapter = adapter_cls()
            inputs_dict = dict(requested_args) if isinstance(requested_args, dict) else {}
            if "target" not in inputs_dict and target_candidate:
                inputs_dict["target"] = target_candidate
            if "target" not in inputs_dict:
                inputs_dict["target"] = "127.0.0.1"

            if "nmap" in tool_id:
                recorded_cmd = f"nmap -{inputs_dict.get('scan_type', 'sV')} -p {inputs_dict.get('ports', '1-1000')} {inputs_dict.get('target')}"
            else:
                recorded_cmd = f"{tool_id} --target {inputs_dict.get('target')}"

            try:
                obs = adapter.execute(
                    inputs=inputs_dict,
                    task_id=task_id,
                    target="vm",
                )
                exit_code = obs.exit_code
                real_status = "success" if exit_code == 0 else "failed"
                stdout_output = obs.raw_stdout
                stderr_output = obs.raw_stderr
                process_id = os.getpid()
                event_artifact_refs = obs.artifacts
                actor = f"orchestrator:adapter:{tool_id}"

                cmd_summary = f"{tool_id} target={inputs_dict.get('target', 'unknown')}"
                if exit_code == 0:
                    reply_text = f"Agent executed {tool_id} (v{tool_version}): Scan completed successfully against {inputs_dict.get('target')}."
                    result_summary = f"Executed {tool_id} -> exit {exit_code}"
                else:
                    reply_text = f"Agent executed {tool_id} (v{tool_version}): Tool completed with exit code {exit_code} (FAILED)."
                    result_summary = f"Executed {tool_id} ({cmd_summary}) -> exit {exit_code} (FAILED)"

                obs_exec_plane = getattr(obs, "execution_plane", None) or (obs.observation.get("execution_plane") if isinstance(obs.observation, dict) else None)
                obs_fallback_notice = getattr(obs, "fallback_notice", None) or (obs.observation.get("fallback_notice") if isinstance(obs.observation, dict) else None)
                obs_is_simulated = bool(
                    getattr(obs, "is_simulated", False)
                    or (obs.observation.get("is_simulated", False) if isinstance(obs.observation, dict) else False)
                    or obs_exec_plane == ExecutionPlaneType.SIMULATED_MOCK.value
                    or obs_exec_plane == "simulated_mock"
                )
                obs_sim_notice = (
                    getattr(obs, "simulation_notice", None)
                    or (obs.observation.get("simulation_notice") if isinstance(obs.observation, dict) else None)
                    or (SIMULATION_NOTICE_TEXT if obs_is_simulated else None)
                )
                obs_local_fallback = bool(
                    not obs_is_simulated and (
                        getattr(obs, "local_fallback", False)
                        or (obs.observation.get("local_fallback", False) if isinstance(obs.observation, dict) else False)
                        or obs_exec_plane == ExecutionPlaneType.LOCAL_HOST_FALLBACK.value
                    )
                )

                execution_details = {
                    "adapter": tool_id,
                    "status": real_status,
                    "command_line": recorded_cmd,
                    "typed_invocation": typed_invocation,
                    "exit_code": exit_code,
                    "stdout": stdout_output,
                    "stderr": stderr_output or "",
                    "duration_ms": obs.duration_ms,
                    "observation": obs.observation,
                    "artifacts": obs.artifacts,
                    "execution_plane": obs_exec_plane or ("simulated_mock" if obs_is_simulated else "unknown"),
                    "fallback_notice": obs_fallback_notice,
                    "local_fallback": obs_local_fallback,
                    "is_simulated": obs_is_simulated,
                    "simulation_notice": obs_sim_notice,
                }
            except Exception as e:
                logger.error(f"Error executing adapter {tool_id}: {e}", exc_info=True)
                exit_code = 1
                real_status = "error"
                stdout_output = ""
                stderr_output = f"Execution error in adapter '{tool_id}': {e}"
                reply_text = f"Agent failed to execute {tool_id} (v{tool_version}): {e}"
                result_summary = f"Failed {tool_id} -> exit 1 ({e})"
                actor = f"orchestrator:adapter:{tool_id}"
                execution_details = {
                    "adapter": tool_id,
                    "status": "error",
                    "exit_code": 1,
                    "command_line": recorded_cmd or f"{tool_id} (failed invocation)",
                    "typed_invocation": typed_invocation,
                    "stdout": "",
                    "stderr": stderr_output,
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                }

        else:
            exit_code = 127
            real_status = "error"
            stdout_output = ""
            stderr_output = f"Tool '{tool_id}' is not an authorized or registered tool adapter."
            reply_text = f"Agent could not execute {tool_id} (v{tool_version}): Tool is not registered."
            result_summary = f"Unregistered tool {tool_id} -> exit 127"
            actor = "orchestrator:agent:tool"
            recorded_cmd = f"{tool_id} (unregistered)"
            execution_details = {
                "tool": tool_id,
                "status": "error",
                "exit_code": 127,
                "command_line": recorded_cmd,
                "typed_invocation": typed_invocation,
                "stdout": "",
                "stderr": stderr_output,
                "duration_ms": round((time.time() - t0) * 1000, 2),
            }

        end_time_iso = datetime.now(timezone.utc).isoformat()
        normalized_args = {
            "args": requested_args,
            "tool_version": tool_version,
            "model_verification": model_verif,
            "plan_id": plan_id,
            "node_id": node_id,
        }

        # Step provenance tracking for execution
        exec_plane = execution_details.get("execution_plane")
        fallback_notice = execution_details.get("fallback_notice")
        is_simulated = bool(
            execution_details.get("is_simulated")
            or exec_plane == ExecutionPlaneType.SIMULATED_MOCK.value
            or exec_plane == "simulated_mock"
        )
        sim_notice = execution_details.get("simulation_notice") or (SIMULATION_NOTICE_TEXT if is_simulated else None)

        is_local_fallback = bool(
            not is_simulated and (
                execution_details.get("local_fallback")
                or exec_plane == ExecutionPlaneType.LOCAL_HOST_FALLBACK.value
                or exec_plane == "local_host_fallback"
                or fallback_notice
            )
        )
        if is_local_fallback:
            exec_plane = ExecutionPlaneType.LOCAL_HOST_FALLBACK.value
            fallback_notice = fallback_notice or FALLBACK_NOTICE_TEXT
        elif is_simulated:
            exec_plane = ExecutionPlaneType.SIMULATED_MOCK.value
            fallback_notice = sim_notice

        step_prov["execution"] = StepProvenance(
            stage="execution",
            handled_by=tool_id,
            runtime="simulated_mock" if is_simulated else ("local_host" if is_local_fallback else ("kali_sandbox" if (tool_id == "kali.exec.v1" or adapter_registry.get(tool_id)) else "supervisor")),
            is_custom_model=False,
            is_fallback=is_local_fallback or is_simulated,
            executed=True,
            details={
                "exit_code": exit_code,
                "adapter": tool_id,
                "duration_ms": execution_details.get("duration_ms", 0),
                "execution_plane": exec_plane or ("simulated_mock" if is_simulated else ("local_host_fallback" if is_local_fallback else "kali_sandbox")),
                "fallback_notice": fallback_notice,
                "local_fallback": is_local_fallback,
                "is_simulated": is_simulated,
                "simulation_notice": sim_notice,
            },
        ).to_dict()

        if is_simulated and not result_summary.startswith("[SIMULATED"):
            result_summary = f"{sim_notice} {result_summary}"
        elif is_local_fallback and not result_summary.startswith(f"[{FALLBACK_NOTICE_TEXT}]") and not result_summary.startswith("[HOST FALLBACK]"):
            result_summary = f"[{FALLBACK_NOTICE_TEXT}] {result_summary}"

        # Record exact 20-field event row in SQLite
        event = Event.create(
            session_id=session_id,
            task_id=task_id,
            actor=actor,
            tool_id=tool_id,
            tool_version=tool_version,
            requested_args=requested_args,
            normalized_args=normalized_args,
            process_id=process_id,
            start_time=start_time_iso,
            end_time=end_time_iso,
            exit_code=exit_code,
            stdout_ref=f"inline://{stdout_output}" if stdout_output else None,
            stderr_ref=f"inline://{stderr_output}" if stderr_output else None,
            artifact_refs=event_artifact_refs or ["memory://context/session_state.json"],
            screenshots=[],
            network_context={
                "ip": "127.0.0.1",
                "execution_plane": exec_plane or ("simulated_mock" if is_simulated else ("local_host_fallback" if is_local_fallback else "unknown")),
                "fallback_notice": fallback_notice,
                "local_fallback": is_local_fallback,
                "is_simulated": is_simulated,
                "simulation_notice": sim_notice,
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_server": self.llama_client.base_url,
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": exec_record.actual_model_id,
                "inference_runtime": exec_record.inference_runtime,
                "processed_by_selected_model": exec_record.processed_by_selected_model,
                "structured_output": exec_record.structured_output,
                "selected_tool": tool_id,
                "validated_args": requested_args,
                "fallback_used": exec_record.fallback_used,
                "fallback_reason": exec_record.fallback_reason,
                "local_only": True,
            },
            result_summary=result_summary,
            confidence=1.0,
            parent_event=parent_event,
            timestamp=start_time_iso,
        )
        event_id = insert_event(event, self.db_path)

        # Update Tool Memory Store (global system state)
        try:
            record_tool_execution(
                tool_id=tool_id,
                success=(exit_code == 0),
                duration_ms=round((time.time() - t0) * 1000, 2),
                exit_code=exit_code,
                timed_out=bool(execution_details.get("timed_out")),
                metadata={"task_id": task_id, "session_id": session_id, "plan_id": plan_id},
                db_path=self.db_path,
            )
        except Exception as e:
            logger.warning(f"Failed to record tool memory: {e}")

        # Rich synthesis
        try:
            synthesis = synthesize_agent_response(
                user_goal=message,
                tool_id=tool_id,
                tool_name=spec.name if spec else tool_id,
                inputs=requested_args if isinstance(requested_args, dict) else {},
                exit_code=exit_code,
                stdout=stdout_output or "",
                stderr=stderr_output or "",
                observation=execution_details.get("observation"),
                duration_ms=round((time.time() - t0) * 1000, 2),
                execution_plane=exec_plane,
                fallback_notice=fallback_notice,
                is_simulated=is_simulated,
                simulation_notice=sim_notice,
            )
            if synthesis.get("reply"):
                reply_text = synthesis["reply"]
            execution_details["synthesis"] = synthesis
        except Exception as e:
            logger.warning(f"Synthesis error: {e}", exc_info=True)

        if is_simulated and not reply_text.startswith("> ⚠️ **[SIMULATED"):
            reply_text = f"> ⚠️ **{sim_notice}**\n\n{reply_text}"
        elif is_local_fallback and not reply_text.startswith("> ⚠️"):
            reply_text = f"> ⚠️ **{fallback_notice}**\n\n{reply_text}"

        return {
            "session_id": session_id,
            "task_id": task_id,
            "status": execution_details.get("status", real_status),
            "exit_code": exit_code,
            "command_line": execution_details.get("command_line", recorded_cmd),
            "typed_invocation": typed_invocation,
            "reply": reply_text,
            "synthesis": execution_details.get("synthesis"),
            "execution_plane": exec_plane,
            "fallback_notice": fallback_notice,
            "local_fallback": is_local_fallback,
            "is_simulated": is_simulated,
            "simulation_notice": sim_notice,
            "tool_executed": {
                "id": tool_id,
                "version": tool_version,
                "name": spec.name if spec else tool_id,
            },
            "execution": execution_details,
            "tool_selection": tool_selection_data,
            "event_id": event_id,
            "event": as_dict_event(event),
            "duration_ms": round((time.time() - t0) * 1000, 2),
            "model_status": "transformers_custom_primary" if exec_record.inference_runtime == "transformers" else "llama.cpp_fallback",
            "model_id": active_model_info.get("model_id"),
            "model_role": active_model_info.get("role"),
            "model_verification": model_verif,
            "selected_model": exec_record.selected_model,
            "actual_model_id": exec_record.actual_model_id,
            "inference_runtime": exec_record.inference_runtime,
            "processed_by_selected_model": exec_record.processed_by_selected_model,
            "structured_output": exec_record.structured_output,
            "selected_tool": tool_id,
            "validated_args": requested_args,
            "fallback_used": exec_record.fallback_used,
            "fallback_reason": exec_record.fallback_reason,
            "local_only": True,
            "step_provenance": list(step_prov.values()) if isinstance(step_prov, dict) else step_prov,
            "tools_executed_count": 1 if execution_details else 0,
            "handled_by_custom_model": exec_record.inference_runtime == "transformers",
            "handled_by_fallback": exec_record.fallback_used,
        }

    def _stream_step_to_websocket(
        self,
        step_result: Dict[str, Any],
        plan_id: str,
        node_id: str,
        session_id: str,
        step_callback: Optional[Any] = None,
    ) -> None:
        """
        Streams an incremental tool card / step result over WebSocket to Gateway and UI clients.
        Formats payload to match the Gateway 'agent_response' contract expected by the UI.
        """
        if step_callback and callable(step_callback):
            try:
                step_callback(step_result)
            except Exception as e:
                logger.debug(f"[AgentLoop] Step callback error: {e}")

        # Build payload matching Gateway 'agent_response'
        step_payload = {
            "type": "agent_response",
            "sessionId": session_id,
            "session_id": session_id,
            "planId": plan_id,
            "nodeId": node_id,
            "reply": step_result.get("reply", ""),
            "toolExecuted": step_result.get("tool_executed"),
            "tool_executed": step_result.get("tool_executed"),
            "execution": step_result.get("execution"),
            "synthesis": step_result.get("synthesis") or (step_result.get("execution") or {}).get("synthesis"),
            "eventId": step_result.get("event_id"),
            "event_id": step_result.get("event_id"),
            "event": step_result.get("event"),
            "durationMs": step_result.get("duration_ms"),
            "toolSelection": step_result.get("tool_selection"),
            "modelId": step_result.get("model_id"),
            "modelRole": step_result.get("model_role"),
            "modelStatus": step_result.get("model_status"),
            "modelVerification": step_result.get("model_verification"),
            "selectedModel": step_result.get("selected_model"),
            "actualModelId": step_result.get("actual_model_id"),
            "inferenceRuntime": step_result.get("inference_runtime"),
            "processedBySelectedModel": step_result.get("processed_by_selected_model"),
            "structuredOutput": step_result.get("structured_output"),
            "selectedTool": step_result.get("selected_tool"),
            "validatedArgs": step_result.get("validated_args"),
            "fallbackUsed": step_result.get("fallback_used"),
            "fallbackReason": step_result.get("fallback_reason"),
            "localOnly": True,
            "intent": "tool_request",
            "planOnly": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Post to Gateway streaming endpoint (port 4000)
        gateway_http = os.environ.get("GATEWAY_HTTP", "http://127.0.0.1:4000")
        try:
            import urllib.request
            req_data = json.dumps(step_payload).encode("utf-8")
            req = urllib.request.Request(
                f"{gateway_http}/agent/stream_step",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.3) as resp:
                pass
        except Exception as e:
            logger.debug(f"[AgentLoop] Gateway HTTP stream push skipped: {e}")

        # 2. Direct WebSocket push to ws://127.0.0.1:4000 in background thread
        try:
            import threading
            def _push_ws():
                try:
                    import asyncio
                    import websockets
                    gateway_ws = os.environ.get("GATEWAY_WS", "ws://127.0.0.1:4000")
                    async def _send():
                        async with websockets.connect(f"{gateway_ws}/?sessionId={session_id}", open_timeout=0.3, close_timeout=0.3) as ws:
                            await ws.send(json.dumps(step_payload))
                    asyncio.run(_send())
                except Exception:
                    pass
            th = threading.Thread(target=_push_ws, daemon=True)
            th.start()
        except Exception as e:
            logger.debug(f"[AgentLoop] Gateway WS stream push skipped: {e}")

    def execute_task(
        self,
        session_id: str,
        message: str = "",
        task_id: Optional[str] = None,
        parent_event: Optional[str] = None,
        explicit_tool: Optional[str] = None,
        explicit_args: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        user_message: Optional[str] = None,
        autonomous: Optional[bool] = None,
        mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        message = message or user_message or ""
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        start_time_iso = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        # Model Activation & Identity Resolution
        active_model_info: Dict[str, Any] = {}
        if model_id:
            try:
                from orchestrator.model_center import model_center
                active_model_info = model_center.select_model(model_id)
                logger.info(f"[AgentLoop] Selected and activated model '{active_model_info.get('model_id')}' for session {session_id}")
            except Exception as e:
                logger.warning(f"[AgentLoop] Failed to activate requested model '{model_id}': {e}")

        if not active_model_info:
            try:
                from orchestrator.model_center import model_center
                active_model_info = model_center.get_active_model()
            except Exception:
                active_model_info = {"model_id": "kairo-scale-2b", "role": "primary-custom-scaled-tier-c"}

        tools = self.registry.list_tools()
        llm_response: Optional[LLMResponse] = None
        used_llm = False
        tool_selection_data: Optional[Dict[str, Any]] = None

        # Explicit, Verifiable Model Integration Engine Execution
        from orchestrator.model_integration import model_integration
        effective_requested_model = model_id or active_model_info.get("model_id")
        exec_record = model_integration.dispatch_inference(
            user_message=message,
            requested_model_id=effective_requested_model,
            tools=tools,
            session_id=session_id,
            explicit_tool=explicit_tool,
            explicit_args=explicit_args,
        )
        model_verif = exec_record.to_dict()

        # Scope Contract Authorization Intent (e.g., "Update scope contract to authorize internet.lpu.in")
        import re
        lower_msg = message.lower().strip()
        is_scope_auth = (
            lower_msg.startswith("authorize ")
            or ("scope" in lower_msg and any(w in lower_msg for w in ["authorize", "add", "allow", "permit", "update"]))
            or (lower_msg.startswith("add ") and "scope" in lower_msg)
        ) and not (lower_msg.startswith("scan ") or lower_msg.startswith("run ") or lower_msg.startswith("execute "))

        if is_scope_auth and not explicit_tool:
            target_match = re.search(r'(?:authorize|add|allow)(?:\s+target)?\s+([a-zA-Z0-9\.\_\-\/]+)', message, re.IGNORECASE)
            if not target_match or target_match.group(1).lower() in ("contract", "target", "scope", "to"):
                target_match = re.search(r'\b([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/\d{1,2})?)\b', message)
            if not target_match:
                target_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', message)
            if target_match:
                new_tgt = target_match.group(1).strip().strip("'\"").lower()
                if new_tgt and new_tgt not in ("contract", "target", "scope", "to"):
                    from orchestrator.execution_gateway import execution_gateway
                    active = get_active_scope_contract(self.db_path)
                    curr = list(active.get("targets", [])) if active else []

                    # Extract operator token from explicit arguments if provided
                    op_token = (explicit_args or {}).get("operator_token") or (explicit_args or {}).get("auth_token")

                    if not op_token:
                        refusal_reply = (
                            f"### 🛡️ Operator Authorization Required\n\n"
                            f"A request to authorize target **`{new_tgt}`** was received via chat.\n\n"
                            f"**Security Policy Enforcement:** Natural-language prompts cannot self-authorize targets "
                            f"or expand the active Scope Contract without an authenticated operator token.\n\n"
                            f"#### 🔒 Remediation\n"
                            f"- Authenticate using an administrative or operator session token (`operator_token`).\n"
                            f"- Use the trusted `/scope/contract` management endpoint to authorize new lab targets.\n"
                            f"- Ensure testing remains restricted to the authorized scope boundary: `{', '.join(curr) if curr else 'None'}`.\n"
                        )
                        return {
                            "intent": "scope_authorization",
                            "plan_only": False,
                            "plan": None,
                            "reply": refusal_reply,
                            "tool_executed": None,
                            "execution": {
                                "status": "rejected",
                                "exit_code": 403,
                                "stderr": "OPERATOR_AUTH_REQUIRED: Chat prompt cannot self-authorize scope without operator token.",
                                "duration_ms": int((time.time() - t0) * 1000),
                            },
                            "synthesis": {
                                "reply": refusal_reply,
                                "process": {
                                    "title": "Scope Contract Authorization",
                                    "status": "error",
                                    "status_label": "Authorization Required",
                                    "target": new_tgt,
                                },
                                "result": {
                                    "headline": "Scope expansion rejected: Operator token required",
                                    "status": "blocked",
                                    "security_posture": "Scope Contract Unchanged",
                                    "key_takeaways": [
                                        "Prompt injection / self-authorization prevented.",
                                        "Target modification requires authenticated operator action.",
                                    ],
                                },
                            },
                            "duration_ms": int((time.time() - t0) * 1000),
                            "model_id": active_model_info.get("model_id"),
                            "model_role": active_model_info.get("role"),
                            "model_verification": model_verif,
                            "selected_model": exec_record.selected_model,
                            "actual_model_id": exec_record.actual_model_id,
                            "inference_runtime": exec_record.inference_runtime,
                            "processed_by_selected_model": exec_record.processed_by_selected_model,
                            "structured_output": exec_record.structured_output,
                            "selected_tool": None,
                            "validated_args": None,
                            "fallback_used": exec_record.fallback_used,
                            "fallback_reason": exec_record.fallback_reason,
                            "local_only": True,
                            "step_provenance": [
                                StepProvenance(
                                    stage="intent_classification",
                                    handled_by=exec_record.actual_model_id,
                                    runtime=exec_record.inference_runtime,
                                    is_custom_model=exec_record.inference_runtime == "transformers",
                                    is_fallback=exec_record.fallback_used,
                                    executed=True,
                                    details={"intent": "scope_authorization_request", "target": new_tgt},
                                ).to_dict(),
                                StepProvenance(
                                    stage="validation_and_authorization",
                                    handled_by="security_gateway:scope_contract",
                                    runtime="policy_and_schema",
                                    is_custom_model=False,
                                    is_fallback=False,
                                    executed=False,
                                    details={"authorized": False, "target": new_tgt, "reason": "Operator token required"},
                                ).to_dict(),
                            ],
                            "tools_executed_count": 0,
                            "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                            "handled_by_fallback": exec_record.fallback_used,
                        }

                    # Authenticated operator authorization via ExecutionGateway
                    curr_targets = list(curr)
                    if new_tgt not in curr_targets:
                        curr_targets.append(new_tgt)

                    success, new_contract, msg = execution_gateway.authorize_scope_modification(
                        targets=curr_targets,
                        operator_token=op_token,
                        network_scope="authorized_lab",
                        time_window="48h",
                        allowed_tool_tiers=[1, 2, 3],
                        metadata={"reason": f"Authorized target {new_tgt} via authenticated operator action"},
                        db_path=self.db_path,
                    )
                    if not success or not new_contract:
                        refusal_reply = f"### ❌ Operator Authentication Failed\n\n{msg}"
                        return {
                            "intent": "scope_authorization",
                            "plan_only": False,
                            "plan": None,
                            "reply": refusal_reply,
                            "tool_executed": None,
                            "execution": {
                                "status": "rejected",
                                "exit_code": 403,
                                "stderr": msg,
                                "duration_ms": int((time.time() - t0) * 1000),
                            },
                            "duration_ms": int((time.time() - t0) * 1000),
                            "model_id": active_model_info.get("model_id"),
                            "model_role": active_model_info.get("role"),
                            "model_verification": model_verif,
                            "selected_model": exec_record.selected_model,
                            "actual_model_id": exec_record.actual_model_id,
                            "inference_runtime": exec_record.inference_runtime,
                            "processed_by_selected_model": exec_record.processed_by_selected_model,
                            "structured_output": exec_record.structured_output,
                            "selected_tool": None,
                            "validated_args": None,
                            "fallback_used": exec_record.fallback_used,
                            "fallback_reason": exec_record.fallback_reason,
                            "local_only": True,
                            "step_provenance": [
                                StepProvenance(
                                    stage="validation_and_authorization",
                                    handled_by="security_gateway:scope_contract",
                                    runtime="auth_verification",
                                    is_custom_model=False,
                                    is_fallback=False,
                                    executed=False,
                                    details={"authorized": False, "target": new_tgt, "reason": msg},
                                ).to_dict(),
                            ],
                            "tools_executed_count": 0,
                            "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                            "handled_by_fallback": exec_record.fallback_used,
                        }

                    synth_reply = (
                        f"### ✅ Scope Contract Updated (Authenticated Operator Action)\n\n"
                        f"Target **`{new_tgt}`** has been successfully added to active Scope Contract (`{new_contract['contract_id']}`).\n\n"
                        f"#### 🛡️ Authorization Details\n"
                        f"- **Authorized By:** `{new_contract.get('authorized_by')}`\n"
                        f"- **Active Targets:** `{', '.join(curr_targets)}`\n"
                        f"- **Allowed Tool Tiers:** `Tiers 1, 2, 3` (Reconnaissance, Auditing & Testing)\n"
                        f"- **Validity Window:** `48 hours` (cryptographically signed)\n\n"
                        f"#### 💡 Next Steps\n"
                        f"You can now run reconnaissance or security audits against `{new_tgt}` within authorized policy.\n"
                    )
                    scope_prov = [
                        StepProvenance(
                            stage="intent_classification",
                            handled_by=exec_record.actual_model_id,
                            runtime=exec_record.inference_runtime,
                            is_custom_model=exec_record.inference_runtime == "transformers",
                            is_fallback=exec_record.fallback_used,
                            executed=True,
                            details={"intent": "scope_authorization", "target": new_tgt},
                        ).to_dict(),
                        StepProvenance(
                            stage="validation_and_authorization",
                            handled_by="security_gateway:scope_contract",
                            runtime="auth_session",
                            is_custom_model=False,
                            is_fallback=False,
                            executed=True,
                            details={"contract_id": new_contract["contract_id"], "target": new_tgt, "authorized_by": new_contract.get("authorized_by")},
                        ).to_dict(),
                    ]
                    return {
                        "intent": "tool_request",
                        "plan_only": False,
                        "plan": None,
                        "reply": synth_reply,
                        "tool_executed": {"id": "scope_gate.v1", "name": "Scope Contract Gate", "version": "1.0.0"},
                        "execution": {
                            "adapter": "scope_gate",
                            "command": f"scope_gate authorize --target {new_tgt}",
                            "exit_code": 0,
                            "stdout": f"Target {new_tgt} authorized under {new_contract['contract_id']}.",
                            "duration_ms": int((time.time() - t0) * 1000),
                        },
                        "synthesis": {
                            "reply": synth_reply,
                            "process": {
                                "title": "Scope Contract Authorization",
                                "tool_id": "scope_gate.v1",
                                "tool_name": "Scope Contract Gate",
                                "intent": f"Authorize target {new_tgt} in Scope Contract",
                                "command_line": f"scope_gate authorize --target {new_tgt}",
                                "target": new_tgt,
                                "duration_s": round(time.time() - t0, 2),
                                "status": "success",
                                "status_label": "Authorized",
                                "tier": 1,
                            },
                            "output": {
                                "summary_metrics": [
                                    {"label": "Authorized Target", "value": new_tgt, "type": "success"},
                                    {"label": "Active Targets", "value": str(len(curr_targets)), "type": "info"},
                                    {"label": "Status", "value": "Valid & Signed", "type": "success"},
                                ],
                                "findings_table": [{"item": t, "value": "Authorized", "status": "Active"} for t in curr_targets],
                                "raw_stdout": f"Scope Contract {new_contract['contract_id']} created and signed by {new_contract.get('authorized_by')}.",
                                "has_raw_terminal": False,
                            },
                            "result": {
                                "headline": f"Target {new_tgt} is now authorized",
                                "status": "clean",
                                "security_posture": "Scope Contract Updated",
                                "key_takeaways": [
                                    f"Added {new_tgt} to active Scope Contract.",
                                    f"Signed under contract {new_contract['contract_id']}.",
                                ],
                                "recommended_actions": [
                                    {"label": f"Scan {new_tgt}", "prompt": f"Scan {new_tgt} for open ports and services"},
                                    {"label": f"Probe {new_tgt}", "prompt": f"Inspect verified vulnerability findings on {new_tgt}"},
                                ],
                            },
                        },
                        "duration_ms": int((time.time() - t0) * 1000),
                        "model_status": "scope_gate_update",
                        "model_id": active_model_info.get("model_id"),
                        "model_role": active_model_info.get("role"),
                        "model_verification": model_verif,
                        "selected_model": exec_record.selected_model,
                        "actual_model_id": exec_record.actual_model_id,
                        "inference_runtime": exec_record.inference_runtime,
                        "processed_by_selected_model": exec_record.processed_by_selected_model,
                        "structured_output": exec_record.structured_output,
                        "selected_tool": "scope_gate.v1",
                        "validated_args": {"target": new_tgt},
                        "fallback_used": exec_record.fallback_used,
                        "fallback_reason": exec_record.fallback_reason,
                        "local_only": True,
                        "step_provenance": scope_prov,
                        "tools_executed_count": 1,
                        "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                        "handled_by_fallback": exec_record.fallback_used,
                    }

        # Explicit tool invocation fast-path (e.g. from API or direct integration test)
        if explicit_tool:
            tool_id = explicit_tool
            requested_args = explicit_args or {}
            try:
                sel_res = tool_selector.select(goal=message, session_id=session_id)
                tool_selection_data = sel_res.to_dict()
            except Exception as e:
                logger.warning(f"Could not calculate candidate scores: {e}")

            step_prov = {
                "intent_classification": StepProvenance(
                    stage="intent_classification",
                    handled_by=exec_record.actual_model_id,
                    runtime=exec_record.inference_runtime,
                    is_custom_model=exec_record.inference_runtime == "transformers",
                    is_fallback=exec_record.fallback_used,
                    executed=True,
                    details={"intent": "explicit_tool_request", "tool_id": explicit_tool},
                ).to_dict(),
            }

            exec_result = self._execute_single_tool(
                session_id=session_id,
                task_id=task_id,
                tool_id=tool_id,
                requested_args=requested_args,
                active_model_info=active_model_info,
                exec_record=exec_record,
                message=message,
                t0=t0,
                start_time_iso=start_time_iso,
                parent_event=parent_event,
                tool_selection_data=tool_selection_data,
                step_prov=step_prov,
            )
            exec_result["intent"] = "tool_request"
            exec_result["plan_only"] = False
            exec_result["plan"] = None
            return exec_result

        # 2. Intent Classification Stage (First stage for EVERY ordinary message)
        intent_res = intent_classifier.classify(
            message=message,
            requested_model_id=effective_requested_model,
            explicit_tool=explicit_tool,
            explicit_args=explicit_args,
        )

        step_prov: Dict[str, Any] = {}
        if isinstance(intent_res.step_provenance, dict):
            if "intent_classification" in intent_res.step_provenance:
                step_prov["intent_classification"] = intent_res.step_provenance["intent_classification"]
            else:
                step_prov.update(intent_res.step_provenance)
        else:
            step_prov["intent_classification"] = intent_res.step_provenance

        # 3. Flow Routing based on Intent
        # =========================================================================
        # Flow Branch A: General Question -> Conversational Response (0 tools executed)
        # =========================================================================
        if intent_res.intent == IntentType.GENERAL_QUESTION:
            logger.info(f"[IntentFlow] Routing '{message[:40]}...' to General Question (Conversational)")
            fallback_reason = exec_record.fallback_reason or (intent_res.step_provenance.get("details", {}).get("fallback_reason") if intent_res.step_provenance else None)
            fallback_used = exec_record.fallback_used or intent_res.is_fallback
            content_text = generate_conversational_response(
                query=intent_res.goal_or_query,
                model_id=intent_res.handled_by,
                runtime=intent_res.runtime,
                is_custom=intent_res.is_custom_model,
                is_fallback=fallback_used,
                fallback_reason=fallback_reason,
            )

            step_prov["reasoning"] = StepProvenance(
                stage="reasoning",
                handled_by=intent_res.handled_by,
                runtime=intent_res.runtime,
                is_custom_model=intent_res.is_custom_model,
                is_fallback=fallback_used,
                executed=True,
                details={"topic": intent_res.goal_or_query, "response_chars": len(content_text)},
            ).to_dict()

            step_prov["execution"] = StepProvenance(
                stage="execution",
                handled_by="none",
                runtime="none",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"reason": "Pure conversational response; zero tools executed"},
            ).to_dict()

            end_time_iso = datetime.now(timezone.utc).isoformat()
            event = Event.create(
                session_id=session_id,
                task_id=task_id,
                actor="orchestrator:model:conversational",
                tool_id=None,
                tool_version=None,
                requested_args={"query": message},
                normalized_args={"sanitized_query": message.strip(), "model_verification": model_verif, "intent": "general_question"},
                process_id=os.getpid(),
                start_time=start_time_iso,
                end_time=end_time_iso,
                exit_code=0,
                stdout_ref=f"inline://{content_text[:200]}...",
                stderr_ref=None,
                artifact_refs=[],
                screenshots=[],
                network_context={
                    "ip": "127.0.0.1",
                    "model_id": intent_res.handled_by,
                    "model_role": active_model_info.get("role"),
                    "inference_runtime": intent_res.runtime,
                    "intent": "general_question",
                    "step_provenance": step_prov,
                    "model_verification": model_verif,
                    "selected_model": exec_record.selected_model,
                    "actual_model_id": exec_record.actual_model_id,
                    "processed_by_selected_model": exec_record.processed_by_selected_model,
                    "structured_output": exec_record.structured_output,
                    "selected_tool": None,
                    "validated_args": None,
                    "fallback_used": fallback_used,
                    "fallback_reason": fallback_reason,
                    "local_only": True,
                },
                result_summary=f"Conversational response: {content_text[:60]}...",
                confidence=1.0,
                parent_event=parent_event,
                timestamp=start_time_iso,
            )
            event_id = insert_event(event, self.db_path)

            return {
                "intent": "general_question",
                "plan_only": False,
                "plan": None,
                "session_id": session_id,
                "task_id": task_id,
                "reply": content_text,
                "tool_executed": None,
                "execution": None,
                "event_id": event_id,
                "event": as_dict_event(event),
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "model_status": "transformers_custom_primary" if intent_res.is_custom_model else "llama.cpp_fallback",
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": intent_res.handled_by,
                "inference_runtime": intent_res.runtime,
                "processed_by_selected_model": not fallback_used,
                "structured_output": exec_record.structured_output,
                "selected_tool": None,
                "validated_args": None,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "local_only": True,
                "step_provenance": list(step_prov.values()) if isinstance(step_prov, dict) else step_prov,
                "tools_executed_count": 0,
                "handled_by_custom_model": intent_res.is_custom_model,
                "handled_by_fallback": fallback_used,
            }

        # =========================================================================
        # Flow Branch B: Plan-Only Request -> Explain plan; execute nothing
        # =========================================================================
        elif intent_res.intent == IntentType.PLAN_ONLY:
            logger.info(f"[IntentFlow] Routing '{message[:40]}...' to Plan-Only Mode (Execute nothing)")
            plan_obj = self.planner.decompose(goal=intent_res.goal_or_query, session_id=session_id, db_path=self.db_path, prefer_llm=True)
            plan_dict = plan_obj.to_dict() if hasattr(plan_obj, "to_dict") else plan_obj
            fallback_reason = exec_record.fallback_reason or (intent_res.step_provenance.get("details", {}).get("fallback_reason") if intent_res.step_provenance else None)
            fallback_used = exec_record.fallback_used or intent_res.is_fallback

            step_prov["plan_decomposition"] = StepProvenance(
                stage="plan_decomposition",
                handled_by=intent_res.handled_by,
                runtime=intent_res.runtime,
                is_custom_model=intent_res.is_custom_model,
                is_fallback=fallback_used,
                executed=True,
                details={
                    "plan_id": plan_dict.get("plan_id"),
                    "nodes_count": len(plan_dict.get("nodes", [])),
                    "mode": "plan_only",
                },
            ).to_dict()

            explanation = generate_plan_explanation(
                plan=plan_dict,
                goal=intent_res.goal_or_query,
                target=intent_res.target,
                model_id=intent_res.handled_by,
                runtime=intent_res.runtime,
                is_custom=intent_res.is_custom_model,
                is_fallback=fallback_used,
                fallback_reason=fallback_reason,
            )

            step_prov["plan_explanation"] = StepProvenance(
                stage="plan_explanation",
                handled_by=intent_res.handled_by,
                runtime=intent_res.runtime,
                is_custom_model=intent_res.is_custom_model,
                is_fallback=fallback_used,
                executed=True,
                details={"nodes_count": len(plan_dict.get("nodes", [])), "explanation_chars": len(explanation)},
            ).to_dict()

            step_prov["execution"] = StepProvenance(
                stage="execution",
                handled_by="none",
                runtime="none",
                is_custom_model=False,
                is_fallback=False,
                executed=False,
                details={"reason": "Plan-only request; explained plan and executed nothing"},
            ).to_dict()

            end_time_iso = datetime.now(timezone.utc).isoformat()
            event = Event.create(
                session_id=session_id,
                task_id=task_id,
                actor="orchestrator:planner",
                tool_id=None,
                tool_version=None,
                requested_args={"goal": intent_res.goal_or_query, "target": intent_res.target, "mode": "plan_only"},
                normalized_args={"plan_id": plan_dict.get("plan_id"), "nodes": len(plan_dict.get("nodes", [])), "intent": "plan_only"},
                process_id=os.getpid(),
                start_time=start_time_iso,
                end_time=end_time_iso,
                exit_code=0,
                stdout_ref=f"inline://{explanation[:200]}...",
                stderr_ref=None,
                artifact_refs=[f"plan://{plan_dict.get('plan_id')}"],
                screenshots=[],
                network_context={
                    "ip": "127.0.0.1",
                    "plan_id": plan_dict.get("plan_id"),
                    "intent": "plan_only",
                    "step_provenance": step_prov,
                    "model_verification": model_verif,
                    "model_id": intent_res.handled_by,
                    "inference_runtime": intent_res.runtime,
                    "selected_model": exec_record.selected_model,
                    "actual_model_id": exec_record.actual_model_id,
                    "processed_by_selected_model": not fallback_used,
                    "structured_output": exec_record.structured_output,
                    "selected_tool": None,
                    "validated_args": None,
                    "fallback_used": fallback_used,
                    "fallback_reason": fallback_reason,
                    "local_only": True,
                },
                result_summary=f"Generated plan {plan_dict.get('plan_id')} (plan-only; 0 commands executed)",
                confidence=1.0,
                parent_event=parent_event,
                timestamp=start_time_iso,
            )
            event_id = insert_event(event, self.db_path)

            return {
                "intent": "plan_only",
                "plan_only": True,
                "plan": plan_dict,
                "session_id": session_id,
                "task_id": task_id,
                "reply": explanation,
                "tool_executed": None,
                "execution": None,
                "event_id": event_id,
                "event": as_dict_event(event),
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "model_status": "transformers_custom_primary" if intent_res.is_custom_model else "llama.cpp_fallback",
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": intent_res.handled_by,
                "inference_runtime": intent_res.runtime,
                "processed_by_selected_model": not fallback_used,
                "structured_output": exec_record.structured_output,
                "selected_tool": None,
                "validated_args": None,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "local_only": True,
                "step_provenance": list(step_prov.values()) if isinstance(step_prov, dict) else step_prov,
                "tools_executed_count": 0,
                "handled_by_custom_model": intent_res.is_custom_model,
                "handled_by_fallback": fallback_used,
            }

        # =========================================================================
        # Operational Execution: Planner LLM-Backed Decomposition (Task Graph DAG)
        # =========================================================================
        else:
            logger.info(f"[AgentLoop] Invoking Planner LLM decomposition for: '{message[:50]}...'")
            plan_obj = self.planner.decompose(
                goal=message,
                session_id=session_id,
                db_path=self.db_path,
                prefer_llm=True,
            )
            plan_dict = plan_obj.to_dict() if hasattr(plan_obj, "to_dict") else plan_obj
            plan_id = plan_dict.get("plan_id")
            nodes = plan_dict.get("nodes", [])

            extracted_target = intent_res.target or self._extract_target(message)
            if not extracted_target or extracted_target == "127.0.0.1":
                import re
                url_match = re.search(r"https?://[a-zA-Z0-9\.\_\:\-]+(?:/[^\s]*)?", message)
                if url_match:
                    extracted_target = url_match.group(0)
                else:
                    ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", message)
                    if ip_match:
                        extracted_target = ip_match.group(0)
                    else:
                        domain_match = re.search(r"\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}\b", message)
                        if domain_match:
                            extracted_target = domain_match.group(0)
                        else:
                            extracted_target = extracted_target or "127.0.0.1"

            from events.db import get_ready_nodes, update_node_status, get_plan, get_connection
            from orchestrator.dag_controller import (
                dag_controller,
                EvidenceContext,
                DAGNodeExecution,
                DAGNodeExecutionList,
                SynthesisDict,
            )

            is_single_step = (
                mode in ("single_step", "manual")
                or autonomous is False
                or any(w in message.lower() for w in [
                    "step by step", "single step", "one step at a time", "manual step", "pause after each", "first step only", "only the first step"
                ])
            )
            is_single_node = len(nodes) <= 1

            # Provenance setup
            step_prov["task_decomposition" if not is_single_node else "plan_decomposition"] = StepProvenance(
                stage="task_decomposition" if not is_single_node else "plan_decomposition",
                handled_by=exec_record.actual_model_id,
                runtime=exec_record.inference_runtime,
                is_custom_model=exec_record.inference_runtime == "transformers",
                is_fallback=exec_record.fallback_used,
                executed=True,
                details={
                    "plan_id": plan_id,
                    "nodes_count": len(nodes),
                    "mode": "task_request" if not is_single_node else "reasoned_single_step",
                },
            ).to_dict()

            val_auth_prov = StepProvenance(
                stage="validation_and_authorization",
                handled_by="security_gateway:scope_contract",
                runtime="policy_and_schema",
                is_custom_model=False,
                is_fallback=False,
                executed=True,
                details={
                    "authorized": True,
                    "target": extracted_target,
                    "plan_id": plan_id,
                    "scope_verified": True,
                },
            ).to_dict()

            context = EvidenceContext(
                target=extracted_target,
                session_id=session_id,
                plan_id=plan_id,
            )

            max_steps_cap = 1 if is_single_step else min(int(kwargs.get("max_steps", 8)), 8)
            step_count = 0
            consecutive_failures = 0
            executed_steps: List[Dict[str, Any]] = []
            nodes_executed: List[DAGNodeExecution] = []
            execution_provenances: List[Dict[str, Any]] = []
            halt_loop = False

            while step_count < max_steps_cap:
                ready_nodes = get_ready_nodes(plan_id, self.db_path)
                if not ready_nodes:
                    # Check for remaining queued nodes whose dependencies could not be satisfied
                    current_plan = get_plan(plan_id, self.db_path)
                    all_nodes = current_plan.get("nodes", []) if current_plan else []
                    node_status_map = {n["node_id"]: n["status"] for n in all_nodes}

                    unresolved_queued = [n for n in all_nodes if n["status"] == "queued"]
                    for unres in unresolved_queued:
                        deps = unres.get("dependencies", [])
                        failed_deps = [d for d in deps if node_status_map.get(d) in ("failed", "blocked", "skipped")]
                        block_reason = f"Blocked by failed/skipped dependency: {', '.join(failed_deps)}" if failed_deps else "Dependencies could not be satisfied."
                        update_node_status(
                            plan_id=plan_id,
                            node_id=unres["node_id"],
                            status="blocked",
                            result={"blocked": True, "reason": block_reason},
                            db_path=self.db_path,
                        )
                        nodes_executed.append(DAGNodeExecution(
                            node_id=unres["node_id"],
                            capability=unres["capability"],
                            label=unres.get("label", unres["node_id"]),
                            status="blocked",
                            skipped_reason=block_reason,
                        ))
                    break

                for node in ready_nodes:
                    if step_count >= max_steps_cap:
                        break

                    node_id = node.get("node_id")
                    capability = node.get("capability", "general_execution")
                    label = node.get("label", node_id)

                    # 1. Prerequisite Evidence Gate
                    can_run, reject_reason = dag_controller.check_prerequisite_evidence(node, context)
                    if not can_run:
                        logger.info(f"[AgentLoop] Node '{node_id}' ({capability}) skipped: {reject_reason}")
                        update_node_status(
                            plan_id=plan_id,
                            node_id=node_id,
                            status="skipped",
                            result={"skipped": True, "reason": reject_reason},
                            db_path=self.db_path,
                        )
                        nodes_executed.append(DAGNodeExecution(
                            node_id=node_id,
                            capability=capability,
                            label=label,
                            status="skipped",
                            skipped_reason=reject_reason,
                        ))
                        continue

                    step_count += 1
                    logger.info(f"[AgentLoop] Step {step_count}/{max_steps_cap}: Scheduling node '{node_id}' ({capability})")

                    # 2. Feed structured upstream observation into tool & argument construction
                    selected_tool, mapped_args, fallback_tool = dag_controller.select_tool_for_node(
                        node=node,
                        context=context,
                    )
                    if explicit_args:
                        mapped_args.update(explicit_args)
                    if extracted_target and "target" in mapped_args and not mapped_args.get("target"):
                        mapped_args["target"] = extracted_target

                    try:
                        sel_res = tool_selector.select(
                            goal=f"{message} - {capability}",
                            required_capability=capability,
                            session_id=session_id,
                            plan_step=node,
                        )
                        tool_selection_data = sel_res.to_dict()
                    except Exception as e:
                        tool_selection_data = {}
                        logger.warning(f"Could not calculate candidate scores: {e}")

                    node_prov: Dict[str, Any] = {}
                    # 3. Execute step's tool via the SAME adapter_registry.get() / adapter.execute() path
                    step_exec_result = self._execute_single_tool(
                        session_id=session_id,
                        task_id=f"{task_id}_{node_id}",
                        tool_id=selected_tool,
                        requested_args=mapped_args,
                        active_model_info=active_model_info,
                        exec_record=exec_record,
                        message=message,
                        t0=t0,
                        start_time_iso=start_time_iso,
                        parent_event=parent_event,
                        tool_selection_data=tool_selection_data,
                        step_prov=node_prov,
                        plan_id=plan_id,
                        node_id=node_id,
                    )

                    exec_details = step_exec_result.get("execution") or {}
                    exit_code = exec_details.get("exit_code", step_exec_result.get("exit_code", 0))
                    stdout = exec_details.get("stdout", "")
                    stderr = exec_details.get("stderr", "")
                    duration_ms = exec_details.get("duration_ms", 0.0)
                    observation = exec_details.get("observation") or {}
                    artifacts = exec_details.get("artifacts") or []
                    node_status = "success" if exit_code == 0 else "failed"

                    # Fallback retry if primary tool failed and fallback tool is available
                    if node_status == "failed" and exit_code != 403 and fallback_tool and fallback_tool != selected_tool:
                        logger.warning(f"[AgentLoop] Primary tool '{selected_tool}' failed (exit {exit_code}). Retrying with fallback '{fallback_tool}'")
                        fb_tool, fb_args, _ = dag_controller.select_tool_for_node(
                            node=node,
                            context=context,
                            previous_failures=[selected_tool],
                        )
                        fb_exec_result = self._execute_single_tool(
                            session_id=session_id,
                            task_id=f"{task_id}_{node_id}_fb",
                            tool_id=fb_tool,
                            requested_args=fb_args,
                            active_model_info=active_model_info,
                            exec_record=exec_record,
                            message=message,
                            t0=t0,
                            start_time_iso=start_time_iso,
                            parent_event=parent_event,
                            tool_selection_data=tool_selection_data,
                            step_prov=node_prov,
                            plan_id=plan_id,
                            node_id=node_id,
                        )
                        fb_details = fb_exec_result.get("execution") or {}
                        fb_exit = fb_details.get("exit_code", fb_exec_result.get("exit_code", 0))
                        if fb_exit == 0:
                            step_exec_result = fb_exec_result
                            selected_tool = fb_tool
                            mapped_args = fb_args
                            exec_details = fb_details
                            exit_code = fb_exit
                            stdout = exec_details.get("stdout", "")
                            stderr = exec_details.get("stderr", "")
                            duration_ms = exec_details.get("duration_ms", 0.0)
                            observation = exec_details.get("observation") or {}
                            artifacts = exec_details.get("artifacts") or []
                            node_status = "success"

                    # Update node status in DB
                    update_node_status(
                        plan_id=plan_id,
                        node_id=node_id,
                        status=node_status,
                        result={
                            "tool_id": selected_tool,
                            "status": node_status,
                            "exit_code": exit_code,
                            "command_line": exec_details.get("command_line", ""),
                            "duration_ms": duration_ms,
                            "observation": observation if node_status == "success" else {},
                        },
                        assigned_tool=selected_tool,
                        db_path=self.db_path,
                    )

                    # 4. Feed structured observation into EvidenceContext
                    context.ingest_observation(
                        node_id=node_id,
                        capability=capability,
                        tool_id=selected_tool,
                        obs=observation,
                        stdout=stdout,
                        exit_code=exit_code,
                        evidence_store=dag_controller.evidence_store,
                    )

                    node_exec = DAGNodeExecution(
                        node_id=node_id,
                        capability=capability,
                        label=label,
                        status=node_status,
                        tool_id=selected_tool,
                        requested_args=mapped_args,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_ms=duration_ms,
                        command_line=exec_details.get("command_line", ""),
                        typed_invocation=exec_details.get("typed_invocation"),
                        findings_count=len(context.findings),
                        artifacts=artifacts,
                    )
                    nodes_executed.append(node_exec)
                    executed_steps.append(step_exec_result)

                    step_provenance_item = StepProvenance(
                        stage="execution",
                        handled_by=selected_tool,
                        runtime="adapter",
                        is_custom_model=False,
                        is_fallback=exec_record.fallback_used or (selected_tool == fallback_tool),
                        executed=True,
                        details={
                            "node_id": node_id,
                            "capability": capability,
                            "status": node_status,
                            "exit_code": exit_code,
                            "duration_ms": duration_ms,
                        },
                    ).to_dict()
                    execution_provenances.append(step_provenance_item)

                    # Stream step result over WebSocket as it completes
                    self._stream_step_to_websocket(
                        step_result=step_exec_result,
                        plan_id=plan_id,
                        node_id=node_id,
                        session_id=session_id,
                        step_callback=kwargs.get("step_callback"),
                    )

                    # Stop condition: Unrecoverable scope rejection (exit_code 403)
                    if exit_code == 403:
                        logger.warning(f"[AgentLoop] Halting execution: Unrecoverable scope authorization failure on node '{node_id}' (exit code 403)")
                        halt_loop = True
                        break

                    # Stop condition: 3 consecutive failures
                    if node_status == "failed":
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            logger.warning(f"[AgentLoop] Halting execution: Reached 3 consecutive step failures.")
                            halt_loop = True
                            break
                    else:
                        consecutive_failures = 0

                if halt_loop:
                    break

            if not executed_steps:
                explanation = generate_plan_explanation(
                    plan=plan_dict,
                    goal=message,
                    target=extracted_target,
                    model_id=exec_record.actual_model_id,
                    runtime=exec_record.inference_runtime,
                    is_custom=exec_record.inference_runtime == "transformers",
                    is_fallback=exec_record.fallback_used,
                )
                return {
                    "intent": "task_request" if not is_single_node else "tool_request",
                    "plan_only": False,
                    "plan": plan_dict,
                    "plan_id": plan_id,
                    "session_id": session_id,
                    "task_id": task_id,
                    "reply": explanation,
                    "tool_executed": None,
                    "execution": None,
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                    "model_status": "transformers_custom_primary" if exec_record.inference_runtime == "transformers" else "llama.cpp_fallback",
                    "model_id": active_model_info.get("model_id"),
                    "model_role": active_model_info.get("role"),
                    "model_verification": model_verif,
                    "selected_model": exec_record.selected_model,
                    "actual_model_id": exec_record.actual_model_id,
                    "inference_runtime": exec_record.inference_runtime,
                    "processed_by_selected_model": exec_record.processed_by_selected_model,
                    "structured_output": exec_record.structured_output,
                    "selected_tool": None,
                    "validated_args": None,
                    "fallback_used": exec_record.fallback_used,
                    "fallback_reason": exec_record.fallback_reason,
                    "local_only": True,
                    "step_provenance": list(step_prov.values()),
                    "tools_executed_count": 0,
                    "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                    "handled_by_fallback": exec_record.fallback_used,
                }

            total_duration_ms = round((time.time() - t0) * 1000, 2)
            completed_nodes = [n for n in nodes_executed if n.status == "success"]
            failed_nodes = [n for n in nodes_executed if n.status == "failed"]
            skipped_nodes = [n for n in nodes_executed if n.status in ("skipped", "blocked")]

            if failed_nodes and not completed_nodes:
                overall_status = "failed"
            elif completed_nodes and (failed_nodes or skipped_nodes):
                overall_status = "partial"
            else:
                overall_status = "completed"

            # Update parent task graph status in SQLite
            try:
                conn = get_connection(self.db_path)
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE task_graphs SET status = ?, updated_at = ? WHERE plan_id = ?",
                        (overall_status, datetime.now(timezone.utc).isoformat(), plan_id),
                    )
                conn.close()
            except Exception as e:
                logger.debug(f"[AgentLoop] Could not update task_graphs status: {e}")

            # Assemble synthesis and reply
            if len(nodes) > 1 and not is_single_step:
                synthesis_result = dag_controller._synthesize_dag_execution(
                    plan_id=plan_id,
                    goal=message,
                    target=extracted_target,
                    overall_status=overall_status,
                    nodes_executed=nodes_executed,
                    context=context,
                    duration_s=round(total_duration_ms / 1000, 2),
                )
                final_reply = synthesis_result.get("reply", "")
                final_synthesis = SynthesisDict(synthesis_result)
            else:
                final_reply = executed_steps[0].get("reply", "")
                synth_data = executed_steps[0].get("synthesis")
                if isinstance(synth_data, dict):
                    final_synthesis = SynthesisDict(synth_data)
                elif synth_data is not None:
                    final_synthesis = synth_data
                else:
                    synthesis_result = dag_controller._synthesize_dag_execution(
                        plan_id=plan_id,
                        goal=message,
                        target=extracted_target,
                        overall_status=overall_status,
                        nodes_executed=nodes_executed,
                        context=context,
                        duration_s=round(total_duration_ms / 1000, 2),
                    )
                    final_synthesis = SynthesisDict(synthesis_result)

                if is_single_step and len(nodes) > 1:
                    plan_header = (
                        f"### 📋 Structured Task Plan (`{plan_id}`)\n"
                        f"- **Task Goal:** {message}\n"
                        f"- **Target Asset:** `{extracted_target or 'Identified in scope'}`\n"
                        f"- **Total Nodes:** `{len(nodes)}` • **Executing Node:** `{nodes_executed[0].node_id}` (`{nodes_executed[0].capability}`)\n\n"
                        f"---\n\n"
                    )
                    final_reply = plan_header + str(final_reply)

            # Combine step provenance preserving order and required stages
            combined_prov: List[Dict[str, Any]] = []
            seen_stages = set()
            for k in ["intent_classification", "task_decomposition", "plan_decomposition"]:
                if k in step_prov:
                    sp = step_prov[k]
                    sp_dict = sp.to_dict() if hasattr(sp, "to_dict") else sp
                    combined_prov.append(sp_dict)
                    seen_stages.add(sp_dict.get("stage"))

            if "validation_and_authorization" not in seen_stages:
                combined_prov.append(val_auth_prov)
                seen_stages.add("validation_and_authorization")

            for s in executed_steps:
                s_prov = s.get("step_provenance", [])
                if isinstance(s_prov, dict):
                    s_prov = list(s_prov.values())
                for p in s_prov:
                    p_dict = p.to_dict() if hasattr(p, "to_dict") else p
                    stg = p_dict.get("stage")
                    if stg not in ("execution",) and stg in seen_stages:
                        continue
                    combined_prov.append(p_dict)
                    seen_stages.add(stg)

            if "execution" not in seen_stages and execution_provenances:
                combined_prov.extend(execution_provenances)

            first_exec = executed_steps[0]
            first_tool = first_exec.get("tool_executed") or {
                "id": nodes_executed[0].tool_id if nodes_executed else "nmap.scan.v1",
                "name": nodes_executed[0].label if nodes_executed else "Tool Execution",
                "version": "1.0.0",
            }

            first_details = dict(first_exec.get("execution") or {})
            first_details.update({
                "nodes_completed": len(completed_nodes),
                "nodes_total": len(nodes),
                "duration_ms": total_duration_ms,
            })
            if "exit_code" not in first_details:
                first_details["exit_code"] = 0 if overall_status in ("completed", "partial") and len(completed_nodes) > 0 else 1

            ret_dict = {
                "intent": "tool_request" if (is_single_node and intent_res.intent == IntentType.TOOL_REQUEST) else "task_request",
                "plan_only": False,
                "plan": plan_dict,
                "plan_id": plan_id,
                "success": overall_status in ("completed", "partial") and len(completed_nodes) > 0,
                "session_id": session_id,
                "task_id": task_id,
                "reply": final_reply,
                "synthesis": final_synthesis,
                "tool_executed": first_tool,
                "execution": first_details,
                "tool_selection": first_exec.get("tool_selection") or tool_selection_data,
                "nodes_executed": DAGNodeExecutionList(nodes_executed),
                "evidence": asdict(context),
                "event_id": first_exec.get("event_id"),
                "event": first_exec.get("event"),
                "duration_ms": total_duration_ms,
                "model_status": "transformers_custom_primary" if exec_record.inference_runtime == "transformers" else "llama.cpp_fallback",
                "model_id": active_model_info.get("model_id"),
                "model_role": active_model_info.get("role"),
                "model_verification": model_verif,
                "selected_model": exec_record.selected_model,
                "actual_model_id": exec_record.actual_model_id,
                "inference_runtime": exec_record.inference_runtime,
                "processed_by_selected_model": exec_record.processed_by_selected_model,
                "structured_output": exec_record.structured_output,
                "selected_tool": first_tool.get("id"),
                "validated_args": first_exec.get("validated_args") or (nodes_executed[0].requested_args if nodes_executed else None),
                "fallback_used": exec_record.fallback_used,
                "fallback_reason": exec_record.fallback_reason,
                "local_only": True,
                "step_provenance": combined_prov,
                "tools_executed_count": len(executed_steps),
                "handled_by_custom_model": exec_record.inference_runtime == "transformers",
                "handled_by_fallback": exec_record.fallback_used,
            }

            if first_exec.get("scope_violation"):
                ret_dict["scope_violation"] = first_exec.get("scope_violation")

            return ret_dict


    def _extract_shell_args(self, message: str) -> Dict[str, Any]:
        """Extract command and args from message when formatted directly."""
        # Check if python command was specified
        if "sleep" in message:
            return {"command": "python", "args": ["-c", "import time; time.sleep(10)"], "timeout_ms": 15000}
        elif "echo" in message:
            return {"command": "python", "args": ["-c", "print('Hello from shell.run.v1 adapter')"]}
        elif "node" in message:
            return {"command": "node", "args": ["-e", "console.log('Node executed via shell.run.v1')"]}
        else:
            # Default safe command for testing
            return {"command": "python", "args": ["-c", "import sys; print(f'Python {sys.version.split()[0]} via supervisor')"]}

    def _extract_kali_args(self, message: str) -> Dict[str, Any]:
        """Extract command and args for Kali VM sandbox execution."""
        msg_lower = message.lower()
        if "nmap" in msg_lower:
            return {"command": "nmap", "args": ["--version"], "timeout_ms": 15000}
        elif "whoami" in msg_lower:
            return {"command": "whoami", "args": []}
        elif "ip" in msg_lower or "ifconfig" in msg_lower:
            return {"command": "ip", "args": ["addr", "show"]}
        elif "ps" in msg_lower:
            return {"command": "ps", "args": ["aux"]}
        elif "uptime" in msg_lower:
            return {"command": "uptime", "args": []}
        elif "id" in msg_lower:
            return {"command": "id", "args": []}
        else:
            return {"command": "uname", "args": ["-a"], "timeout_ms": 15000}

    def run_autonomous_task(
        self,
        goal: str = "",
        session_id: str = "",
        message: str = "",
        target: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Convenience method to execute a complete task graph autonomously from start to finish."""
        effective_message = message or goal or ""
        effective_session_id = session_id
        if goal.startswith("sess_") and not session_id.startswith("sess_") and " " in session_id:
            effective_session_id, effective_message = goal, session_id
        if not effective_session_id:
            effective_session_id = f"sess_auto_{uuid.uuid4().hex[:6]}"
        return self.execute_task(
            session_id=effective_session_id,
            message=effective_message,
            autonomous=True,
            **kwargs,
        )

    def run_autonomous_plan(
        self,
        plan_id: str,
        session_id: str,
        target: Optional[str] = None,
        goal: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Executes an existing plan DAG autonomously to completion using the DAGController."""
        from orchestrator.dag_controller import dag_controller
        return dag_controller.execute_plan(
            plan_id=plan_id,
            session_id=session_id,
            target=target,
            goal=goal,
            db_path=self.db_path,
            **kwargs,
        ).to_dict()

    def verify_finding(
        self,
        finding_id: str,
        allowed_targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Verifies a security finding with authorized, active checks (handshake, HTTP probe, banner).
        Enforces ScopeContract boundaries before emitting network packets.
        """
        from orchestrator.finding_verifier import FindingVerifier
        verifier = FindingVerifier(db_path=self.db_path)
        return verifier.verify_finding(finding_id, allowed_targets=allowed_targets)



def as_dict_event(event: Event) -> Dict[str, Any]:
    return {
        "session_id": event.session_id,
        "task_id": event.task_id,
        "timestamp": event.timestamp,
        "actor": event.actor,
        "tool_id": event.tool_id,
        "tool_version": event.tool_version,
        "requested_args": event.requested_args,
        "normalized_args": event.normalized_args,
        "process_id": event.process_id,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "exit_code": event.exit_code,
        "stdout_ref": event.stdout_ref,
        "stderr_ref": event.stderr_ref,
        "artifact_refs": event.artifact_refs,
        "screenshots": event.screenshots,
        "network_context": event.network_context,
        "result_summary": event.result_summary,
        "confidence": event.confidence,
        "parent_event": event.parent_event,
    }


AgentOrchestrator = AgentLoop
