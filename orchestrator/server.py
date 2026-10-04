"""
FastAPI Server for Orchestrator. Exposes endpoints to trigger agent loop and query events.
"""

from pathlib import Path
import sys
from typing import Optional

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from events.db import get_events_by_session, get_recent_events
from orchestrator.agent import AgentLoop

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
    }


@app.post("/run")
def run_loop(req: RunRequest):
    try:
        result = agent.execute_task(
            session_id=req.session_id,
            message=req.message,
            task_id=req.task_id,
            parent_event=req.parent_event,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
