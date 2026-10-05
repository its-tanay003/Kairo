"""
Workspace Manager for Autonomous Cyber Agent Platform.
Manages project lifecycle and server-side provisioning of disposable Kali sandbox environments.

Features:
- "Boot a disposable Kali VM per project/session" on the server side.
- Manages workspace state, ephemeral storage, and port allocations.
- Integrates with KaliWorkerConnector for WSL2, native Linux, and macOS Virtualization.
- Automatically tears down and cleans up ephemeral project sandboxes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from orchestrator.kali_connector import get_kali_connector, ExecutionPlaneType

logger = logging.getLogger("orchestrator.workspace_manager")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "events" / "events.db"
WORKSPACES_ROOT = ROOT_DIR / "workspaces"


class WorkspaceStatus(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass
class Workspace:
    workspace_id: str
    project_name: str
    session_id: str
    owner_id: str
    status: WorkspaceStatus
    plane_type: str
    backend_name: str
    disposable_vm_id: str
    ephemeral_dir: str
    network_isolated: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    terminated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["guest_dir"] = self.metadata.get("guest_work_dir", f"/tmp/kairo_workspaces/{self.workspace_id}")
        data["host_dir"] = self.ephemeral_dir
        return data


class WorkspaceManager:
    """
    Manages isolated project workspaces and server-side disposable Kali VMs.
    """

    def __init__(self, db_path: Optional[Path | str] = None, workspaces_root: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.workspaces_root = Path(workspaces_root) if workspaces_root else WORKSPACES_ROOT
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.connector = get_kali_connector()
        self._init_workspace_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_workspace_table(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspaces (
                        workspace_id TEXT PRIMARY KEY,
                        project_name TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        owner_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        plane_type TEXT NOT NULL,
                        backend_name TEXT NOT NULL,
                        disposable_vm_id TEXT NOT NULL,
                        ephemeral_dir TEXT NOT NULL,
                        network_isolated INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL,
                        terminated_at TEXT,
                        metadata TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_session ON workspaces(session_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_status ON workspaces(status);")
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing workspaces table: {e}")

    def provision_disposable_workspace(
        self,
        project_name: str,
        session_id: str,
        owner_id: str = "default_user",
        network_isolated: bool = True,
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> Workspace:
        """
        Boots a disposable Kali sandbox / VM instance for a project or session.
        Allocates isolated ephemeral storage and prepares the target execution environment.
        """
        workspace_id = f"ws_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        plane_info = self.connector.get_status()
        plane_type = plane_info.get("plane_type", "unknown")
        backend_name = plane_info.get("backend_name", "Kali Sandbox")

        # 1. Prepare host-side ephemeral directory
        host_ephemeral_dir = self.workspaces_root / workspace_id
        host_ephemeral_dir.mkdir(parents=True, exist_ok=True)
        (host_ephemeral_dir / "artifacts").mkdir(exist_ok=True)
        (host_ephemeral_dir / "logs").mkdir(exist_ok=True)

        disposable_vm_id = f"kali-disposable-{workspace_id}"

        # 2. Server-side disposable sandbox provisioning
        guest_work_dir = f"/tmp/kairo_workspaces/{workspace_id}"
        provision_success = True
        error_msg = None

        try:
            # Create guest workspace folder inside Kali sandbox (WSL2, Native Linux, or VM)
            setup_cmd = f"mkdir -p {guest_work_dir}/artifacts {guest_work_dir}/logs && chmod 700 {guest_work_dir}"
            init_res = self.connector.execute(
                task_id=f"init_{workspace_id}",
                command="bash",
                args=["-c", setup_cmd],
                timeout_ms=10000,
            )
            if init_res.get("exit_code") != 0 and init_res.get("status") == "error":
                logger.warning(f"Could not initialize guest workspace dir: {init_res.get('stderr')}")
        except Exception as e:
            logger.warning(f"Error during disposable sandbox preparation: {e}")
            provision_success = False
            error_msg = str(e)

        meta = custom_metadata or {}
        meta.update({
            "guest_work_dir": guest_work_dir,
            "host_os": plane_info.get("host_os"),
            "distro_name": plane_info.get("distro_name"),
            "wsl_version": plane_info.get("wsl_version"),
            "win_kex_ready": plane_info.get("win_kex", {}).get("ready_for_phase5_gui", False),
            "disposable": True,
        })
        if error_msg:
            meta["provision_error"] = error_msg

        status = WorkspaceStatus.READY if provision_success else WorkspaceStatus.ERROR

        ws = Workspace(
            workspace_id=workspace_id,
            project_name=project_name,
            session_id=session_id,
            owner_id=owner_id,
            status=status,
            plane_type=plane_type,
            backend_name=backend_name,
            disposable_vm_id=disposable_vm_id,
            ephemeral_dir=str(host_ephemeral_dir),
            network_isolated=network_isolated,
            metadata=meta,
        )

        # 3. Persist to SQLite
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO workspaces (
                        workspace_id, project_name, session_id, owner_id, status,
                        plane_type, backend_name, disposable_vm_id, ephemeral_dir,
                        network_isolated, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ws.workspace_id,
                        ws.project_name,
                        ws.session_id,
                        ws.owner_id,
                        ws.status.value,
                        ws.plane_type,
                        ws.backend_name,
                        ws.disposable_vm_id,
                        ws.ephemeral_dir,
                        1 if ws.network_isolated else 0,
                        ws.created_at,
                        json.dumps(ws.metadata),
                    ),
                )
                conn.commit()
            logger.info(f"Provisioned disposable workspace '{workspace_id}' for project '{project_name}' (session: {session_id})")
        except Exception as e:
            logger.error(f"Error persisting workspace record: {e}")

        return ws

    def terminate_workspace(self, workspace_id: str, purge_storage: bool = False) -> Dict[str, Any]:
        """
        Disposes of the ephemeral Kali VM / workspace, cleans up storage, and updates status.
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return {"error": f"Workspace '{workspace_id}' not found", "status": "not_found"}

        terminated_at = datetime.now(timezone.utc).isoformat()
        guest_dir = ws.metadata.get("guest_work_dir")

        # 1. Clean up in-guest disposable files
        if guest_dir:
            try:
                self.connector.execute(
                    task_id=f"cleanup_{workspace_id}",
                    command="rm",
                    args=["-rf", guest_dir],
                    timeout_ms=10000,
                )
            except Exception as e:
                logger.warning(f"Error cleaning guest workspace directory {guest_dir}: {e}")

        # 2. Optionally purge host-side storage
        if purge_storage and os.path.exists(ws.ephemeral_dir):
            try:
                shutil.rmtree(ws.ephemeral_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Error purging host workspace directory {ws.ephemeral_dir}: {e}")

        # 3. Update status in database
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE workspaces SET status = ?, terminated_at = ? WHERE workspace_id = ?",
                    (WorkspaceStatus.TERMINATED.value, terminated_at, workspace_id),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating workspace termination status: {e}")

        logger.info(f"Disposed workspace '{workspace_id}' (project: {ws.project_name})")
        return {
            "workspace_id": workspace_id,
            "status": "terminated",
            "terminated_at": terminated_at,
            "purged_storage": purge_storage,
        }

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """Retrieves a workspace by its unique ID."""
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
                if row:
                    return self._row_to_workspace(row)
        except Exception as e:
            logger.error(f"Error retrieving workspace {workspace_id}: {e}")
        return None

    def get_active_workspace_for_session(self, session_id: str) -> Optional[Workspace]:
        """Finds the most recent non-terminated workspace for a session."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM workspaces
                    WHERE session_id = ? AND status != 'terminated'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
                if row:
                    return self._row_to_workspace(row)
        except Exception as e:
            logger.error(f"Error retrieving active workspace for session {session_id}: {e}")
        return None

    def list_workspaces(
        self,
        status: Optional[str] = None,
        project_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Workspace]:
        """Lists workspaces with optional filtering."""
        workspaces = []
        try:
            with self._get_connection() as conn:
                query = "SELECT * FROM workspaces WHERE 1=1"
                params: List[Any] = []
                if status:
                    query += " AND status = ?"
                    params.append(status)
                if project_name:
                    query += " AND project_name = ?"
                    params.append(project_name)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                for row in conn.execute(query, params).fetchall():
                    workspaces.append(self._row_to_workspace(row))
        except Exception as e:
            logger.error(f"Error listing workspaces: {e}")
        return workspaces

    def _row_to_workspace(self, row: sqlite3.Row) -> Workspace:
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                meta = {}
        return Workspace(
            workspace_id=row["workspace_id"],
            project_name=row["project_name"],
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            status=WorkspaceStatus(row["status"]),
            plane_type=row["plane_type"],
            backend_name=row["backend_name"],
            disposable_vm_id=row["disposable_vm_id"],
            ephemeral_dir=row["ephemeral_dir"],
            network_isolated=bool(row["network_isolated"]),
            created_at=row["created_at"],
            terminated_at=row["terminated_at"],
            metadata=meta,
        )


# Global singleton
workspace_manager = WorkspaceManager()


def get_workspace_manager() -> WorkspaceManager:
    return workspace_manager
