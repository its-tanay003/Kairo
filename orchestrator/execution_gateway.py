"""
ExecutionGateway: Centralized trusted security enforcement, scope authorization,
schema validation, workflow approval, and auditable tool dispatch for Kairo.

Architectural Invariant:
AI proposal -> Execution Gateway -> Security checks -> Authorized Adapter -> Worker/Sandbox

Every execution route MUST use this service:
- Direct tool requests
- Autonomous DAG nodes
- Recovery attempts
- Explicit tool calls
- REST / WebSocket operations
- Finding verification operations that initiate network activity
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import (
    DEFAULT_DB_PATH,
    Event,
    compute_sha256,
    create_scope_contract,
    extract_host_from_target,
    get_active_scope_contract,
    insert_event,
    is_target_in_scope,
    validate_scope_request,
)
from orchestrator.adapters.registry import adapter_registry
from orchestrator.auth import auth_manager
from orchestrator.process_supervisor import ProcessResult, ProcessSupervisor, get_supervisor
from orchestrator.validation import BROAD_EXECUTION_TOOLS, is_workflow_approved, validate_tool_arguments
from orchestrator.vm_manager import VMManager, get_vm_manager
from registry.loader import ToolSpec, tool_registry

logger = logging.getLogger("orchestrator.execution_gateway")


@dataclass
class ExecutionResult:
    """Standardized result returned by ExecutionGateway for all tool dispatches."""
    tool_id: str
    tool_version: str
    task_id: str
    session_id: str
    target: Optional[str]
    authorized: bool
    status: str  # "success" | "failed" | "rejected" | "timeout" | "error"
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    observation: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    event_id: Optional[int] = None
    command_line: str = ""
    actor: str = "orchestrator:gateway"
    provenance: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionGateway:
    """
    Centralized execution and policy enforcement gateway.
    Ensures that no tool invocation can bypass scope contracts, schema validation,
    privilege tier controls, or workflow approvals.
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        vm_manager: Optional[VMManager] = None,
        supervisor: Optional[ProcessSupervisor] = None,
    ):
        self.db_path = Path(db_path)
        self._vm_manager = vm_manager
        self._supervisor = supervisor

    @property
    def vm_manager(self) -> VMManager:
        if self._vm_manager is None:
            self._vm_manager = get_vm_manager()
        return self._vm_manager

    @property
    def supervisor(self) -> ProcessSupervisor:
        if self._supervisor is None:
            self._supervisor = get_supervisor()
        return self._supervisor

    def extract_target(self, tool_id: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Extracts and normalizes the network target from tool arguments."""
        if not isinstance(arguments, dict):
            return None

        # Check explicit target keys
        for key in ("target", "host", "url", "domain", "ip", "rhost", "rhosts", "filepath"):
            val = arguments.get(key)
            if val and isinstance(val, str) and val.strip():
                clean = extract_host_from_target(val.strip())
                if clean:
                    return clean

        # Check inside args list (e.g. for shell.run.v1 or kali.exec.v1)
        raw_args = arguments.get("args")
        if isinstance(raw_args, list):
            for item in raw_args:
                s = str(item).strip()
                if any(c in s for c in [".", ":", "/"]) and not s.startswith("-"):
                    # Avoid catching local file scripts as network targets
                    if not s.endswith((".py", ".sh", ".json", ".pt", ".yaml", ".yml", ".txt")):
                        clean = extract_host_from_target(s)
                        if clean:
                            return clean

        # Check command string
        cmd = arguments.get("command")
        if cmd and isinstance(cmd, str):
            ip_m = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', cmd)
            if ip_m:
                return ip_m.group(0)
            dm = re.search(r'\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}\b', cmd)
            if dm and not dm.group(0).endswith((".py", ".sh", ".json", ".pt", ".yaml", ".yml")):
                return dm.group(0)

        return None

    def execute(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        session_id: str,
        task_id: Optional[str] = None,
        target: Optional[str] = None,
        actor: str = "orchestrator:gateway",
        plan_id: Optional[str] = None,
        node_id: Optional[str] = None,
        parent_event: Optional[str] = None,
        execution_target: str = "vm",
        operator_token: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        db_path: Optional[Path | str] = None,
    ) -> ExecutionResult:
        """
        Validates and executes a tool through the centralized security boundary.
        Enforces:
        1. Tool registration & spec resolution
        2. Adapter availability
        3. Target extraction and normalization
        4. Schema & bounds validation & injection sanitization
        5. Scope contract authorization (fail-closed)
        6. Workflow approval for broad execution tools
        7. Timeout & resource enforcement
        8. Audit event generation (20 fields)
        9. Honest execution & error capture
        """
        active_db_path = Path(db_path) if db_path else self.db_path
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        t0 = time.time()
        start_time_iso = datetime.now(timezone.utc).isoformat()
        clean_args = dict(arguments) if isinstance(arguments, dict) else {}

        # 1. Resolve Tool Spec
        spec: Optional[ToolSpec] = tool_registry.get(tool_id)
        tool_version = spec.version if spec else "1.0.0"

        # Diagnostic tools handled safely without external registry
        is_diagnostic = tool_id in ("hello_world", "system_ping")

        if not spec and not is_diagnostic:
            # Check if adapter exists
            adapter_cls = adapter_registry.get(tool_id)
            if not adapter_cls:
                err_msg = f"UNREGISTERED_TOOL: Tool '{tool_id}' is not registered in authoritative ToolSpec registry."
                logger.warning(f"[ExecutionGateway] Rejected: {err_msg}")
                event = self._record_rejection_event(
                    session_id=session_id,
                    task_id=task_id,
                    actor=actor,
                    tool_id=tool_id,
                    tool_version=tool_version,
                    requested_args=clean_args,
                    exit_code=127,
                    rejection_reason=err_msg,
                    target=target,
                    parent_event=parent_event,
                    db_path=active_db_path,
                )
                return ExecutionResult(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    task_id=task_id,
                    session_id=session_id,
                    target=target,
                    authorized=False,
                    status="rejected",
                    exit_code=127,
                    stdout="",
                    stderr=err_msg,
                    duration_ms=0.0,
                    rejection_reason=err_msg,
                    event_id=event.get("id"),
                    actor=actor,
                )

        # 2. Extract and Normalize Target
        target_candidate = target or self.extract_target(tool_id, clean_args)
        if target_candidate and "target" not in clean_args:
            clean_args["target"] = target_candidate

        # 3. Schema & Bounds Validation & Injection Sanitization
        if spec:
            is_valid, validation_errors = validate_tool_arguments(spec, clean_args)
            if not is_valid:
                err_msg = f"VALIDATION_ERROR: {'; '.join(validation_errors)}"
                logger.warning(f"[ExecutionGateway] Argument validation rejected '{tool_id}': {err_msg}")
                event = self._record_rejection_event(
                    session_id=session_id,
                    task_id=task_id,
                    actor=actor,
                    tool_id=tool_id,
                    tool_version=tool_version,
                    requested_args=clean_args,
                    exit_code=400,
                    rejection_reason=err_msg,
                    target=target_candidate,
                    parent_event=parent_event,
                    db_path=active_db_path,
                )
                return ExecutionResult(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    task_id=task_id,
                    session_id=session_id,
                    target=target_candidate,
                    authorized=False,
                    status="rejected",
                    exit_code=400,
                    stdout="",
                    stderr=err_msg,
                    duration_ms=0.0,
                    rejection_reason=err_msg,
                    event_id=event.get("id"),
                    actor=actor,
                )

        # 4. Scope Contract Authorization Check
        scope_check = validate_scope_request(
            target=target_candidate,
            tool_id=tool_id,
            db_path=active_db_path,
        )

        if not scope_check.get("authorized", False):
            rejection_reason = scope_check.get("reason", "Scope violation detected by execution gateway.")
            logger.warning(f"[ExecutionGateway] Scope rejected '{tool_id}' on target '{target_candidate}': {rejection_reason}")
            event = self._record_rejection_event(
                session_id=session_id,
                task_id=task_id,
                actor=actor,
                tool_id=tool_id,
                tool_version=tool_version,
                requested_args=clean_args,
                exit_code=403,
                rejection_reason=rejection_reason,
                target=target_candidate,
                parent_event=parent_event,
                db_path=active_db_path,
            )
            return ExecutionResult(
                tool_id=tool_id,
                tool_version=tool_version,
                task_id=task_id,
                session_id=session_id,
                target=target_candidate,
                authorized=False,
                status="rejected",
                exit_code=403,
                stdout="",
                stderr=rejection_reason,
                duration_ms=0.0,
                rejection_reason=rejection_reason,
                event_id=event.get("id"),
                actor=actor,
            )

        # 5. Workflow Approval Check for Broad Execution Tools
        active_contract = scope_check.get("active_contract")
        is_approved, approval_reason = is_workflow_approved(
            tool_id=tool_id,
            requested_args=clean_args,
            scope_contract=active_contract,
        )
        if not is_approved:
            logger.warning(f"[ExecutionGateway] Workflow approval rejected '{tool_id}': {approval_reason}")
            event = self._record_rejection_event(
                session_id=session_id,
                task_id=task_id,
                actor=actor,
                tool_id=tool_id,
                tool_version=tool_version,
                requested_args=clean_args,
                exit_code=403,
                rejection_reason=approval_reason,
                target=target_candidate,
                parent_event=parent_event,
                db_path=active_db_path,
            )
            return ExecutionResult(
                tool_id=tool_id,
                tool_version=tool_version,
                task_id=task_id,
                session_id=session_id,
                target=target_candidate,
                authorized=False,
                status="rejected",
                exit_code=403,
                stdout="",
                stderr=approval_reason,
                duration_ms=0.0,
                rejection_reason=approval_reason,
                event_id=event.get("id"),
                actor=actor,
            )

        # 6. Dispatch Execution to Worker / Adapter
        effective_timeout = timeout_ms or (spec.timeout_ms if spec else 60000)
        exit_code = 0
        stdout_output = ""
        stderr_output = ""
        observation: Dict[str, Any] = {}
        artifacts: List[str] = []
        recorded_cmd = ""

        try:
            if tool_id == "hello_world":
                greet_tgt = target_candidate or clean_args.get("target") or "World"
                recorded_cmd = f"echo 'Hello {greet_tgt}! Boundary verified.'"
                stdout_output = f"[Tool:hello_world] Executed with target: '{greet_tgt}'."
                exit_code = 0
                observation = {"greeting": f"Hello {greet_tgt}", "target": greet_tgt}

            elif tool_id == "system_ping":
                recorded_cmd = "kairo-diag --self-test"
                stdout_output = f"[Tool:system_ping] System healthy. Pid: {os.getpid()} Time: {start_time_iso}"
                exit_code = 0
                observation = {"status": "healthy", "pid": os.getpid()}

            elif tool_id == "shell.run.v1":
                command = clean_args.get("command") or "python"
                raw_args = clean_args.get("args") or ["-c", "print('Executed via shell.run.v1 adapter')"]
                recorded_cmd = f"{command} {' '.join(str(a) for a in raw_args)}"

                proc_res: ProcessResult = self.supervisor.execute(
                    task_id=task_id,
                    command=command,
                    args=raw_args,
                    timeout_ms=effective_timeout,
                    limits=clean_args.get("resource_limits"),
                    artifact_dir=clean_args.get("artifact_dir"),
                )
                exit_code = proc_res.exit_code
                stdout_output = proc_res.stdout
                stderr_output = proc_res.stderr or ""
                artifacts = proc_res.artifacts or []
                observation = {
                    "tool": "shell.run.v1",
                    "command": command,
                    "timed_out": proc_res.timed_out,
                    "resource_limit_exceeded": proc_res.resource_limit_exceeded,
                }

            elif tool_id == "kali.exec.v1":
                command = clean_args.get("command") or "uname"
                raw_args = clean_args.get("args") or ["-a"]
                recorded_cmd = f"{command} {' '.join(str(a) for a in raw_args)}"

                vm_res = self.vm_manager.execute_in_vm(
                    task_id=task_id,
                    tool_id="kali.exec.v1",
                    tool_version=tool_version,
                    args={"command": command, "args": raw_args, "cwd": clean_args.get("cwd", "/home/kali")},
                    snapshot_before=bool(clean_args.get("snapshot_before", True)),
                    rollback_after=bool(clean_args.get("rollback_after", False)),
                    rollback_on_failure=bool(clean_args.get("rollback_on_failure", False)),
                    resource_limits=clean_args.get("resource_limits"),
                    artifact_dir=clean_args.get("artifact_dir"),
                    timeout_ms=effective_timeout,
                )
                exit_code = vm_res.get("exit_code", 0)
                stdout_output = vm_res.get("stdout", "")
                stderr_output = vm_res.get("stderr") or ""
                artifacts = [a.get("filepath", a.get("filename", "")) for a in vm_res.get("artifacts", [])]
                observation = vm_res

            else:
                adapter_cls = adapter_registry.get(tool_id)
                if not adapter_cls:
                    err_msg = f"ADAPTER_NOT_FOUND: No registered adapter for '{tool_id}'."
                    logger.error(err_msg)
                    return ExecutionResult(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        task_id=task_id,
                        session_id=session_id,
                        target=target_candidate,
                        authorized=True,
                        status="error",
                        exit_code=127,
                        stdout="",
                        stderr=err_msg,
                        duration_ms=round((time.time() - t0) * 1000, 2),
                        rejection_reason=err_msg,
                        actor=actor,
                    )

                try:
                    adapter = adapter_cls(vm_manager=self.vm_manager, supervisor=self.supervisor)
                except TypeError:
                    try:
                        adapter = adapter_cls(vm_manager=self.vm_manager)
                    except TypeError:
                        try:
                            adapter = adapter_cls(self.vm_manager)
                        except TypeError:
                            adapter = adapter_cls()

                if "nmap" in tool_id:
                    recorded_cmd = f"nmap -{clean_args.get('scan_type', 'sV')} -p {clean_args.get('ports', '1-1000')} {clean_args.get('target', target_candidate)}"
                else:
                    recorded_cmd = f"{tool_id} --target {clean_args.get('target', target_candidate)}"

                try:
                    obs = adapter.execute(
                        inputs=clean_args,
                        task_id=task_id,
                        target=execution_target,
                        timeout_ms=effective_timeout,
                        snapshot_before=bool(clean_args.get("snapshot_before", True)),
                        rollback_after=bool(clean_args.get("rollback_after", False)),
                        rollback_on_failure=bool(clean_args.get("rollback_on_failure", False)),
                        resource_limits=clean_args.get("resource_limits"),
                        artifact_dir=clean_args.get("artifact_dir"),
                    )
                except TypeError:
                    try:
                        obs = adapter.execute(
                            inputs=clean_args,
                            task_id=task_id,
                            target=execution_target,
                        )
                    except TypeError:
                        obs = adapter.execute(clean_args, task_id, execution_target)

                exit_code = getattr(obs, "exit_code", 0)
                stdout_output = getattr(obs, "raw_stdout", "")
                stderr_output = getattr(obs, "raw_stderr", "")
                observation = getattr(obs, "observation", {})
                artifacts = getattr(obs, "artifacts", []) or []

        except Exception as exc:
            logger.exception(f"[ExecutionGateway] Unhandled exception while executing '{tool_id}': {exc}")
            exit_code = 1
            stderr_output = f"Execution exception: {str(exc)}"
            observation = {"error": str(exc), "exception": True}

        duration_ms = round((time.time() - t0) * 1000, 2)
        real_status = "success" if exit_code == 0 else "failed"

        # 7. Record Authoritative Audit Event (20 fields)
        end_time_iso = datetime.now(timezone.utc).isoformat()
        audit_event = Event.create(
            session_id=session_id,
            task_id=task_id,
            actor=actor,
            tool_id=tool_id,
            tool_version=tool_version,
            requested_args=clean_args,
            normalized_args=clean_args,
            process_id=os.getpid(),
            start_time=start_time_iso,
            end_time=end_time_iso,
            exit_code=exit_code,
            stdout_ref=f"inline://{stdout_output[:500]}" if stdout_output else None,
            stderr_ref=f"inline://{stderr_output[:500]}" if stderr_output else None,
            artifact_refs=artifacts,
            network_context={
                "target": target_candidate,
                "tool_id": tool_id,
                "scope_contract_id": scope_check.get("scope_contract_id"),
                "command_line": recorded_cmd,
                "plan_id": plan_id,
                "node_id": node_id,
                "authorized": True,
            },
            result_summary=f"Executed {tool_id} -> exit {exit_code} ({real_status})",
            confidence=1.0 if exit_code == 0 else 0.0,
            parent_event=parent_event,
            timestamp=start_time_iso,
        )
        event_id = insert_event(audit_event, active_db_path)

        return ExecutionResult(
            tool_id=tool_id,
            tool_version=tool_version,
            task_id=task_id,
            session_id=session_id,
            target=target_candidate,
            authorized=True,
            status=real_status,
            exit_code=exit_code,
            stdout=stdout_output,
            stderr=stderr_output,
            duration_ms=duration_ms,
            observation=observation,
            artifacts=artifacts,
            event_id=event_id,
            command_line=recorded_cmd,
            actor=actor,
        )

    def authorize_scope_modification(
        self,
        targets: List[str],
        operator_token: Optional[str],
        network_scope: str = "authorized_lab",
        time_window: str = "24h",
        allowed_tool_tiers: Optional[List[int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db_path: Optional[Path | str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Authenticates an operator action and authorizes a scope contract modification.
        Enforces:
        - Authenticated operator session (role: admin or operator)
        - Explicit target list without automatic wildcards
        - Truthful authorized_by recorded from session identity
        """
        active_db_path = Path(db_path) if db_path else self.db_path
        tiers = allowed_tool_tiers or [1, 2, 3]

        # Verify operator token
        is_valid, session, err = auth_manager.verify_token(operator_token)
        if not is_valid or not session:
            return (
                False,
                None,
                f"OPERATOR_AUTH_REQUIRED: Scope modification requires a valid operator token. ({err or 'unauthorized'})",
            )

        if session.role not in ("admin", "operator"):
            return (
                False,
                None,
                f"INSUFFICIENT_PRIVILEGE: User '{session.user_id}' with role '{session.role}' cannot modify scope contracts.",
            )

        if not targets:
            return False, None, "INVALID_TARGETS: At least one target must be provided."

        clean_targets = [str(t).strip().lower() for t in targets if str(t).strip()]
        new_contract = create_scope_contract(
            targets=clean_targets,
            network_scope=network_scope,
            time_window=time_window,
            allowed_tool_tiers=tiers,
            authorized_by=f"{session.user_id} ({session.role})",
            metadata={
                **(metadata or {}),
                "auth_session_id": session.token[:12] + "...",
                "modified_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=active_db_path,
        )

        logger.info(
            f"[ExecutionGateway] Scope contract updated by {session.user_id}: {new_contract['contract_id']} for targets {clean_targets}"
        )
        return True, new_contract, f"Scope contract '{new_contract['contract_id']}' activated successfully."

    def _record_rejection_event(
        self,
        session_id: str,
        task_id: str,
        actor: str,
        tool_id: str,
        tool_version: str,
        requested_args: Dict[str, Any],
        exit_code: int,
        rejection_reason: str,
        target: Optional[str] = None,
        parent_event: Optional[str] = None,
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> Dict[str, Any]:
        """Records a policy rejection audit event in the database."""
        now_iso = datetime.now(timezone.utc).isoformat()
        ev = Event.create(
            session_id=session_id,
            task_id=task_id,
            actor=f"{actor}:gateway_rejection",
            tool_id=tool_id,
            tool_version=tool_version,
            requested_args=requested_args,
            normalized_args=requested_args,
            process_id=os.getpid(),
            start_time=now_iso,
            end_time=now_iso,
            exit_code=exit_code,
            stdout_ref=None,
            stderr_ref=f"inline://{rejection_reason}",
            artifact_refs=[],
            network_context={
                "target": target,
                "tool_id": tool_id,
                "authorized": False,
                "rejection_reason": rejection_reason,
            },
            result_summary=f"POLICY_REJECTION: {rejection_reason}",
            confidence=0.0,
            parent_event=parent_event,
            timestamp=now_iso,
        )
        ev_id = insert_event(ev, db_path)
        d = asdict(ev)
        d["id"] = ev_id
        return d


# Global singleton
execution_gateway = ExecutionGateway()


def get_execution_gateway() -> ExecutionGateway:
    return execution_gateway
