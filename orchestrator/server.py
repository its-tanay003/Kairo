"""
FastAPI Server for Orchestrator. Exposes endpoints to trigger agent loop, query events,
and activate SIGKILL kill switch for running supervisor processes.
"""

from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dataclasses import asdict
from events.db import (
    Event,
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

app = FastAPI(title="Agent Orchestrator Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = AgentLoop()


class RunRequest(BaseModel):
    session_id: str
    message: str
    task_id: Optional[str] = None
    parent_event: Optional[str] = None
    explicit_tool: Optional[str] = None
    explicit_args: Optional[Dict[str, Any]] = None


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


class ToolSelectRequest(BaseModel):
    goal: Optional[str] = None
    intent: Optional[str] = None
    required_capability: Optional[str] = None
    capability: Optional[str] = None
    session_id: Optional[str] = "default_session"
    top_k: Optional[int] = 3
    environment: Optional[Dict[str, Any]] = None
    budget: Optional[float] = None


class ScopeContractCreateRequest(BaseModel):
    targets: List[str]
    network_scope: str = "authorized_lab"
    time_window: str = "8h"
    allowed_tool_tiers: List[int] = [1, 2, 3]
    authorized_by: str = "secops_lead@kairo.internal"
    metadata: Optional[Dict[str, Any]] = None


class ScopeValidateRequest(BaseModel):
    target: Optional[str] = None
    tool_id: Optional[str] = None
    tool_tier: Optional[int] = None


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


@app.get("/model-center")
def get_model_center_status():
    """Reports which model is currently loaded, VRAM/RAM usage, and context length."""
    return model_center.get_status(llama_url=agent.llama_client.base_url)


@app.post("/run")
def run_loop(req: RunRequest):
    try:
        result = agent.execute_task(
            session_id=req.session_id,
            message=req.message,
            task_id=req.task_id,
            parent_event=req.parent_event,
            explicit_tool=req.explicit_tool,
            explicit_args=req.explicit_args,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
def vm_execute(req: VMExecuteRequest):
    """Executes a typed ToolSpec command inside the Kali VM via guest Worker Agent."""
    tid = req.task_id or f"task_vm_{int(time.time()*1000)}"
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = vm_manager.execute_in_vm(
        task_id=tid,
        tool_id="kali.exec.v1",
        tool_version="1.0.0",
        args={"command": req.command, "args": req.args or [], "cwd": req.cwd or "/home/kali"},
        snapshot_before=bool(req.snapshot_before),
        rollback_after=bool(req.rollback_after),
        rollback_on_failure=bool(req.rollback_on_failure),
        resource_limits=req.resource_limits,
        artifact_dir=req.artifact_dir,
        timeout_ms=int(req.timeout_ms or 30000),
    )
    end_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Compile artifact references with SHA-256 for evidence integrity
    artifact_refs = []
    for art in result.get("artifacts", []):
        artifact_refs.append(f"sha256:{art.get('sha256')}:{art.get('filename')}")
    if result.get("snapshot_name"):
        artifact_refs.append(f"snapshot://{result.get('snapshot_name')}")
    if result.get("rolled_back"):
        artifact_refs.append(f"rollback://{result.get('rollback_info', {}).get('snapshot_restored', 'kairo_worker_ready')}")

    # Log to SQLite event store (Task 0.1 schema)
    try:
        summary_msg = f"VM execution of '{req.command}' finished with exit code {result.get('exit_code')}"
        if result.get("rolled_back"):
            summary_msg += " (VM rolled back to clean state)"
        if result.get("resource_limit_exceeded"):
            summary_msg += f" (RESOURCE CAP VIOLATION: {result.get('violation_reason')})"

        event = Event.create(
            session_id=req.session_id or "vm_session",
            task_id=tid,
            actor="worker_agent@kali_vm",
            tool_id="kali.exec.v1",
            tool_version="1.0.0",
            requested_args={
                "command": req.command,
                "args": req.args or [],
                "cwd": req.cwd or "/home/kali",
                "snapshot_before": req.snapshot_before,
                "rollback_after": req.rollback_after,
                "rollback_on_failure": req.rollback_on_failure,
                "resource_limits": req.resource_limits,
            },
            normalized_args={"command": req.command, "args": req.args or [], "cwd": req.cwd or "/home/kali"},
            process_id=result.get("process_id"),
            start_time=start_iso,
            end_time=end_iso,
            exit_code=result.get("exit_code"),
            stdout_ref=f"inline://{result.get('stdout', '')[:120]}" if result.get("stdout") else None,
            stderr_ref=f"inline://{result.get('stderr', '')[:120]}" if result.get("stderr") else None,
            artifact_refs=artifact_refs,
            screenshots=[],
            network_context={"ip": "127.0.0.1", "port_ssh": 2222, "port_worker": 9999, "vm": "kali-linux-2026.1-virtualbox-amd64"},
            result_summary=summary_msg,
            confidence=1.0,
            parent_event=None,
            timestamp=start_iso,
        )
        insert_event(event, agent.db_path)
    except Exception as e:
        print(f"[Orchestrator] Warning: could not log event: {e}")

    # Update Tool Memory store
    try:
        record_tool_execution(
            tool_id="kali.exec.v1",
            success=(result.get("exit_code") == 0),
            duration_ms=float(result.get("duration_ms") or 0.0),
            exit_code=result.get("exit_code"),
            timed_out=bool(result.get("timed_out")),
            metadata={"command": req.command, "task_id": tid},
            db_path=agent.db_path,
        )
    except Exception as e:
        print(f"[Orchestrator] Warning: could not update tool memory: {e}")

    return result


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
    plan = planner.decompose(goal=req.goal, session_id=req.session_id, prefer_llm=req.prefer_llm)
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
    valid_statuses = ("queued", "running", "success", "warning", "failed")
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


# Hybrid Tool Selection & Tool Memory Endpoints
@app.post("/tools/select")
def select_tool_endpoint(req: ToolSelectRequest):
    """Evaluates candidate tools using the hybrid scoring function and returns top 3 with full breakdown."""
    goal = req.goal or req.intent or ""
    if not goal.strip():
        raise HTTPException(status_code=400, detail="Missing required 'goal' or 'intent'")
    cap = req.required_capability or req.capability
    res = tool_selector.select(
        goal=goal,
        required_capability=cap,
        session_id=req.session_id or "default_session",
        top_k=req.top_k or 3,
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
def create_scope_contract_endpoint(req: ScopeContractCreateRequest):
    """Creates, cryptographically signs, and activates a new Scope Contract."""
    if not req.targets:
        raise HTTPException(status_code=400, detail="Scope Contract must specify at least one target or CIDR subnet")
    if not req.allowed_tool_tiers:
        raise HTTPException(status_code=400, detail="Scope Contract must allow at least one tool tier [1, 2, or 3]")

    contract = create_scope_contract(
        targets=req.targets,
        network_scope=req.network_scope,
        time_window=req.time_window,
        allowed_tool_tiers=req.allowed_tool_tiers,
        authorized_by=req.authorized_by,
        metadata=req.metadata,
        db_path=agent.db_path,
    )
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


@app.post("/planner/plans/{plan_id}/execute")
def execute_task_graph_endpoint(plan_id: str):
    """
    Executes a task graph DAG.
    MANDATORY GATE: Requires an unexpired, cryptographically signed Scope Contract before any task graph can execute.
    """
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

    plan = get_plan(plan_id, db_path=agent.db_path)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")

    ready_nodes = get_ready_nodes(plan_id, db_path=agent.db_path)
    executed_nodes = []

    for node in ready_nodes:
        node_res = cognitive_engine.execute_node(
            plan_id=plan_id,
            node=node,
            plan=plan,
            contract=contract,
            max_attempts=3,
        )
        executed_nodes.append(node_res)

    return {
        "status": "executed",
        "plan_id": plan_id,
        "authorized_by": contract.get("authorized_by"),
        "scope_contract_id": contract.get("contract_id"),
        "executed_count": len(executed_nodes),
        "executed_nodes": executed_nodes,
        "updated_plan": get_plan(plan_id, db_path=agent.db_path),
    }


@app.post("/planner/plans/{plan_id}/nodes/{node_id}/execute")
def execute_single_node_endpoint(plan_id: str, node_id: str, req: NodeExecuteRequest = NodeExecuteRequest()):
    """
    Executes a single DAG node through the cognitive loop:
    Tool Selection -> Scope Verification -> Execution -> Observer -> Critic -> Recovery Agent (cap: 3).
    """
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

    res = cognitive_engine.execute_node(
        plan_id=plan_id,
        node=target_node,
        plan=plan,
        contract=contract,
        max_attempts=req.max_attempts or 3,
    )
    return {
        "plan_id": plan_id,
        "node_id": node_id,
        "execution_result": res,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("orchestrator.server:app", host="127.0.0.1", port=8000, reload=False)

