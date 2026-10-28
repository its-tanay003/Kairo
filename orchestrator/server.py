"""
FastAPI Server for Orchestrator. Exposes endpoints to trigger agent loop, query events,
and activate SIGKILL kill switch for running supervisor processes.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Union
import uuid

logger = logging.getLogger("kairo.server")

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException, Response, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from orchestrator.vnc_server import vnc_server
from orchestrator.execution_gateway import execution_gateway, ExecutionGateway

from dataclasses import asdict
from events.db import (
    Event,
    get_connection,
    insert_event,
    get_events_by_session,
    get_recent_events,
    get_artifacts_by_task,
    get_artifact_by_id,
    verify_artifact_file,
    get_plan,
    list_plans,
    update_node_status,
    get_ready_nodes,
    list_tool_memories,
    get_tool_memory,
    record_tool_execution,
    ScopeContract,
    create_scope_contract,
    get_active_scope_contract,
    list_scope_contracts,
    seed_default_scope_contract,
    validate_scope_request,
    get_tool_tier,
    is_target_in_scope,
    Project,
    create_project,
    get_project,
    list_projects,
    update_project,
    update_project_shared_state,
    add_project_collaborator,
    remove_project_collaborator,
    seed_default_shared_project,
    query_audit_timeline,
    get_audit_stats,
)
from orchestrator.agent import AgentLoop
from orchestrator.model_center import model_center
from orchestrator.planner import planner
from orchestrator.process_supervisor import supervisor
from orchestrator.vm_manager import vm_manager
from orchestrator.tool_selector import tool_selector
from orchestrator.observer import observer
from orchestrator.critic import critic
from orchestrator.recovery_agent import recovery_agent
from orchestrator.cognitive_engine import cognitive_engine
from orchestrator.reporter import reporter
from orchestrator.evidence_store import (
    evidence_store,
    Finding,
    EvidenceClass,
)
from orchestrator.report_generator import report_generator
from orchestrator.adapters.registry import adapter_registry
from orchestrator.adapters.gui_base import BaseGuiAdapter
from orchestrator.kali_connector import ExecutionPlaneType, SIMULATION_NOTICE_TEXT
from orchestrator.training_manager import training_manager
from orchestrator.benchmark_manager import benchmark_manager
from orchestrator.model_evolution_controller import evolution_controller
from orchestrator.tool_knowledge_center import tool_knowledge_center
from orchestrator.update_manager import update_manager, UpdatePolicy



app = FastAPI(title="Agent Orchestrator Service", version="1.0.0")

allowed_origins_env = os.environ.get("KAIRO_ALLOWED_ORIGINS", "")
if allowed_origins_env.strip():
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "tauri://localhost",
        "http://tauri.localhost",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if os.environ.get("KAIRO_SECURE_CORS", "false").lower() in ("true", "1") else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = AgentLoop()


@app.on_event("startup")
def server_startup_event():
    """
    On server boot, initiate background auto-start of isolated Kali worker if not already online.
    Runs in a detached daemon thread so server startup remains immediate and non-blocking.
    """
    import threading
    def _bg_autostart_worker():
        auto_start_enabled = os.environ.get("KAIRO_AUTOSTART_VM", "true").lower() in ("true", "1", "yes")
        if not auto_start_enabled:
            logger.info("[Startup] KAIRO_AUTOSTART_VM is disabled; skipping VM auto-start.")
            return
        if not vm_manager.is_worker_online(timeout_sec=1.5):
            logger.info("[Startup] Kali worker is offline. Initiating background auto-start...")
            vm_manager.ensure_worker_online(timeout_sec=50, auto_start=True)
        else:
            logger.info(f"[Startup] Kali worker is already ONLINE on {vm_manager.worker_url}.")

    threading.Thread(target=_bg_autostart_worker, daemon=True, name="kairo_worker_autostart").start()


class RunRequest(BaseModel):
    session_id: str
    message: str
    task_id: Optional[str] = None
    parent_event: Optional[str] = None
    explicit_tool: Optional[str] = None
    explicit_args: Optional[Dict[str, Any]] = None
    model_id: Optional[str] = None
    autonomous: Optional[bool] = None
    mode: Optional[str] = None


class KillRequest(BaseModel):
    task_id: str


class VMSnapshotRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = ""


class VMRollbackRequest(BaseModel):
    name: Optional[str] = "kairo_worker_ready"


class VMExecuteRequest(BaseModel):
    task_id: Optional[str] = None
    session_id: Optional[str] = "vm_session"
    command: str
    args: Optional[List[str]] = []
    cwd: Optional[str] = "/home/kali"
    timeout_ms: Optional[int] = 30000
    snapshot_before: Optional[bool] = True
    rollback_after: Optional[bool] = False
    rollback_on_failure: Optional[bool] = False
    resource_limits: Optional[Dict[str, Any]] = None
    artifact_dir: Optional[str] = None
    operator_token: Optional[str] = None
    workflow_token: Optional[str] = None
    target: Optional[str] = None


class GatewayExecuteRequest(BaseModel):
    session_id: str
    task_id: str
    tool_id: str
    tool_version: Optional[str] = "1.0.0"
    arguments: Dict[str, Any]
    target: Optional[str] = None
    operator_token: Optional[str] = None
    workflow_token: Optional[str] = None
    timeout_ms: Optional[int] = None
    execution_plane: Optional[str] = "auto"


class ChatRequest(BaseModel):
    session_id: str
    message: str
    task_id: Optional[str] = None
    parent_event: Optional[str] = None
    explicit_tool: Optional[str] = None
    explicit_args: Optional[Dict[str, Any]] = None
    model_id: Optional[str] = None
    autonomous: Optional[bool] = None
    mode: Optional[str] = None


class ArtifactVerifyRequest(BaseModel):
    filepath: Optional[str] = None
    expected_sha256: Optional[str] = None
    artifact_id: Optional[int] = None


class PlanDecomposeRequest(BaseModel):
    goal: str
    session_id: Optional[str] = None
    prefer_llm: Optional[bool] = True


class PlanNodeStatusRequest(BaseModel):
    status: str
    result: Optional[Any] = None
    assigned_tool: Optional[str] = None


class PlanExecuteRequest(BaseModel):
    session_id: Optional[str] = None
    target: Optional[str] = None
    goal: Optional[str] = None
    max_steps: Optional[int] = 50
    stop_on_critical_failure: Optional[bool] = True
    mode: Optional[str] = "autonomous"  # "autonomous", "plan_only", "step_by_step", "manual"


class UpdateApplyRequest(BaseModel):
    item_id: str
    create_snapshot: Optional[bool] = True


class UpdateRollbackRequest(BaseModel):
    snapshot_name: str


class UpdatePolicyRequest(BaseModel):
    policy: str


class ToolSelectRequest(BaseModel):
    goal: Optional[str] = None
    intent: Optional[str] = None
    required_capability: Optional[str] = None
    capability: Optional[str] = None
    session_id: Optional[str] = "default_session"
    top_k: Optional[int] = 3
    environment: Optional[Dict[str, Any]] = None
    budget: Optional[float] = None
    plan_step: Optional[Dict[str, Any]] = None
    intended_capability: Optional[str] = None
    intended_category: Optional[str] = None
    planner_output: Optional[Any] = None


class ScopeContractCreateRequest(BaseModel):
    targets: List[str]
    network_scope: str = "authorized_lab"
    time_window: str = "8h"
    allowed_tool_tiers: Optional[List[int]] = None
    authorized_by: Optional[str] = "secops_lead@kairo.internal"
    operator_token: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ScopeValidateRequest(BaseModel):
    target: Optional[str] = None
    tool_id: Optional[str] = None
    tool_tier: Optional[int] = None  # Deprecated per ADR-004


class ObserverRequest(BaseModel):
    tool_id: str
    stdout: str
    stderr: Optional[str] = ""
    exit_code: Optional[int] = 0
    meta: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = 0.0


class CriticRequest(BaseModel):
    node: Dict[str, Any]
    plan_goal: str
    observation: Dict[str, Any]
    previous_observations: Optional[List[Dict[str, Any]]] = None
    attempt_number: Optional[int] = 1


class RecoveryRequest(BaseModel):
    plan_id: str
    node: Dict[str, Any]
    current_tool: str
    current_args: Dict[str, Any]
    stdout: str
    stderr: Optional[str] = ""
    exit_code: Optional[int] = 1
    timed_out: Optional[bool] = False
    parser_mismatch: Optional[bool] = False
    critic_status: Optional[str] = ""
    critique_msg: Optional[str] = ""
    session_id: Optional[str] = "recovery_session"


class NodeExecuteRequest(BaseModel):
    max_attempts: Optional[int] = 3


class GuiExecuteRequest(BaseModel):
    tool_id: str = "burpsuite.gui.v1"
    action: str = "workflow"  # "launch", "workflow", "click", "type", "extract_state", "screenshot", "stop"
    workflow: Optional[str] = "init_project"
    params: Optional[Dict[str, Any]] = None
    x: Optional[int] = None
    y: Optional[int] = None
    control_id: Optional[str] = None
    text: Optional[str] = None
    caption: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = "gui_session"


@app.get("/health")
def health():
    vm_stat = vm_manager.get_status()
    return {
        "status": "healthy",
        "service": "orchestrator",
        "llama_cpp": {
            "healthy": agent.llama_client.is_healthy(),
            "url": agent.llama_client.base_url,
        },
        "vm_sandbox": {
            "name": vm_stat.get("vm_name"),
            "running": vm_stat.get("running", False),
            "vm_state": vm_stat.get("vm_state"),
            "worker_online": vm_stat.get("worker_online", False),
            "snapshots_count": vm_stat.get("snapshots_count", 0),
        },
        "registered_tools": [t.id for t in agent.registry.list_tools()],
        "active_processes": len(supervisor.list_active()),
    }


from orchestrator.kali_connector import kali_connector
from orchestrator.auth import auth_manager
from orchestrator.workspace_manager import workspace_manager, WorkspaceStatus


class TokenRequest(BaseModel):
    user_id: Optional[str] = "operator"
    role: Optional[str] = "operator"
    client_type: Optional[str] = "browser-desktop"
    metadata: Optional[Dict[str, Any]] = None


class WorkspaceProvisionRequest(BaseModel):
    project_name: str
    session_id: str
    owner_id: Optional[str] = "default_user"
    network_isolated: Optional[bool] = True
    metadata: Optional[Dict[str, Any]] = None


@app.get("/model-center")
def get_model_center_status():
    """Reports which model is currently loaded, VRAM/RAM usage, and context length."""
    return model_center.get_status(llama_url=agent.llama_client.base_url)


class ModelSelectRequest(BaseModel):
    model_id: str


@app.post("/model-center/select")
def select_model_endpoint(req: ModelSelectRequest):
    """Activates a model checkpoint in Model Center."""
    try:
        updated = model_center.select_model(req.model_id)
        return {"success": True, "active_model": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/execution-plane")
def get_execution_plane_endpoint():
    """Reports detected local execution plane (Linux native, Windows WSL2, macOS Virtualization)."""
    return kali_connector.get_status()


# --- Auth & Session State Endpoints ---

@app.post("/auth/token")
def issue_token_endpoint(req: TokenRequest):
    """Issues an authenticated session token for browser or mobile client."""
    sess = auth_manager.issue_token(
        user_id=req.user_id or "operator",
        role=req.role or "operator",
        client_type=req.client_type or "browser-desktop",
        metadata=req.metadata,
    )
    return sess.to_dict()


@app.get("/auth/verify")
def verify_token_endpoint(token: Optional[str] = None):
    """Verifies token validity and returns session state."""
    is_valid, sess, err = auth_manager.verify_token(token)
    if not is_valid:
        raise HTTPException(status_code=401, detail=err or "Unauthorized")
    return {"valid": True, "session": sess.to_dict() if sess else None}


@app.get("/auth/sessions")
def list_sessions_endpoint():
    """Lists active client sessions and connection types."""
    return {"sessions": auth_manager.list_active_sessions()}


# --- Workspace Manager Endpoints (Disposable Kali VM per project/session) ---

@app.post("/workspaces/provision")
def provision_workspace_endpoint(req: WorkspaceProvisionRequest):
    """Server-side provisioning of disposable Kali sandbox VM per project/session."""
    ws = workspace_manager.provision_disposable_workspace(
        project_name=req.project_name,
        session_id=req.session_id,
        owner_id=req.owner_id or "default_user",
        network_isolated=bool(req.network_isolated),
        custom_metadata=req.metadata,
    )
    return {"workspace": ws.to_dict(), **ws.to_dict()}


@app.get("/workspaces")
def list_workspaces_endpoint(status: Optional[str] = None, project_name: Optional[str] = None):
    """Lists managed workspaces across projects and sessions."""
    workspaces = workspace_manager.list_workspaces(status=status, project_name=project_name)
    return {"workspaces": [w.to_dict() for w in workspaces]}


@app.get("/workspaces/{workspace_id}")
def get_workspace_endpoint(workspace_id: str):
    """Retrieves metadata and status for a specific workspace."""
    ws = workspace_manager.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    return {"workspace": ws.to_dict(), **ws.to_dict()}


@app.post("/workspaces/{workspace_id}/terminate")
def terminate_workspace_endpoint(workspace_id: str, purge_storage: bool = False):
    """Tears down and disposes of ephemeral Kali VM / workspace."""
    res = workspace_manager.terminate_workspace(workspace_id, purge_storage=purge_storage)
    return res


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    """Unified conversational AI and operational task execution endpoint."""
    try:
        autonomous_flag = req.autonomous
        if req.mode in ("autonomous_task", "autonomous"):
            autonomous_flag = True
        elif req.mode in ("single_step", "manual"):
            autonomous_flag = False

        result = agent.execute_task(
            session_id=req.session_id,
            message=req.message,
            task_id=req.task_id,
            parent_event=req.parent_event,
            explicit_tool=req.explicit_tool,
            explicit_args=req.explicit_args,
            model_id=req.model_id,
            autonomous=autonomous_flag,
            mode=req.mode,
        )
        return result
    except Exception as e:
        logger.exception(f"Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
def chat_stream_endpoint(req: ChatRequest):
    """
    Server-Sent Events (SSE) streaming endpoint for real-time lifecycle monitoring of autonomous execution.
    Emits unified lifecycle events:
    - intent_classified
    - plan_created
    - step_started
    - step_output_chunk
    - step_completed
    - agent_message_chunk
    - next_step_recommendations
    """
    import queue
    import threading

    q: queue.Queue = queue.Queue()

    def run_worker():
        try:
            # 1. Intent Classified
            intent = "tool_request"
            if hasattr(agent, "intent_classifier") and agent.intent_classifier:
                try:
                    c_res = agent.intent_classifier.classify(req.message)
                    intent = getattr(c_res, "intent", str(c_res))
                except Exception:
                    pass
            q.put({
                "event": "intent_classified",
                "data": {
                    "session_id": req.session_id,
                    "task_id": req.task_id or f"task_{uuid.uuid4().hex[:8]}",
                    "intent": intent,
                    "message": req.message,
                }
            })

            # Step streaming callback
            def on_step(step_res: Dict[str, Any]):
                tool_id = (step_res.get("tool_executed") or {}).get("id") or step_res.get("tool_id", "tool")
                node_id = step_res.get("node_id") or "node_0"
                plan_id = step_res.get("plan_id") or "plan_0"
                q.put({
                    "event": "step_started",
                    "data": {
                        "session_id": req.session_id,
                        "plan_id": plan_id,
                        "node_id": node_id,
                        "tool_id": tool_id,
                    }
                })
                raw_out = (step_res.get("execution") or {}).get("stdout") or step_res.get("reply", "")
                if raw_out:
                    q.put({
                        "event": "step_output_chunk",
                        "data": {
                            "session_id": req.session_id,
                            "plan_id": plan_id,
                            "node_id": node_id,
                            "chunk": raw_out[:1000],
                        }
                    })
                q.put({
                    "event": "step_completed",
                    "data": {
                        "session_id": req.session_id,
                        "plan_id": plan_id,
                        "node_id": node_id,
                        "tool_id": tool_id,
                        "exit_code": (step_res.get("execution") or {}).get("exit_code", 0),
                        "duration_ms": step_res.get("duration_ms", 0),
                        "status": step_res.get("status", "success"),
                    }
                })

            autonomous_flag = req.autonomous
            if req.mode in ("autonomous_task", "autonomous"):
                autonomous_flag = True
            elif req.mode in ("single_step", "manual"):
                autonomous_flag = False

            result = agent.execute_task(
                session_id=req.session_id,
                message=req.message,
                task_id=req.task_id,
                parent_event=req.parent_event,
                explicit_tool=req.explicit_tool,
                explicit_args=req.explicit_args,
                model_id=req.model_id,
                autonomous=autonomous_flag,
                mode=req.mode,
                step_callback=on_step,
            )

            # Plan created event
            if result.get("plan") or result.get("plan_id"):
                q.put({
                    "event": "plan_created",
                    "data": {
                        "session_id": req.session_id,
                        "plan": result.get("plan"),
                        "plan_id": result.get("plan_id"),
                        "nodes": (result.get("plan") or {}).get("nodes", []),
                    }
                })

            # Agent message chunk
            reply = result.get("reply", "")
            if reply:
                q.put({
                    "event": "agent_message_chunk",
                    "data": {
                        "session_id": req.session_id,
                        "chunk": reply,
                        "complete": True,
                    }
                })

            # Next step recommendations
            recs = result.get("next_step_recommendations") or (result.get("synthesis") or {}).get("next_step_recommendations", [])
            q.put({
                "event": "next_step_recommendations",
                "data": {
                    "session_id": req.session_id,
                    "recommendations": recs,
                }
            })
            q.put(None)
        except Exception as e:
            logger.error(f"[chat_stream_endpoint] Worker error: {e}")
            q.put({"event": "error", "data": {"error": str(e)}})
            q.put(None)

    th = threading.Thread(target=run_worker, daemon=True)
    th.start()

    def sse_event_stream():
        while True:
            item = q.get()
            if item is None:
                break
            evt = item.get("event", "message")
            data_str = json.dumps(item.get("data", {}))
            yield f"event: {evt}\ndata: {data_str}\n\n"

    return StreamingResponse(sse_event_stream(), media_type="text/event-stream")


@app.post("/run")
def run_loop(req: RunRequest):
    """Execution endpoint aliased to /chat for backward compatibility."""
    try:
        autonomous_flag = req.autonomous
        if req.mode in ("autonomous_task", "autonomous"):
            autonomous_flag = True
        elif req.mode in ("single_step", "manual"):
            autonomous_flag = False

        result = agent.execute_task(
            session_id=req.session_id,
            message=req.message,
            task_id=req.task_id,
            parent_event=req.parent_event,
            explicit_tool=req.explicit_tool,
            explicit_args=req.explicit_args,
            model_id=req.model_id,
            autonomous=autonomous_flag,
            mode=req.mode,
        )
        return result
    except Exception as e:
        logger.exception(f"Run loop error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gateway/execute")
def gateway_execute_endpoint(req: GatewayExecuteRequest):
    """Direct authoritative tool execution through centralized ExecutionGateway."""
    exec_res = execution_gateway.execute(
        tool_id=req.tool_id,
        arguments=req.arguments,
        session_id=req.session_id,
        task_id=req.task_id,
        target=req.target,
        operator_token=req.operator_token,
        workflow_token=req.workflow_token,
        tool_version=req.tool_version or "1.0.0",
        execution_plane=req.execution_plane or "auto",
        timeout_ms=req.timeout_ms,
        db_path=agent.db_path,
    )
    if not exec_res.authorized:
        status_code = 403 if ("SCOPE" in (exec_res.rejection_reason or "") or "WORKFLOW" in (exec_res.rejection_reason or "")) else 400
        raise HTTPException(
            status_code=status_code,
            detail=exec_res.rejection_reason or exec_res.stderr or "Execution rejected by ExecutionGateway.",
        )
    return {
        "tool_id": exec_res.tool_id,
        "tool_version": exec_res.tool_version,
        "task_id": exec_res.task_id,
        "session_id": exec_res.session_id,
        "target": exec_res.target,
        "authorized": exec_res.authorized,
        "status": exec_res.status,
        "exit_code": exec_res.exit_code,
        "stdout": exec_res.stdout,
        "stderr": exec_res.stderr,
        "duration_ms": exec_res.duration_ms,
        "observation": exec_res.observation,
        "artifacts": exec_res.artifacts,
        "event_id": exec_res.event_id,
    }


@app.post("/kill")
def kill_process(req: KillRequest):
    """Kill switch endpoint: SIGKILL running process by task_id."""
    res = supervisor.kill_by_task_id(req.task_id)
    return res


@app.post("/kill/{task_id}")
def kill_process_by_path(task_id: str):
    """Kill switch endpoint by path parameter."""
    res = supervisor.kill_by_task_id(task_id)
    return res


@app.get("/processes")
def list_active_processes():
    return {"active_processes": supervisor.list_active()}


@app.post("/process/pause/{task_id}")
def pause_process(task_id: str):
    """Pauses task execution via SIGSTOP / suspend."""
    vm_res = vm_manager.pause_task_in_vm(task_id)
    if vm_res.get("success"):
        return vm_res
    return supervisor.pause_by_task_id(task_id)


@app.post("/process/resume/{task_id}")
def resume_process(task_id: str):
    """Resumes task execution via SIGCONT / resume."""
    vm_res = vm_manager.resume_task_in_vm(task_id)
    if vm_res.get("success"):
        return vm_res
    return supervisor.resume_by_task_id(task_id)


@app.post("/process/stop/{task_id}")
def stop_process(task_id: str):
    """Stops/kills task execution immediately."""
    vm_res = vm_manager.stop_task_in_vm(task_id)
    host_res = supervisor.stop_by_task_id(task_id)
    return {"task_id": task_id, "vm": vm_res, "host": host_res}


@app.post("/process/retry/{task_id}")
def retry_process(task_id: str):
    """Restarts task execution cleanly with same parameters."""
    vm_res = vm_manager.retry_task_in_vm(task_id)
    if vm_res.get("success"):
        return vm_res
    return supervisor.retry_by_task_id(task_id)


@app.get("/process/tree")
@app.get("/process/tree/{task_id}")
def get_process_tree(task_id: Optional[str] = None):
    """Returns hierarchical process tree (parent/child/background) for task."""
    vm_tree = vm_manager.get_process_tree(task_id)
    if vm_tree.get("nodes"):
        return vm_tree
    if task_id:
        return supervisor.get_process_tree(task_id)
    return vm_tree


@app.get("/process/poll/{task_id}")
def poll_process(task_id: str, since: int = 0):
    """Polls streaming output chunks and current process tree for task."""
    vm_poll = vm_manager.poll_task(task_id, since=since)
    if not vm_poll.get("error"):
        return vm_poll
    rec = supervisor._active.get(task_id) or supervisor._history.get(task_id)
    if rec:
        chunks = rec.get_chunks_since(since)
        tree = supervisor.get_process_tree(task_id)
        return {
            "task_id": task_id,
            "status": rec.status,
            "chunks": chunks,
            "completed": rec.done_event.is_set(),
            "tree": tree.get("nodes", []),
        }
    return {"task_id": task_id, "chunks": [], "completed": True, "status": "not_found"}


@app.get("/events")
def list_events(session_id: Optional[str] = None, limit: int = 50):
    if session_id:
        return {"events": get_events_by_session(session_id)}
    return {"events": get_recent_events(limit)}


@app.get("/tools")
def list_tools():
    return {"tools": [t.to_dict() for t in agent.registry.list_tools()]}


# --- Kali Linux Sandbox & Snapshot Endpoints ---

@app.get("/vm/status")
def vm_status():
    """Returns status of Kali VM and in-guest worker agent."""
    return vm_manager.get_status()


@app.post("/vm/start")
def vm_start(headless: bool = True, wait_seconds: int = 40):
    """Explicitly triggers auto-starting the Kali VM or worker agent."""
    online = vm_manager.ensure_worker_online(timeout_sec=wait_seconds, auto_start=True)
    status = vm_manager.get_status()
    return {
        "status": "success" if online else "timeout",
        "worker_online": online,
        "details": status,
    }


@app.get("/vm/snapshots")
def vm_snapshots():
    """Lists all VirtualBox snapshots for the Kali VM."""
    return {"snapshots": vm_manager.list_snapshots()}


@app.post("/vm/snapshot")
def vm_snapshot(req: VMSnapshotRequest):
    """Creates a snapshot of the current Kali VM."""
    return vm_manager.take_snapshot(name=req.name, description=req.description or "")


@app.post("/vm/rollback")
def vm_rollback(req: VMRollbackRequest):
    """Manually rolls back the Kali VM to a snapshot (default: kairo_worker_ready)."""
    return vm_manager.rollback_snapshot(snapshot_name=req.name or "kairo_worker_ready")


@app.post("/vm/execute")
def vm_execute(
    req: VMExecuteRequest,
    authorization: Optional[str] = Header(None),
):
    """Executes a typed ToolSpec command inside the Kali VM via centralized ExecutionGateway."""
    tid = req.task_id or f"task_vm_{int(time.time()*1000)}"

    # Resolve operator token
    token = req.operator_token
    if not token and authorization:
        parts = authorization.split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization

    wf_token = req.workflow_token or token

    clean_args = {
        "command": req.command,
        "args": req.args or [],
        "cwd": req.cwd or "/home/kali",
        "snapshot_before": bool(req.snapshot_before),
        "rollback_after": bool(req.rollback_after),
        "rollback_on_failure": bool(req.rollback_on_failure),
        "resource_limits": req.resource_limits,
        "artifact_dir": req.artifact_dir,
    }
    if wf_token:
        clean_args["workflow_token"] = wf_token

    exec_res = execution_gateway.execute(
        tool_id="kali.exec.v1",
        arguments=clean_args,
        session_id=req.session_id or "vm_session",
        task_id=tid,
        target=req.target or "127.0.0.1",
        operator_token=token,
        workflow_token=wf_token,
        timeout_ms=int(req.timeout_ms or 30000),
        db_path=agent.db_path,
        execution_target="vm",
    )

    if not exec_res.authorized:
        status_code = 403 if ("SCOPE" in (exec_res.rejection_reason or "") or "WORKFLOW" in (exec_res.rejection_reason or "")) else 400
        raise HTTPException(
            status_code=status_code,
            detail=exec_res.rejection_reason or exec_res.stderr or "VM execution rejected by ExecutionGateway.",
        )

    response = {
        "task_id": tid,
        "tool_id": "kali.exec.v1",
        "authorized": exec_res.authorized,
        "status": exec_res.status,
        "exit_code": exec_res.exit_code,
        "stdout": exec_res.stdout,
        "stderr": exec_res.stderr,
        "duration_ms": exec_res.duration_ms,
        "artifacts": exec_res.artifacts,
        "observation": exec_res.observation,
        "event_id": exec_res.event_id,
    }
    if isinstance(exec_res.observation, dict):
        for k, v in exec_res.observation.items():
            if k not in response:
                response[k] = v
    return response


@app.get("/artifacts/{task_id}")
def get_task_artifacts(task_id: str):
    """Returns all captured output files and their SHA-256 hashes for a given task."""
    arts = get_artifacts_by_task(task_id, agent.db_path)
    return {"task_id": task_id, "count": len(arts), "artifacts": arts}


@app.post("/artifacts/verify")
def verify_artifact(req: ArtifactVerifyRequest):
    """Verifies SHA-256 cryptographic integrity of a captured output artifact."""
    if req.artifact_id:
        art = get_artifact_by_id(req.artifact_id, agent.db_path)
        if not art:
            raise HTTPException(status_code=404, detail=f"Artifact ID {req.artifact_id} not found")
        fpath = art["filepath"]
        expected_sha = art["sha256"]
    elif req.filepath and req.expected_sha256:
        fpath = req.filepath
        expected_sha = req.expected_sha256
    else:
        raise HTTPException(status_code=400, detail="Must provide either artifact_id or (filepath and expected_sha256)")

    res = verify_artifact_file(fpath, expected_sha)
    return res


@app.post("/vm/kill/{task_id}")
def vm_kill(task_id: str):
    """Sends SIGKILL to an active task inside the Kali VM."""
    return vm_manager.kill_task_in_vm(task_id)


# Planner Endpoints: DAG Decomposition, Graph Query, and Node Status Updates
@app.post("/planner/decompose")
def planner_decompose(req: PlanDecomposeRequest):
    """Decomposes a natural language goal into a validated DAG plan stored in the event store."""
    if not req.goal or not req.goal.strip():
        raise HTTPException(status_code=400, detail="Missing required 'goal'")
    plan = planner.decompose(goal=req.goal, session_id=req.session_id, prefer_llm=req.prefer_llm, db_path=agent.db_path)
    return plan


@app.get("/planner/plans")
def list_planner_plans(limit: int = 20):
    """Lists recent task graph plans."""
    return {"plans": list_plans(limit=limit, db_path=agent.db_path)}


@app.get("/planner/plans/{plan_id}")
def get_planner_plan(plan_id: str):
    """Retrieves a specific task graph DAG with its nodes and execution statuses."""
    plan = get_plan(plan_id, db_path=agent.db_path)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return plan


@app.post("/planner/plans/{plan_id}/nodes/{node_id}/status")
def update_planner_node_status(plan_id: str, node_id: str, req: PlanNodeStatusRequest):
    """Updates status for a specific DAG node (queued, running, success, warning, failed)."""
    valid_statuses = ("queued", "running", "success", "warning", "failed", "skipped", "blocked")
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")
    ok = update_node_status(
        plan_id=plan_id,
        node_id=node_id,
        status=req.status,
        result=req.result,
        assigned_tool=req.assigned_tool,
        db_path=agent.db_path,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' in plan '{plan_id}' not found")
    return get_plan(plan_id, db_path=agent.db_path)


@app.get("/planner/plans/{plan_id}/ready")
def get_planner_ready_nodes(plan_id: str):
    """Returns all queued nodes whose dependencies are satisfied and ready for parallel execution."""
    ready = get_ready_nodes(plan_id, db_path=agent.db_path)
    return {"plan_id": plan_id, "ready_count": len(ready), "ready_nodes": ready}


@app.post("/planner/plans/{plan_id}/run")
@app.post("/planner/plans/{plan_id}/execute")
def run_planner_plan(plan_id: str, req: Optional[PlanExecuteRequest] = None):
    """
    Autonomously executes a multi-step task graph from beginning to end using DAGController.
    MANDATORY GATE: Requires an unexpired, cryptographically signed Scope Contract before any task graph can execute.
    """
    from orchestrator.dag_controller import dag_controller
    req = req or PlanExecuteRequest()
    sess_id = req.session_id or f"sess_dag_{uuid.uuid4().hex[:6]}"

    contract = get_active_scope_contract(agent.db_path)
    if not contract:
        contract = seed_default_scope_contract(agent.db_path)

    # 1. Signature Integrity Verification
    if not contract.get("signature_valid", False):
        rejection_event = Event.create(
            session_id="plan_exec",
            task_id=f"plan_exec_{plan_id}",
            actor="gateway:scope_guard",
            exit_code=403,
            result_summary="SCOPE_REJECTION: Task graph execution blocked. Active Scope Contract signature is invalid or tampered.",
            confidence=0.0,
            network_context={"plan_id": plan_id, "authorized": False, "reason": "INVALID_SIGNATURE"},
        )
        insert_event(rejection_event, agent.db_path)
        raise HTTPException(
            status_code=403,
            detail="Scope Contract signature is invalid or contract has been tampered with. Task graph execution blocked.",
        )

    # 2. Expiration Verification
    if contract.get("is_expired", False) or contract.get("seconds_remaining", 0) <= 0:
        rejection_event = Event.create(
            session_id="plan_exec",
            task_id=f"plan_exec_{plan_id}",
            actor="gateway:scope_guard",
            exit_code=403,
            result_summary=f"SCOPE_REJECTION: Task graph execution blocked. Active Scope Contract expired at {contract.get('expires_at')}.",
            confidence=0.0,
            network_context={"plan_id": plan_id, "authorized": False, "reason": "EXPIRED_CONTRACT"},
        )
        insert_event(rejection_event, agent.db_path)
        raise HTTPException(
            status_code=403,
            detail=f"Active Scope Contract expired at {contract.get('expires_at')}. Renew contract before executing task graph.",
        )

    try:
        res = dag_controller.execute_plan(
            plan_id=plan_id,
            session_id=sess_id,
            target=req.target,
            goal=req.goal,
            max_steps=req.max_steps or 50,
            stop_on_critical_failure=req.stop_on_critical_failure if req.stop_on_critical_failure is not None else True,
            db_path=agent.db_path,
            mode=req.mode or "autonomous",
        )
        res_dict = res.to_dict()
        res_dict.setdefault("scope_contract_id", contract.get("contract_id"))
        res_dict.setdefault("authorized_by", contract.get("authorized_by"))
        res_dict.setdefault("executed_count", res.completed_count + res.failed_count)
        res_dict.setdefault("executed_nodes", [n.to_dict() for n in res.nodes_executed])
        res_dict.setdefault("updated_plan", get_plan(plan_id, db_path=agent.db_path))
        return res_dict
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Autonomous plan execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/planner/run")
def run_planner_goal(req: PlanDecomposeRequest):
    """Decomposes a goal into a DAG plan and executes it autonomously from start to finish."""
    from orchestrator.dag_controller import dag_controller
    if not req.goal or not req.goal.strip():
        raise HTTPException(status_code=400, detail="Missing required 'goal'")
    plan = planner.decompose(goal=req.goal, session_id=req.session_id, prefer_llm=req.prefer_llm, db_path=agent.db_path)
    plan_id = plan["plan_id"]
    sess_id = req.session_id or plan.get("session_id") or f"sess_dag_{uuid.uuid4().hex[:6]}"
    res = dag_controller.execute_plan(
        plan_id=plan_id,
        session_id=sess_id,
        goal=req.goal,
        db_path=agent.db_path,
    )
    return res.to_dict()


# Hybrid Tool Selection & Tool Memory Endpoints
@app.post("/tools/select")
def select_tool_endpoint(req: ToolSelectRequest):
    """Evaluates candidate tools using the hybrid scoring function and returns top 3 with full breakdown."""
    goal = req.goal or req.intent or ""
    if not goal.strip():
        raise HTTPException(status_code=400, detail="Missing required 'goal' or 'intent'")
    cap = req.required_capability or req.capability or req.intended_capability
    res = tool_selector.select(
        goal=goal,
        required_capability=cap,
        session_id=req.session_id or "default_session",
        top_k=req.top_k or 3,
        environment=req.environment,
        budget=req.budget,
        plan_step=req.plan_step,
        intended_capability=req.intended_capability,
        intended_category=req.intended_category,
        planner_output=req.planner_output,
    )
    return res.to_dict()


@app.get("/tools/memory")
def get_tools_memory_endpoint():
    """Returns historical execution and reliability memory for all registered tools."""
    tools = list_tool_memories(agent.db_path)
    return {"tools": tools, "count": len(tools)}


@app.get("/tools/memory/{tool_id}")
def get_single_tool_memory_endpoint(tool_id: str):
    """Returns reliability and performance memory for a single tool."""
    return get_tool_memory(tool_id, agent.db_path)


# ==============================================================================
# SCOPE CONTRACT ENDPOINTS & TASK GRAPH EXECUTION GATING
# ==============================================================================

@app.get("/scope/active")
def get_active_scope_endpoint():
    """Returns the currently active Scope Contract or seeds default if none exists."""
    contract = get_active_scope_contract(agent.db_path)
    if not contract or contract.get("is_expired"):
        contract = seed_default_scope_contract(agent.db_path)
    return contract


@app.post("/scope/contract")
def create_scope_contract_endpoint(
    req: ScopeContractCreateRequest,
    authorization: Optional[str] = Header(None),
):
    """Creates, cryptographically signs, and activates a new Scope Contract under operator authorization."""
    if not req.targets:
        raise HTTPException(status_code=400, detail="Scope Contract must specify at least one target or CIDR subnet")

    token = req.operator_token
    if not token and authorization:
        parts = authorization.split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization

    success, contract, message = execution_gateway.authorize_scope_modification(
        targets=req.targets,
        operator_token=token,
        network_scope=req.network_scope,
        time_window=req.time_window,
        allowed_tool_tiers=req.allowed_tool_tiers,
        metadata=req.metadata,
        db_path=agent.db_path,
    )
    if not success:
        status_code = 401 if "OPERATOR_AUTH_REQUIRED" in message else (403 if "INSUFFICIENT_PRIVILEGE" in message else 400)
        raise HTTPException(status_code=status_code, detail=message)
    return contract


@app.get("/scope/contracts")
def list_scope_contracts_endpoint(limit: int = 10):
    """Returns historical Scope Contracts and their signature status."""
    return {"contracts": list_scope_contracts(limit=limit, db_path=agent.db_path)}


@app.post("/scope/validate")
def validate_scope_endpoint(req: ScopeValidateRequest):
    """Validates target and tool tier against active Scope Contract."""
    res = validate_scope_request(
        target=req.target,
        tool_id=req.tool_id,
        tool_tier=req.tool_tier,
        db_path=agent.db_path,
    )
    return res



@app.post("/planner/plans/{plan_id}/nodes/{node_id}/execute")
def execute_single_node_endpoint(plan_id: str, node_id: str, req: NodeExecuteRequest = NodeExecuteRequest()):
    """
    Executes a single DAG node using dag_controller (single source of truth for execution):
    Evidence Evaluation -> Tool Selection -> Scope Verification -> Execution -> Telemetry Recording.
    """
    from orchestrator.dag_controller import dag_controller, EvidenceContext
    contract = get_active_scope_contract(agent.db_path)
    if not contract:
        contract = seed_default_scope_contract(agent.db_path)

    plan = get_plan(plan_id, db_path=agent.db_path)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")

    target_node = None
    for n in plan.get("nodes", []):
        if n["node_id"] == node_id:
            target_node = n
            break

    if not target_node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in plan '{plan_id}'")

    sess_id = f"sess_node_{uuid.uuid4().hex[:6]}"
    context = EvidenceContext(
        target=plan.get("target") or "127.0.0.1",
        session_id=sess_id,
        plan_id=plan_id,
    )
    exec_record = dag_controller.execute_node(
        plan_id=plan_id,
        session_id=sess_id,
        node=target_node,
        context=context,
        db_path=agent.db_path,
    )
    return {
        "plan_id": plan_id,
        "node_id": node_id,
        "execution_result": exec_record.to_dict(),
        "updated_plan": get_plan(plan_id, db_path=agent.db_path),
    }


# ==============================================================================
# OBSERVER, CRITIC, AND RECOVERY AGENT DIRECT ENDPOINTS
# ==============================================================================

@app.post("/observer/observe")
def observer_observe_endpoint(req: ObserverRequest):
    """Translates raw command execution stdout/stderr into structured observation facts."""
    obs = observer.observe(
        tool_id=req.tool_id,
        stdout=req.stdout,
        stderr=req.stderr or "",
        exit_code=req.exit_code or 0,
        meta=req.meta or {},
        duration_ms=req.duration_ms or 0.0,
    )
    return obs.to_dict()


@app.post("/critic/evaluate")
def critic_evaluate_endpoint(req: CriticRequest):
    """Evaluates whether an observation moved the task graph toward the goal or flags no-progress."""
    res = critic.evaluate(
        node=req.node,
        plan_goal=req.plan_goal,
        observation=req.observation,
        previous_observations=req.previous_observations,
        attempt_number=req.attempt_number or 1,
    )
    return res.to_dict()


@app.post("/recovery/recover")
def recovery_recover_endpoint(req: RecoveryRequest):
    """Formulates a recovery plan per the blueprint's Reliability table with 3-attempt capping."""
    res = recovery_agent.formulate_recovery(
        plan_id=req.plan_id,
        node=req.node,
        current_tool=req.current_tool,
        current_args=req.current_args,
        stdout=req.stdout,
        stderr=req.stderr or "",
        exit_code=req.exit_code,
        timed_out=req.timed_out or False,
        parser_mismatch=req.parser_mismatch or False,
        critic_status=req.critic_status or "",
        critique_msg=req.critique_msg or "",
        session_id=req.session_id or "recovery_session",
    )
    return res.to_dict()


# ==============================================================================
# REPORTER & FAILURE-AWARE AUDIT SYNTHESIS ENDPOINTS
# ==============================================================================

@app.get("/planner/plans/{plan_id}/report")
def get_plan_report_endpoint(plan_id: str, format: str = "json"):
    """
    Synthesizes and returns the final security audit report for a plan.
    Includes full attempt history narrative for any node where Task 2.4 recovery fired.
    """
    try:
        report_data = reporter.generate_plan_report(plan_id=plan_id, include_markdown=True)
        if format.lower() == "markdown":
            return {"plan_id": plan_id, "markdown": report_data.get("markdown", "")}
        return report_data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")


@app.post("/planner/plans/{plan_id}/report")
def save_plan_report_artifact_endpoint(plan_id: str):
    """
    Generates the final report and commits it as SHA-256 verified JSON/Markdown artifacts.
    """
    try:
        report_data = reporter.generate_plan_report(plan_id=plan_id, include_markdown=True)
        artifact_info = reporter.save_report_artifact(plan_id=plan_id, report_data=report_data)
        return {
            "status": "saved",
            "plan_id": plan_id,
            "report_id": report_data["report_id"],
            "artifacts": artifact_info,
            "metrics": report_data["metrics"],
            "markdown_preview": report_data.get("markdown", "")[:400] + "...",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save report: {e}")


# ==============================================================================
# EVIDENCE STORE & AUDIT REPORT GENERATOR ENDPOINTS
# ==============================================================================

class CreateFindingRequest(BaseModel):
    title: str
    affected_asset: str
    evidence_references: Optional[List[str]] = None
    confidence_score: float = 1.0
    recovery_path: Optional[Any] = None
    severity: str = "INFO"
    description: Optional[str] = ""
    remediation: Optional[str] = ""
    discovering_tool: Optional[str] = None
    discovering_node_id: Optional[str] = None
    session_id: Optional[str] = None
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    tags: Optional[List[str]] = None


class GenerateReportRequest(BaseModel):
    finding_ids: Optional[List[str]] = None
    plan_id: Optional[str] = None
    session_id: Optional[str] = None
    title: Optional[str] = None
    format: str = "both"
    include_workflow: bool = True


@app.get("/evidence/findings")
def list_findings_endpoint(
    session_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    asset: Optional[str] = None,
    severity: Optional[str] = None,
):
    """Lists security finding cards from the Evidence Store with metadata, confidence, and recovery paths."""
    findings = evidence_store.list_findings(
        session_id=session_id,
        plan_id=plan_id,
        affected_asset=asset,
        severity=severity,
    )
    return {
        "count": len(findings),
        "findings": [f.to_dict() for f in findings],
    }


@app.post("/evidence/findings")
def create_finding_endpoint(req: CreateFindingRequest):
    """Registers a structured finding card into the Evidence Store."""
    finding = Finding(
        title=req.title,
        affected_asset=req.affected_asset,
        evidence_references=req.evidence_references or [],
        confidence_score=req.confidence_score,
        recovery_path=req.recovery_path,
        severity=req.severity,
        description=req.description or "",
        remediation=req.remediation or "",
        discovering_tool=req.discovering_tool,
        discovering_node_id=req.discovering_node_id,
        session_id=req.session_id,
        plan_id=req.plan_id,
        task_id=req.task_id,
        tags=req.tags or [],
    )
    saved = evidence_store.store_finding(finding)
    return saved.to_dict()


@app.get("/evidence/findings/{finding_id}")
def get_finding_endpoint(finding_id: str):
    """Retrieves a finding card along with all resolved evidence objects and hashes."""
    finding = evidence_store.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")
    f_dict = finding.to_dict()
    f_dict["resolved_evidence"] = evidence_store.resolve_evidence_references(finding.evidence_references)
    return f_dict


@app.post("/evidence/ingest-plan/{plan_id}")
def ingest_plan_into_evidence_store(plan_id: str, target_asset: Optional[str] = None):
    """
    Auto-ingests all executed nodes and facts from a plan DAG into the Evidence Store,
    generating typed evidence instances and linking recovery paths.
    """
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")

    nodes = plan.get("nodes", [])
    total_findings: List[Finding] = []

    for n in nodes:
        raw_res = n.get("result")
        res_obj = {}
        if isinstance(raw_res, dict):
            res_obj = raw_res
        elif isinstance(raw_res, str):
            try:
                res_obj = json.loads(raw_res)
            except Exception:
                res_obj = {}

        created = evidence_store.auto_ingest_from_node_result(
            plan_id=plan_id,
            node_id=n.get("node_id"),
            tool=n.get("assigned_tool") or "unknown_tool",
            result_data=res_obj,
            session_id=plan.get("session_id"),
            target_asset=target_asset,
        )
        total_findings.extend(created)

    return {
        "status": "ingested",
        "plan_id": plan_id,
        "nodes_processed": len(nodes),
        "findings_created": len(total_findings),
        "findings": [f.to_dict() for f in total_findings],
    }


@app.post("/evidence/reports/generate")
def generate_audit_report_endpoint(req: GenerateReportRequest):
    """
    Assembles selected findings into a publication-ready Markdown/HTML audit report
    with embedded evidence references and an executable reproducible workflow replay script.
    """
    try:
        report_res = report_generator.assemble_report(
            finding_ids=req.finding_ids,
            plan_id=req.plan_id,
            session_id=req.session_id,
            title=req.title,
            include_workflow=req.include_workflow,
        )
        return report_res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to assemble report: {e}")


@app.get("/evidence/artifacts")
def list_evidence_artifacts(task_id: Optional[str] = None, limit: int = 50):
    """Lists captured evidence artifacts with SHA-256 provenance."""
    conn = get_connection()
    with conn:
        cursor = conn.cursor()
        if task_id:
            cursor.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM artifacts ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Enrich with evidence class from metadata if present
    for r in rows:
        if r.get("metadata"):
            try:
                m = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]
                r["evidence_class"] = m.get("evidence_class") or "file"
                r["title"] = m.get("title") or r.get("filename")
            except Exception:
                r["evidence_class"] = "file"
        else:
            r["evidence_class"] = "file"

    return {"count": len(rows), "artifacts": rows}


@app.on_event("startup")
async def startup_vnc_streamer():
    """Starts the RFB 3.8 noVNC streaming server for the Kali worker desktop."""
    try:
        await vnc_server.start()
    except Exception as e:
        import logging
        logging.getLogger("orchestrator.server").warning(f"Could not start VNC streamer on startup: {e}")


@app.on_event("shutdown")
async def shutdown_vnc_streamer():
    """Stops the VNC streamer on orchestrator shutdown."""
    try:
        await vnc_server.stop()
    except Exception:
        pass


@app.get("/screen/status")
def get_screen_status():
    """Returns the operational status and metrics of the Kali worker noVNC stream."""
    return {
        "status": "running" if vnc_server._running else "stopped",
        "ws_port": vnc_server.port,
        "width": vnc_server.desktop.width,
        "height": vnc_server.desktop.height,
        "clients": len(vnc_server.clients),
        "plane": vnc_server.desktop.active_plane_name,
        "upstream_vnc_detected": vnc_server.check_upstream_vnc(),
        "protocol": "RFB 003.008",
    }


@app.get("/screen/snapshot.png")
def get_screen_snapshot():
    """Returns a real-time PNG snapshot of the Kali worker virtual desktop framebuffer."""
    png_bytes = vnc_server.desktop.get_png_bytes()
    return Response(content=png_bytes, media_type="image/png")


# --- Tier 3 GUI Tool Adapter Endpoints ---

_active_gui_instances: Dict[str, BaseGuiAdapter] = {}


def _get_or_create_gui_adapter(tool_id: str) -> BaseGuiAdapter:
    """Returns active instance or instantiates from registry."""
    if tool_id not in _active_gui_instances:
        instance = adapter_registry.get_instance(tool_id)
        if not instance or not isinstance(instance, BaseGuiAdapter):
            raise HTTPException(status_code=404, detail=f"GUI tool adapter not found: {tool_id}")
        _active_gui_instances[tool_id] = instance
    return _active_gui_instances[tool_id]


@app.get("/gui/adapters")
def list_gui_adapters():
    """Lists available GUI tool adapters and their supported scripted workflows."""
    adapters_info = []
    gui_tool_ids = ["burpsuite.gui.v1", "wireshark.gui.v1", "zap.gui.v1"]
    for tid in gui_tool_ids:
        inst = adapter_registry.get_instance(tid)
        if inst and isinstance(inst, BaseGuiAdapter):
            adapters_info.append({
                "tool_id": inst.tool_id,
                "tool_version": inst.tool_version,
                "app_name": inst.app_name,
                "is_running": inst.is_running(),
                "workflows": inst.list_workflows(),
            })
    return {"count": len(adapters_info), "adapters": adapters_info}


@app.post("/gui/execute")
def execute_gui_tool(req: GuiExecuteRequest):
    """
    Executes an action or bounded scripted workflow on a GUI Tool Adapter.
    Enforces Scope Contract target authorization.
    """
    params = req.params or {}
    target = params.get("target") or params.get("host") or params.get("target_url")
    
    # 1. Scope Contract Authorization Check
    scope_val = validate_scope_request(target=target, tool_id=req.tool_id)
    if not scope_val.get("authorized", True):
        raise HTTPException(
            status_code=403,
            detail=f"Scope violation: Tool {req.tool_id} is not authorized for target {target} under active contract.",
        )

    # 2. Get or create adapter instance
    adapter = _get_or_create_gui_adapter(req.tool_id)

    # 3. Build input envelope
    task_id = req.task_id or f"task_{req.tool_id.split('.')[0]}_{int(time.time()*1000)%10000}"
    inputs = {
        "action": req.action,
        "workflow": req.workflow,
        "params": params,
        "x": req.x,
        "y": req.y,
        "control_id": req.control_id,
        "text": req.text,
        "caption": req.caption,
    }

    # 4. Execute action
    observation = adapter.execute(inputs=inputs, task_id=task_id, target="local")

    is_simulated = bool(
        getattr(observation, "is_simulated", False)
        or (isinstance(observation.observation, dict) and observation.observation.get("is_simulated", False))
        or (isinstance(observation.observation, dict) and observation.observation.get("execution_plane") == ExecutionPlaneType.SIMULATED_MOCK.value)
    )
    sim_notice = getattr(observation, "simulation_notice", None) or (
        observation.observation.get("simulation_notice") if isinstance(observation.observation, dict) else None
    )
    if is_simulated and not sim_notice:
        sim_notice = SIMULATION_NOTICE_TEXT

    result_summary = (
        f"{SIMULATION_NOTICE_TEXT} GUI action {req.action} ({req.workflow or ''}): {observation.status}"
        if is_simulated
        else f"GUI action {req.action} ({req.workflow or ''}): {observation.status}"
    )

    # 5. Record Event in events database
    event = Event.create(
        session_id=req.session_id or "gui_session",
        task_id=task_id,
        actor="agent",
        tool_id=req.tool_id,
        tool_version=adapter.tool_version,
        requested_args=inputs,
        normalized_args=inputs,
        process_id=adapter.pid,
        exit_code=observation.exit_code,
        artifact_refs=observation.artifacts,
        screenshots=[s["filepath"] for s in adapter.screenshots if s.get("filepath")],
        network_context={
            "tool_id": req.tool_id,
            "action": req.action,
            "workflow": req.workflow,
            "execution_plane": ExecutionPlaneType.SIMULATED_MOCK.value if is_simulated else "gui",
            "is_simulated": is_simulated,
            "simulation_notice": sim_notice,
        },
        result_summary=result_summary,
    )
    insert_event(event)

    return observation.to_dict()


@app.get("/gui/state/{tool_id}")
def get_gui_tool_state(tool_id: str):
    """Returns current extracted UI-state for a given GUI tool adapter."""
    adapter = _get_or_create_gui_adapter(tool_id)
    return adapter.extract_ui_state()


@app.post("/gui/screenshot/{tool_id}")
def capture_gui_tool_screenshot(tool_id: str, caption: Optional[str] = "Manual Visual Capture"):
    """Triggers an on-demand Visual Evidence screenshot for a GUI tool adapter."""
    adapter = _get_or_create_gui_adapter(tool_id)
    task_id = f"snap_{tool_id.split('.')[0]}_{int(time.time()*1000)%10000}"
    vis = adapter.capture_screenshot(task_id=task_id, caption=caption, workflow_step="manual_snapshot")
    return {
        "evidence_id": vis.evidence_id,
        "filepath": vis.filepath,
        "sha256": vis.sha256,
        "caption": vis.caption,
        "dimensions": vis.dimensions,
        "thumbnail_b64": vis.thumbnail_b64,
    }


@app.post("/gui/stop/{tool_id}")
def stop_gui_tool(tool_id: str):
    """Stops the active GUI tool session."""
    if tool_id in _active_gui_instances:
        adapter = _active_gui_instances[tool_id]
        res = adapter.stop()
        return res
    return {"status": "not_running", "tool_id": tool_id}





# ─────────────────────────────────────────────────────────────────────────────
# Security Testing Browser Endpoints (Playwright-driven / Activity Rail)
# ─────────────────────────────────────────────────────────────────────────────

from orchestrator.adapters.browser_adapter import browser_adapter, SecurityBrowserAdapter


class BrowserExecuteRequest(BaseModel):
    session_id: Optional[str] = "browser_session"
    task_id: Optional[str] = None
    action: str = "workflow"  # workflow, navigate, click, fill, extract_state, screenshot, history, stop
    workflow: Optional[str] = "xss_check"
    url: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    payload: Optional[str] = None
    caption: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


@app.get("/browser/state")
def get_browser_state():
    """Returns the current visible state of the security testing browser."""
    return browser_adapter.extract_visible_state()


@app.get("/browser/history")
def get_browser_history():
    """Returns the sequential action history rendered in the Activity Rail."""
    return {
        "count": len(browser_adapter.action_history),
        "history": browser_adapter.get_action_history(),
        "findings": browser_adapter.findings,
        "is_running": browser_adapter.is_running,
    }


@app.post("/browser/execute")
def execute_browser_action(req: BrowserExecuteRequest):
    """
    Executes an action or scripted workflow on the Security Testing Browser.
    Enforces Scope Contract authorization.
    """
    params = req.params or {}
    target = req.url or params.get("url") or params.get("target") or "http://target.local"

    # 1. Scope Contract Authorization Check
    scope_val = validate_scope_request(target=target, tool_id=browser_adapter.tool_id)
    if not scope_val.get("authorized", True):
        raise HTTPException(
            status_code=403,
            detail=f"Scope violation: Tool {browser_adapter.tool_id} is not authorized for target {target} under active contract.",
        )

    # 2. Build input envelope
    task_id = req.task_id or f"task_browser_{int(time.time()*1000)%10000}"
    inputs = {
        "action": req.action,
        "workflow": req.workflow,
        "url": req.url,
        "selector": req.selector,
        "value": req.value,
        "payload": req.payload,
        "caption": req.caption,
        "params": params,
    }

    # 3. Execute action
    observation = browser_adapter.execute(inputs=inputs, task_id=task_id, target="local")

    # 4. Record Event in SQLite database
    event = Event.create(
        session_id=req.session_id or "browser_session",
        task_id=task_id,
        actor="agent",
        tool_id=browser_adapter.tool_id,
        tool_version=browser_adapter.tool_version,
        requested_args=inputs,
        normalized_args=inputs,
        process_id=os.getpid(),
        exit_code=observation.exit_code,
        artifact_refs=observation.artifacts,
        screenshots=[s["filepath"] for s in browser_adapter.screenshots if s.get("filepath")],
        result_summary=f"Security Browser action {req.action} ({req.workflow or ''}): {observation.status}",
    )
    insert_event(event)

    return observation.to_dict()


@app.post("/browser/screenshot")
def capture_browser_screenshot(caption: Optional[str] = "Manual Visual Capture"):
    """Triggers an on-demand Visual Evidence screenshot for the security browser."""
    task_id = f"snap_browser_{int(time.time()*1000)%10000}"
    return browser_adapter.capture_screenshot(caption=caption, task_id=task_id)


@app.post("/browser/stop")
def stop_browser():
    """Stops the active security browser session."""
    return browser_adapter.stop()


# ==============================================================================
# SHARED PROJECTS & MULTI-USER COLLABORATION ENDPOINTS
# ==============================================================================

class ProjectCreateRequest(BaseModel):
    name: str
    owner_id: str = "alice_secops"
    description: Optional[str] = None
    active_workspace_id: Optional[str] = None
    active_session_id: Optional[str] = None
    initial_state: Optional[Dict[str, Any]] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    active_workspace_id: Optional[str] = None
    active_session_id: Optional[str] = None
    shared_state: Optional[Dict[str, Any]] = None


class ProjectStateUpdateRequest(BaseModel):
    state_updates: Dict[str, Any]
    user_id: Optional[str] = "collaborator"


class CollaboratorRequest(BaseModel):
    user_id: str
    role: str = "editor"
    client_type: Optional[str] = "browser-desktop"


class PresenceHeartbeatRequest(BaseModel):
    user_id: str
    client_type: str = "browser-desktop"
    role: str = "editor"
    active_view: Optional[str] = "dashboard"


_project_presence: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _prune_and_get_presence(project_id: str) -> List[Dict[str, Any]]:
    now_ts = time.time()
    active_map = _project_presence.setdefault(project_id, {})
    stale_users = [uid for uid, p in active_map.items() if now_ts - p.get("last_seen_ts", 0) > 60]
    for uid in stale_users:
        del active_map[uid]
    return list(active_map.values())


@app.get("/projects")
def get_all_projects(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """Lists all shared projects, auto-seeding the canonical shared workspace if empty."""
    seed_default_shared_project()
    projects = list_projects(status=status, limit=limit)
    # Augment each project with live online presence count
    for p in projects:
        p["online_count"] = len(_prune_and_get_presence(p["project_id"]))
    return {"projects": projects, "total": len(projects)}


@app.post("/projects")
def create_new_project(req: ProjectCreateRequest):
    """Creates a new multi-user shared project."""
    project = create_project(
        name=req.name,
        owner_id=req.owner_id,
        description=req.description,
        active_workspace_id=req.active_workspace_id,
        active_session_id=req.active_session_id,
        initial_state=req.initial_state,
    )
    return {"project": project, "status": "created"}


@app.get("/projects/{project_id}")
def get_project_by_id(project_id: str):
    """Retrieves project details including current online presence and synchronized shared state."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    project["active_presence"] = _prune_and_get_presence(project_id)
    return {"project": project}


@app.put("/projects/{project_id}")
def update_project_metadata(project_id: str, req: ProjectUpdateRequest):
    """Updates metadata, status, or workspace bindings for a project."""
    updated = update_project(
        project_id=project_id,
        name=req.name,
        description=req.description,
        status=req.status,
        active_workspace_id=req.active_workspace_id,
        active_session_id=req.active_session_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if req.shared_state:
        updated = update_project_shared_state(project_id, state_patch=req.shared_state) or updated
    return {"project": updated}


@app.put("/projects/{project_id}/state")
def sync_project_state(project_id: str, req: ProjectStateUpdateRequest):
    """Synchronizes shared state (scratchpad, target, notes) across all project collaborators."""
    updated = update_project_shared_state(
        project_id=project_id,
        state_patch=req.state_updates,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    # Record synchronisation event in SQLite Event Store
    try:
        sync_event = Event.create(
            session_id=updated.get("active_session_id") or "shared_sync",
            task_id=f"state_sync_{int(time.time()*1000)%10000}",
            actor=req.user_id or "collaborator",
            tool_id="system.project_state_sync",
            tool_version="1.0.0",
            requested_args=req.state_updates,
            normalized_args=req.state_updates,
            process_id=os.getpid(),
            exit_code=0,
            result_summary=f"Project {project_id} shared state updated by {req.user_id}: {list(req.state_updates.keys())}",
        )
        insert_event(sync_event)
    except Exception as e:
        print(f"[Warning] Failed to log state sync event: {e}")

    return {
        "project": updated,
        "updated_keys": list(req.state_updates.keys()),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/projects/{project_id}/collaborators")
def add_collaborator(project_id: str, req: CollaboratorRequest):
    """Adds a collaborator to a shared project."""
    updated = add_project_collaborator(
        project_id=project_id,
        user_id=req.user_id,
        role=req.role,
        client_type=req.client_type,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"project": updated, "added_user": req.user_id}


@app.delete("/projects/{project_id}/collaborators/{user_id}")
def remove_collaborator(project_id: str, user_id: str):
    """Removes a collaborator from a shared project (owner cannot be removed)."""
    updated = remove_project_collaborator(
        project_id=project_id,
        user_id=user_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"project": updated, "removed_user": user_id}


@app.get("/projects/{project_id}/presence")
def get_project_presence(project_id: str):
    """Returns active online collaborators for the project."""
    presence = _prune_and_get_presence(project_id)
    return {"project_id": project_id, "collaborators_online": presence, "count": len(presence)}


@app.post("/projects/{project_id}/presence")
def heartbeat_project_presence(project_id: str, req: PresenceHeartbeatRequest):
    """Heartbeat endpoint registering active collaborator presence in a project."""
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    active_map = _project_presence.setdefault(project_id, {})
    active_map[req.user_id] = {
        "user_id": req.user_id,
        "client_type": req.client_type,
        "role": req.role,
        "active_view": req.active_view,
        "last_seen_ts": now_ts,
        "last_seen": now_iso,
    }
    presence = _prune_and_get_presence(project_id)
    return {"project_id": project_id, "collaborators_online": presence, "count": len(presence)}


# ==============================================================================
# AUDIT EXPLORER: SEARCHABLE TIMELINE & ACCOUNTABILITY (Task 2.3)
# ==============================================================================

@app.get("/audit/timeline")
def get_audit_timeline(
    query: Optional[str] = None,
    actor: Optional[str] = None,
    tool_id: Optional[str] = None,
    status: Optional[str] = None,
    time_range: Optional[str] = None,
    scope_filter: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """
    Searchable audit timeline querying every agent and tool execution event
    correlated directly with the governing Scope Contract history (Task 2.3).
    Surfaces HMAC-SHA256 signature verification, tool tiers, and target boundaries.
    """
    return query_audit_timeline(
        query=query,
        actor=actor,
        tool_id=tool_id,
        status=status,
        time_range=time_range,
        scope_filter=scope_filter,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )


@app.get("/audit/stats")
def get_audit_explorer_stats(time_range: Optional[str] = None):
    """Returns statistical summaries for the Audit Explorer dashboard overview."""
    return get_audit_stats(time_range=time_range)


@app.get("/audit/model-evolution-timeline")
def get_model_evolution_timeline(
    query: Optional[str] = None,
    event_type: Optional[str] = None,
    preset: Optional[str] = None,
    limit: int = 200,
):
    """
    Returns the dedicated, cryptographically verifiable Model Evolution timeline:
    - Every proposal (Task C.1)
    - Every human approval / dismissal (Task C.2)
    - Every training job start / stop
    - Every auto-promote / no-promote decision (Task C.3)
    Each entry links directly to the specific benchmark sweep numbers that justified it.
    """
    return evolution_controller.get_evolution_timeline(
        query=query,
        event_type=event_type,
        preset=preset,
        limit=limit,
    )


@app.get("/audit/model-evolution-stats")
def get_model_evolution_stats():
    """Returns real-time KPIs and metrics summary for Model Evolution."""
    res = evolution_controller.get_evolution_timeline(limit=1)
    return res.get("stats", {})



# ==============================================================================
# DATASET CURATION & SFT / DPO TRAINING PIPELINE (Phase 3 & 6)
# ==============================================================================

class CurateExampleRequest(BaseModel):
    example_id: str
    status: str
    notes: Optional[str] = None
    operator: Optional[str] = "operator_secops"


class CleanDatasetRequest(BaseModel):
    min_reward: float = 1.0


class ExpandDatasetRequest(BaseModel):
    min_reward: float = 1.0
    val_ratio: float = 0.10


class StartTrainingJobRequest(BaseModel):
    job_type: str = "sft"  # sft, dpo, grpo, pretrain_scale
    preset: str = "kairo-compact-380m"
    epochs: int = 1
    learning_rate: float = 5e-5
    batch_size: int = 2
    beta: float = 0.1
    use_cleaned: bool = True
    max_steps: Optional[int] = None
    output_dir: Optional[str] = None
    version: Optional[str] = None


@app.get("/training/dataset/stats")
def get_training_dataset_stats():
    """Retrieves high-level dataset statistics, split breakdowns, and curation status."""
    return training_manager.get_dataset_stats()


@app.get("/training/dataset/examples")
def list_training_examples(
    dataset_type: str = "sft",
    tool_id: Optional[str] = None,
    tier: Optional[int] = None,
    source_type: Optional[str] = None,
    query: Optional[str] = None,
    curation_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Lists, searches, and filters dataset examples (SFT trajectories or DPO pairs)."""
    return training_manager.list_examples(
        dataset_type=dataset_type,
        tool_id=tool_id,
        tier=tier,
        source_type=source_type,
        query=query,
        curation_filter=curation_filter,
        limit=limit,
        offset=offset,
    )


@app.post("/training/dataset/curate")
def curate_dataset_example(req: CurateExampleRequest):
    """Applies curation decision ('approved', 'flagged', 'pruned') to an example."""
    return training_manager.curate_example(
        example_id=req.example_id,
        status=req.status,
        notes=req.notes,
        operator=req.operator,
    )


@app.post("/training/dataset/clean")
def run_schema_cleaning(req: CleanDatasetRequest):
    """Executes schema-validation filter to prune malformed trajectories."""
    return training_manager.run_cleaning_filter(min_reward=req.min_reward)


@app.post("/training/dataset/expand")
def expand_training_dataset(req: Optional[ExpandDatasetRequest] = None):
    """Pulls recovery chains, benchmark sweeps, and ToolSpecs across all 27 tools to expand dataset."""
    min_reward = req.min_reward if req else 1.0
    val_ratio = req.val_ratio if req else 0.10
    return training_manager.expand_dataset(min_reward=min_reward, val_ratio=val_ratio)


@app.get("/training/jobs")
def list_training_jobs():
    """Lists running and completed SFT/DPO/GRPO training runs."""
    return {"jobs": training_manager.get_training_jobs()}


@app.post("/training/jobs/start")
def start_training_job(req: StartTrainingJobRequest):
    """Launches an asynchronous training run for Phase 3 SFT or Phase 6 DPO/GRPO."""
    job = training_manager.start_training_job(
        job_type=req.job_type,
        preset=req.preset,
        epochs=req.epochs,
        learning_rate=req.learning_rate,
        batch_size=req.batch_size,
        beta=req.beta,
        use_cleaned=req.use_cleaned,
        max_steps=req.max_steps,
        output_dir=req.output_dir,
        version=req.version,
    )
    return {"job": job, "status": "started"}


@app.get("/training/jobs/{job_id}")
def get_training_job_status(job_id: str):
    """Retrieves step-by-step progress, loss metrics, and console logs for a training job."""
    job = training_manager.get_training_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found")
    return {"job": job}


@app.post("/training/jobs/{job_id}/stop")
def stop_training_job(job_id: str):
    """Terminates an active training job."""
    success = training_manager.stop_training_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found or already stopped")
    return {"job_id": job_id, "status": "stopped"}


@app.get("/training/checkpoints")
def list_training_checkpoints():
    """Scans and lists available model checkpoints in training/checkpoints/."""
    return {"checkpoints": training_manager.list_checkpoints()}


# ==============================================================================
# PUBLIC BENCHMARK LEADERBOARD (Task 2.7 Golden & Task 6.2 Full)
# ==============================================================================

class TriggerBenchmarkRequest(BaseModel):
    benchmark_type: str = "full"  # "golden" (50 tasks) or "full" (120 tasks)
    model_id: Optional[Union[str, List[str]]] = "kairo-dpo-1b"
    model_ids: Optional[List[str]] = None
    eval_mode: str = "post-dpo"
    sweep_id: Optional[str] = None
    task_limit: Optional[int] = None
    use_runner: bool = False


class BenchmarkSweepRequest(BaseModel):
    model_ids: Optional[List[str]] = None
    sweep_id: Optional[str] = None
    task_limit: Optional[int] = None


@app.get("/benchmark/leaderboard")
def get_benchmark_leaderboard():
    """
    Returns public-facing benchmark leaderboard scores across model versions and time.
    Provides rigorous head-to-head empirical comparisons against PentAGI, Strix, and CAI.
    """
    return benchmark_manager.get_leaderboard_data()


@app.get("/benchmark/runs/{run_id}")
def get_benchmark_run_details(run_id: str):
    """Retrieves detailed per-task execution trace for a historical benchmark run."""
    details = benchmark_manager.get_run_details(run_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found")
    return {"run": details}


@app.post("/benchmark/run")
def trigger_benchmark_run(req: TriggerBenchmarkRequest):
    """Triggers an on-demand evaluation against the Golden or Full benchmark suite or a list of models."""
    return benchmark_manager.trigger_benchmark_run(
        benchmark_type=req.benchmark_type,
        model_id=req.model_id,
        model_ids=req.model_ids,
        eval_mode=req.eval_mode,
        sweep_id=req.sweep_id,
        task_limit=req.task_limit,
        use_runner=req.use_runner,
    )


@app.post("/benchmark/sweep")
def trigger_benchmark_sweep(req: Optional[BenchmarkSweepRequest] = None):
    """Executes a sequential benchmark sweep across configured models."""
    r = req or BenchmarkSweepRequest()
    return benchmark_manager.run_full_sweep(
        model_ids=r.model_ids,
        sweep_id=r.sweep_id,
        task_limit=r.task_limit,
    )


@app.get("/benchmark/public-card")
def get_public_benchmark_card():
    """Returns cryptographic SHA256 evaluation digest and reproducibility instructions."""
    return benchmark_manager.get_public_verification_card()


@app.get("/benchmark/sweeps/{sweep_id}")
def get_benchmark_sweep_comparison(sweep_id: str):
    """Retrieves comparative side-by-side analysis and metric rankings for a benchmark sweep."""
    res = benchmark_manager.get_sweep_comparison(sweep_id=sweep_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not found")
    return res


@app.get("/benchmark/sweep-comparison")
def get_latest_sweep_comparison(sweep_id: Optional[str] = None):
    """Retrieves comparative side-by-side analysis and metric rankings for the latest sweep."""
    return benchmark_manager.get_sweep_comparison(sweep_id=sweep_id)


# ==============================================================================
# MODEL EVOLUTION CONTROLLER (Autonomous Model Lifecycle Management)
# ==============================================================================

class EvolutionCycleRequest(BaseModel):
    dataset_stats_override: Optional[Dict[str, Any]] = None
    leaderboard_data_override: Optional[Dict[str, Any]] = None
    sweep_comparison_override: Optional[Dict[str, Any]] = None


@app.get("/evolution/status")
def get_evolution_status():
    """Returns runtime telemetry, cycle counts, active proposals, and state for the evolution controller."""
    return evolution_controller.get_status()


@app.get("/evolution/proposals")
def list_evolution_proposals(limit: int = 50):
    """Returns inspectable proposals recorded by the evolution controller."""
    return {"proposals": evolution_controller.get_proposals(limit=limit)}


@app.get("/evolution/policy")
def get_evolution_policy():
    """Returns the currently loaded evolution policy config."""
    return {"policy": evolution_controller.policy}


@app.post("/evolution/cycle")
def run_evolution_cycle(req: Optional[EvolutionCycleRequest] = None):
    """Executes a single synchronous evaluation cycle of the evolution controller rules."""
    r = req or EvolutionCycleRequest()
    return evolution_controller.run_cycle(
        dataset_stats_override=r.dataset_stats_override,
        leaderboard_data_override=r.leaderboard_data_override,
        sweep_comparison_override=r.sweep_comparison_override,
    )


@app.post("/evolution/start")
def start_evolution_controller():
    """Launches the background periodic evolution worker thread."""
    return evolution_controller.start()


@app.post("/evolution/stop")
def stop_evolution_controller():
    """Stops the background periodic evolution worker thread."""
    return evolution_controller.stop()


@app.post("/evolution/reload-policy")
def reload_evolution_policy():
    """Hot-reloads the evolution policy from evolution_policy.yaml."""
    return {"policy": evolution_controller.reload_policy()}


class ProposalDecisionRequest(BaseModel):
    operator: Optional[str] = "operator_secops"
    reason: Optional[str] = None


@app.post("/evolution/proposals/{proposal_id}/approve")
def approve_evolution_proposal(proposal_id: str, req: Optional[ProposalDecisionRequest] = None):
    """
    HUMAN-IN-THE-LOOP CHECKPOINT:
    Approves a pending proposal and triggers the corresponding training run.
    The controller NEVER calls start_training_job directly from its background decision loop.
    """
    operator = req.operator if req and req.operator else "operator_secops"
    res = evolution_controller.approve_proposal(proposal_id, operator=operator)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to approve proposal"))
    return res


@app.post("/evolution/proposals/{proposal_id}/dismiss")
def dismiss_evolution_proposal(proposal_id: str, req: Optional[ProposalDecisionRequest] = None):
    """Dismisses a pending evolution proposal without triggering any training job."""
    operator = req.operator if req and req.operator else "operator_secops"
    reason = req.reason if req else None
    res = evolution_controller.dismiss_proposal(proposal_id, operator=operator, reason=reason)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to dismiss proposal"))
    return res


@app.get("/evolution/evaluations")
def list_evolution_evaluations(limit: int = 50):
    """Returns automated evaluation records and promotion notices for completed training runs (Task C.3)."""
    return {"evaluations": evolution_controller.get_evaluations(limit=limit)}


@app.post("/evolution/evaluate-jobs")
def evaluate_completed_jobs_now():
    """Triggers evaluation and auto-promotion/guarded rollback check on completed training jobs."""
    results = evolution_controller.evaluate_completed_jobs()
    return {"evaluations": results, "count": len(results)}





# ==============================================================================
# TRUSTWORTHY EXECUTION & FINDINGS VERIFICATION ENDPOINTS
# ==============================================================================

class VerifyFindingRequest(BaseModel):
    allowed_targets: Optional[List[str]] = None


@app.get("/findings")
def list_findings_endpoint(
    session_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    affected_asset: Optional[str] = None,
    severity: Optional[str] = None,
    verified_only: Optional[bool] = False,
):
    """Lists security findings from the EvidenceStore with verification status."""
    from orchestrator.evidence_store import EvidenceStore
    store = EvidenceStore(db_path=agent.db_path)
    findings = store.list_findings(
        session_id=session_id,
        plan_id=plan_id,
        affected_asset=affected_asset,
        severity=severity,
    )
    if verified_only:
        findings = [f for f in findings if f.verified]
    return {
        "findings": [f.to_dict() for f in findings],
        "count": len(findings),
    }


@app.get("/findings/{finding_id}")
def get_finding_endpoint(finding_id: str):
    """Retrieves a single security finding with verification details and evidence references."""
    from orchestrator.evidence_store import EvidenceStore
    store = EvidenceStore(db_path=agent.db_path)
    finding = store.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found.")
    return finding.to_dict()


@app.post("/findings/{finding_id}/verify")
def verify_single_finding_endpoint(finding_id: str, req: Optional[VerifyFindingRequest] = None):
    """
    Executes an authorized verification check against the finding's target asset.
    Gated by the active ScopeContract: out-of-scope targets are blocked.
    """
    from orchestrator.finding_verifier import FindingVerifier
    verifier = FindingVerifier(db_path=agent.db_path)
    allowed = req.allowed_targets if req else None
    result = verifier.verify_finding(finding_id, allowed_targets=allowed)
    if "error" in result and result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ==============================================================================
# TOOL KNOWLEDGE CENTER ENDPOINTS
# ==============================================================================

@app.get("/knowledge/tools")
def list_knowledge_tools(
    category: Optional[str] = None,
    installed_only: bool = False,
    execution_type: Optional[str] = None,
    query: Optional[str] = None,
):
    """Lists registered tools with live/cached installation status, categories, and summary metadata."""
    tools = tool_knowledge_center.list_tools(
        category=category,
        installed_only=installed_only,
        execution_type=execution_type,
        query=query,
    )
    return {"tools": tools, "total_count": len(tools)}


@app.get("/knowledge/tools/{tool_id}")
def get_knowledge_tool_details(tool_id: str):
    """Retrieves full 13-section technical specifications, guidance, and examples for a tool."""
    detail = tool_knowledge_center.get_tool_details(tool_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found in Tool Knowledge Center")
    return detail


@app.post("/knowledge/tools/{tool_id}/verify")
def verify_knowledge_tool(tool_id: str):
    """Runs a live verification health check on a tool in the execution environment."""
    res = tool_knowledge_center.verify_tool(tool_id)
    if not res.get("success") and "not found" in res.get("error", "").lower():
        raise HTTPException(status_code=404, detail=res["error"])
    return res


# ==============================================================================
# AUTOMATIC KALI & TOOL UPDATE ENDPOINTS
# ==============================================================================

@app.get("/updates/status")
def get_updates_status():
    """Returns the current state of the Kali and tool update subsystem."""
    return update_manager.get_status()


@app.post("/updates/check")
def check_updates():
    """Discovers available updates across system, tools, and vulnerability databases."""
    updates = update_manager.check_updates()
    return {"updates": [u.to_dict() for u in updates], "count": len(updates)}


@app.post("/updates/apply")
def apply_update(req: UpdateApplyRequest):
    """Applies a package/database update with pre-update snapshot and post-update health check."""
    rec = update_manager.apply_update(
        item_id=req.item_id,
        create_snapshot=req.create_snapshot if req.create_snapshot is not None else True,
    )
    return rec


@app.post("/updates/rollback")
def rollback_update_snapshot(req: UpdateRollbackRequest):
    """Restores a previous system recovery point snapshot."""
    res = update_manager.rollback_to_snapshot(req.snapshot_name)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error", "Rollback failed"))
    return res


@app.post("/updates/policy")
def set_update_policy(req: UpdatePolicyRequest):
    """Configures the operational update policy (standard_managed, managed_rolling, manual_control)."""
    ok = update_manager.set_policy(req.policy)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Invalid update policy: '{req.policy}'")
    return {"policy": update_manager.policy.value, "success": True}


@app.get("/updates/history")
def get_update_history(limit: int = 50):
    """Retrieves immutable audit history of applied updates and rollbacks."""
    return {"history": update_manager.list_update_history(limit=limit)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("orchestrator.server:app", host="127.0.0.1", port=8000, reload=False)



