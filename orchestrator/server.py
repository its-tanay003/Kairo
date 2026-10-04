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

from events.db import Event, insert_event, get_events_by_session, get_recent_events
from orchestrator.agent import AgentLoop
from orchestrator.model_center import model_center
from orchestrator.process_supervisor import supervisor
from orchestrator.vm_manager import vm_manager

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
        timeout_ms=int(req.timeout_ms or 30000),
    )
    end_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Log to SQLite event store (Task 0.1 schema)
    try:
        event = Event.create(
            session_id=req.session_id or "vm_session",
            task_id=tid,
            actor="worker_agent@kali_vm",
            tool_id="kali.exec.v1",
            tool_version="1.0.0",
            requested_args={"command": req.command, "args": req.args or [], "cwd": req.cwd or "/home/kali", "snapshot_before": req.snapshot_before},
            normalized_args={"command": req.command, "args": req.args or [], "cwd": req.cwd or "/home/kali"},
            process_id=result.get("process_id"),
            start_time=start_iso,
            end_time=end_iso,
            exit_code=result.get("exit_code"),
            stdout_ref=f"inline://{result.get('stdout', '')[:120]}" if result.get("stdout") else None,
            stderr_ref=f"inline://{result.get('stderr', '')[:120]}" if result.get("stderr") else None,
            artifact_refs=[f"snapshot://{result.get('snapshot_name')}"] if result.get("snapshot_name") else [],
            screenshots=[],
            network_context={"ip": "127.0.0.1", "port_ssh": 2222, "port_worker": 9999, "vm": "kali-linux-2026.1-virtualbox-amd64"},
            result_summary=f"VM execution of '{req.command}' finished with exit code {result.get('exit_code')}",
            confidence=1.0,
            parent_event=None,
            timestamp=start_iso,
        )
        insert_event(event, agent.db_path)
    except Exception as e:
        print(f"[Orchestrator] Warning: could not log event: {e}")

    return result


@app.post("/vm/kill/{task_id}")
def vm_kill(task_id: str):
    """Sends SIGKILL to an active task inside the Kali VM."""
    return vm_manager.kill_task_in_vm(task_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("orchestrator.server:app", host="127.0.0.1", port=8000, reload=False)
