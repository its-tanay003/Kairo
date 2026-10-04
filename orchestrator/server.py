"""
FastAPI Server for Orchestrator. Exposes endpoints to trigger agent loop, query events,
and activate SIGKILL kill switch for running supervisor processes.
"""

from pathlib import Path
import sys
from typing import Any, Dict, Optional

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from events.db import get_events_by_session, get_recent_events
from orchestrator.agent import AgentLoop
from orchestrator.model_center import model_center
from orchestrator.process_supervisor import supervisor

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


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "orchestrator",
        "llama_cpp": {
            "healthy": agent.llama_client.is_healthy(),
            "url": agent.llama_client.base_url,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("orchestrator.server:app", host="127.0.0.1", port=8000, reload=False)
