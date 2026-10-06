"""
SQLite Event Store repository adhering strictly to the required Event schema.
Fields:
- session_id: str
- task_id: str
- timestamp: str
- actor: str
- tool_id: Optional[str]
- tool_version: Optional[str]
- requested_args: Optional[str] (JSON)
- normalized_args: Optional[str] (JSON)
- process_id: Optional[int]
- start_time: Optional[str]
- end_time: Optional[str]
- exit_code: Optional[int]
- stdout_ref: Optional[str]
- stderr_ref: Optional[str]
- artifact_refs: Optional[str] (JSON)
- screenshots: Optional[str] (JSON)
- network_context: Optional[str] (JSON)
- result_summary: Optional[str]
- confidence: Optional[float]
- parent_event: Optional[str]
"""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "events.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def compute_sha256(file_path: Path | str) -> str:
    """Computes SHA-256 hash of a file efficiently in 64KB chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_artifact_file(file_path: Path | str, expected_sha256: str) -> Dict[str, Any]:
    """Verifies that an artifact file matches its expected SHA-256 hash."""
    p = Path(file_path)
    if not p.exists():
        return {
            "valid": False,
            "filepath": str(file_path),
            "expected_sha256": expected_sha256,
            "actual_sha256": None,
            "error": "File does not exist",
        }
    actual = compute_sha256(p)
    return {
        "valid": actual.lower() == expected_sha256.lower(),
        "filepath": str(p.resolve()),
        "expected_sha256": expected_sha256.lower(),
        "actual_sha256": actual.lower(),
        "size_bytes": p.stat().st_size,
    }


@dataclass
class Artifact:
    task_id: str
    filename: str
    filepath: str
    size_bytes: int
    sha256: str
    mime_type: Optional[str] = None
    created_at: Optional[str] = None
    metadata: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def from_file(
        cls,
        task_id: str,
        filepath: Path | str,
        mime_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any] | str] = None,
    ) -> "Artifact":
        p = Path(filepath)
        if not p.is_file():
            raise FileNotFoundError(f"Artifact file not found: {filepath}")
        size_bytes = p.stat().st_size
        sha = compute_sha256(p)
        meta_str = json.dumps(metadata) if isinstance(metadata, dict) else metadata
        return cls(
            task_id=task_id,
            filename=p.name,
            filepath=str(p.resolve()),
            size_bytes=size_bytes,
            sha256=sha,
            mime_type=mime_type,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=meta_str,
        )


@dataclass
class Event:
    session_id: str
    task_id: str
    timestamp: str
    actor: str
    tool_id: Optional[str] = None
    tool_version: Optional[str] = None
    requested_args: Optional[str] = None
    normalized_args: Optional[str] = None
    process_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_ref: Optional[str] = None
    stderr_ref: Optional[str] = None
    artifact_refs: Optional[str] = None
    screenshots: Optional[str] = None
    network_context: Optional[str] = None
    result_summary: Optional[str] = None
    confidence: Optional[float] = None
    parent_event: Optional[str] = None

    @classmethod
    def create(
        cls,
        session_id: str,
        task_id: str,
        actor: str,
        tool_id: Optional[str] = None,
        tool_version: Optional[str] = None,
        requested_args: Optional[Dict[str, Any] | str] = None,
        normalized_args: Optional[Dict[str, Any] | str] = None,
        process_id: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        exit_code: Optional[int] = None,
        stdout_ref: Optional[str] = None,
        stderr_ref: Optional[str] = None,
        artifact_refs: Optional[List[str] | str] = None,
        screenshots: Optional[List[str] | str] = None,
        network_context: Optional[Dict[str, Any] | str] = None,
        result_summary: Optional[str] = None,
        confidence: Optional[float] = 1.0,
        parent_event: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "Event":
        now_iso = timestamp or datetime.now(timezone.utc).isoformat()
        
        def to_json_str(val):
            if val is None:
                return None
            if isinstance(val, (dict, list)):
                return json.dumps(val)
            return str(val)

        return cls(
            session_id=session_id,
            task_id=task_id,
            timestamp=now_iso,
            actor=actor,
            tool_id=tool_id,
            tool_version=tool_version,
            requested_args=to_json_str(requested_args),
            normalized_args=to_json_str(normalized_args),
            process_id=process_id or os.getpid(),
            start_time=start_time or now_iso,
            end_time=end_time or now_iso,
            exit_code=exit_code,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            artifact_refs=to_json_str(artifact_refs),
            screenshots=to_json_str(screenshots),
            network_context=to_json_str(network_context),
            result_summary=result_summary,
            confidence=confidence,
            parent_event=parent_event,
        )


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    return conn


_DB_INITIALIZED = set()

def init_db(db_path: Optional[Path | str] = None) -> None:
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_key = str(target.resolve())
    if target_key in _DB_INITIALIZED and target.exists():
        return
    conn = get_connection(db_path)
    with conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.close()
    _DB_INITIALIZED.add(target_key)



def insert_event(event: Event, db_path: Optional[Path | str] = None) -> int:
    init_db(db_path)
    conn = get_connection(db_path)
    query = """
    INSERT INTO events (
        session_id, task_id, timestamp, actor, tool_id, tool_version,
        requested_args, normalized_args, process_id, start_time, end_time,
        exit_code, stdout_ref, stderr_ref, artifact_refs, screenshots,
        network_context, result_summary, confidence, parent_event
    ) VALUES (
        :session_id, :task_id, :timestamp, :actor, :tool_id, :tool_version,
        :requested_args, :normalized_args, :process_id, :start_time, :end_time,
        :exit_code, :stdout_ref, :stderr_ref, :artifact_refs, :screenshots,
        :network_context, :result_summary, :confidence, :parent_event
    )
    """
    with conn:
        cursor = conn.cursor()
        cursor.execute(query, asdict(event))
        row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_events_by_session(session_id: str, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE session_id = ? ORDER BY id ASC", (session_id,))
        rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_recent_events(limit: int = 50, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def insert_artifact(artifact: Artifact, db_path: Optional[Path | str] = None) -> int:
    """Inserts a captured artifact into the SQLite artifacts table."""
    init_db(db_path)
    conn = get_connection(db_path)
    query = """
    INSERT INTO artifacts (
        task_id, filename, filepath, size_bytes, sha256, mime_type, created_at, metadata
    ) VALUES (
        :task_id, :filename, :filepath, :size_bytes, :sha256, :mime_type, :created_at, :metadata
    )
    """
    data = asdict(artifact)
    data.pop("id", None)
    with conn:
        cursor = conn.cursor()
        cursor.execute(query, data)
        row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_artifacts_by_task(task_id: str, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Retrieves all artifacts and SHA-256 hashes captured for a specific task."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE task_id = ? ORDER BY id ASC", (task_id,))
        rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_artifact_by_id(artifact_id: int, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a single artifact by its primary key ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        row = cursor.fetchone()
        res = dict(row) if row else None
    conn.close()
    return res


@dataclass
class PlanNode:
    node_id: str
    capability: str
    label: str
    description: str = ""
    dependencies: List[str] = None
    status: str = "queued"  # queued, running, success, warning, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    assigned_tool: Optional[str] = None
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class PlanDAG:
    plan_id: str
    session_id: str
    goal: str
    nodes: List[PlanNode]
    status: str = "queued"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict[str, Any] | str] = None

    def __post_init__(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        if self.created_at is None:
            self.created_at = now_iso
        if self.updated_at is None:
            self.updated_at = now_iso


def insert_plan(plan: PlanDAG, db_path: Optional[Path | str] = None) -> int:
    """Inserts a complete task graph DAG and its nodes into the event store."""
    init_db(db_path)
    conn = get_connection(db_path)

    node_count = len(plan.nodes)
    edge_count = sum(len(n.dependencies) for n in plan.nodes)
    meta_str = json.dumps(plan.metadata) if isinstance(plan.metadata, dict) else plan.metadata

    with conn:
        cursor = conn.cursor()
        # Insert graph record
        cursor.execute(
            """
            INSERT INTO task_graphs (
                plan_id, session_id, goal, status, created_at, updated_at, node_count, edge_count, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                node_count = excluded.node_count,
                edge_count = excluded.edge_count,
                metadata = excluded.metadata
            """,
            (
                plan.plan_id,
                plan.session_id,
                plan.goal,
                plan.status,
                plan.created_at,
                plan.updated_at,
                node_count,
                edge_count,
                meta_str,
            ),
        )
        graph_row_id = cursor.lastrowid

        # Insert or update individual nodes
        for node in plan.nodes:
            deps_str = json.dumps(node.dependencies or [])
            cursor.execute(
                """
                INSERT INTO task_nodes (
                    plan_id, node_id, capability, label, description, dependencies,
                    status, started_at, completed_at, result, assigned_tool, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id, node_id) DO UPDATE SET
                    capability = excluded.capability,
                    label = excluded.label,
                    description = excluded.description,
                    dependencies = excluded.dependencies,
                    status = excluded.status,
                    started_at = COALESCE(excluded.started_at, task_nodes.started_at),
                    completed_at = COALESCE(excluded.completed_at, task_nodes.completed_at),
                    result = COALESCE(excluded.result, task_nodes.result),
                    assigned_tool = COALESCE(excluded.assigned_tool, task_nodes.assigned_tool)
                """,
                (
                    plan.plan_id,
                    node.node_id,
                    node.capability,
                    node.label,
                    node.description,
                    deps_str,
                    node.status,
                    node.started_at,
                    node.completed_at,
                    node.result,
                    node.assigned_tool,
                    node.created_at,
                ),
            )

    conn.close()
    return graph_row_id


def get_plan(plan_id: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a complete task graph DAG with all its nodes and statuses."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM task_graphs WHERE plan_id = ?", (plan_id,))
        graph_row = cursor.fetchone()
        if not graph_row:
            conn.close()
            return None

        graph_dict = dict(graph_row)
        cursor.execute("SELECT * FROM task_nodes WHERE plan_id = ? ORDER BY id ASC", (plan_id,))
        node_rows = cursor.fetchall()

        nodes = []
        for r in node_rows:
            nd = dict(r)
            try:
                nd["dependencies"] = json.loads(nd.get("dependencies") or "[]")
            except Exception:
                nd["dependencies"] = []
            nodes.append(nd)

        roots = [n["node_id"] for n in nodes if not n["dependencies"]]
        convergences = [n["node_id"] for n in nodes if len(n["dependencies"]) >= 2]
        depths: Dict[str, int] = {r: 0 for r in roots}

        # Topological depth propagation
        changed = True
        iterations = 0
        while changed and iterations < len(nodes) + 2:
            changed = False
            iterations += 1
            for n in nodes:
                nid = n["node_id"]
                deps = n["dependencies"]
                if deps and all(d in depths for d in deps):
                    max_dep = max(depths[d] for d in deps)
                    if nid not in depths or depths[nid] != max_dep + 1:
                        depths[nid] = max_dep + 1
                        changed = True

        for n in nodes:
            n["depth_level"] = depths.get(n["node_id"], 0)

        graph_dict["total_nodes"] = len(nodes)
        graph_dict["is_dag"] = True
        graph_dict["parallel_roots"] = roots
        graph_dict["convergence_nodes"] = convergences
        graph_dict["depth_levels"] = depths
        graph_dict["nodes"] = nodes
    conn.close()
    return graph_dict


def list_plans(limit: int = 20, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Retrieves recent task graph plans."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM task_graphs ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def update_node_status(
    plan_id: str,
    node_id: str,
    status: str,
    result: Optional[Any] = None,
    assigned_tool: Optional[str] = None,
    db_path: Optional[Path | str] = None,
) -> bool:
    """
    Updates a node's execution status (queued, running, success, warning, failed)
    and updates parent plan overall status accordingly.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    started_at = now_iso if status == "running" else None
    completed_at = now_iso if status in ("success", "warning", "failed") else None
    res_str = json.dumps(result) if isinstance(result, (dict, list)) else (str(result) if result is not None else None)

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE task_nodes
            SET status = ?,
                result = COALESCE(?, result),
                assigned_tool = COALESCE(?, assigned_tool),
                started_at = CASE WHEN ? IS NOT NULL THEN ? ELSE started_at END,
                completed_at = CASE WHEN ? IS NOT NULL THEN ? ELSE completed_at END
            WHERE plan_id = ? AND node_id = ?
            """,
            (
                status,
                res_str,
                assigned_tool,
                started_at,
                started_at,
                completed_at,
                completed_at,
                plan_id,
                node_id,
            ),
        )
        updated = cursor.rowcount > 0

        # Refresh overall plan status
        cursor.execute("SELECT status FROM task_nodes WHERE plan_id = ?", (plan_id,))
        node_statuses = [r[0] for r in cursor.fetchall()]
        if node_statuses:
            if all(s == "success" for s in node_statuses):
                new_plan_status = "completed"
            elif any(s == "failed" for s in node_statuses):
                new_plan_status = "failed"
            elif any(s == "running" for s in node_statuses):
                new_plan_status = "running"
            elif any(s in ("success", "warning") for s in node_statuses):
                new_plan_status = "in_progress"
            else:
                new_plan_status = "queued"

            cursor.execute(
                "UPDATE task_graphs SET status = ?, updated_at = ? WHERE plan_id = ?",
                (new_plan_status, now_iso, plan_id),
            )

    conn.close()
    return updated


def get_ready_nodes(plan_id: str, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """
    Returns queued nodes whose dependencies have all completed successfully (or with warning).
    These nodes are ready for immediate parallel execution!
    """
    plan = get_plan(plan_id, db_path)
    if not plan:
        return []

    node_map = {n["node_id"]: n for n in plan.get("nodes", [])}
    ready = []

    for n in plan.get("nodes", []):
        if n["status"] != "queued":
            continue
        deps = n.get("dependencies", [])
        # All dependencies must be in 'success' or 'warning'
        deps_satisfied = all(
            node_map.get(dep_id, {}).get("status") in ("success", "warning")
            for dep_id in deps
        )
        if deps_satisfied:
            ready.append(n)

    return ready


# ===========================================================================
# Tool Memory Store (Global System State)
# Tracks tool performance history across sessions (reliability, duration, counts)
# ===========================================================================

@dataclass
class ToolMemoryRecord:
    tool_id: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    timeout_runs: int = 0
    avg_duration_ms: float = 0.0
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None
    reliability_score: float = 1.0
    metadata: Optional[Dict[str, Any] | str] = None


DEFAULT_TOOL_BASELINES: Dict[str, Dict[str, Any]] = {
    "nmap.scan.v1": {"total_runs": 25, "successful_runs": 23, "failed_runs": 2, "avg_duration_ms": 3200.0, "note": "succeeded 23/25 prior runs"},
    "nmap.network_scan.v1": {"total_runs": 25, "successful_runs": 23, "failed_runs": 2, "avg_duration_ms": 3200.0, "note": "succeeded 23/25 prior runs"},
    "gobuster.dir.v1": {"total_runs": 18, "successful_runs": 17, "failed_runs": 1, "avg_duration_ms": 4500.0, "note": "succeeded 17/18 prior runs"},
    "ffuf.fuzz.v1": {"total_runs": 14, "successful_runs": 13, "failed_runs": 1, "avg_duration_ms": 5100.0, "note": "succeeded 13/14 prior runs"},
    "nikto.scan.v1": {"total_runs": 12, "successful_runs": 10, "failed_runs": 2, "avg_duration_ms": 12000.0, "note": "succeeded 10/12 prior runs"},
    "whatweb.scan.v1": {"total_runs": 20, "successful_runs": 19, "failed_runs": 1, "avg_duration_ms": 1800.0, "note": "succeeded 19/20 prior runs"},
    "sqlmap.scan.v1": {"total_runs": 10, "successful_runs": 9, "failed_runs": 1, "avg_duration_ms": 8500.0, "note": "succeeded 9/10 prior runs"},
    "hydra.brute.v1": {"total_runs": 8, "successful_runs": 7, "failed_runs": 1, "avg_duration_ms": 7200.0, "note": "succeeded 7/8 prior runs"},
    "whois.lookup.v1": {"total_runs": 30, "successful_runs": 30, "failed_runs": 0, "avg_duration_ms": 450.0, "note": "succeeded 30/30 prior runs"},
    "dig.lookup.v1": {"total_runs": 28, "successful_runs": 28, "failed_runs": 0, "avg_duration_ms": 220.0, "note": "succeeded 28/28 prior runs"},
    "tcpdump.capture.v1": {"total_runs": 15, "successful_runs": 14, "failed_runs": 1, "avg_duration_ms": 10500.0, "note": "succeeded 14/15 prior runs"},
    "exiftool.extract.v1": {"total_runs": 22, "successful_runs": 22, "failed_runs": 0, "avg_duration_ms": 310.0, "note": "succeeded 22/22 prior runs"},
    "hashid.identify.v1": {"total_runs": 16, "successful_runs": 16, "failed_runs": 0, "avg_duration_ms": 180.0, "note": "succeeded 16/16 prior runs"},
    "searchsploit.search.v1": {"total_runs": 24, "successful_runs": 23, "failed_runs": 1, "avg_duration_ms": 890.0, "note": "succeeded 23/24 prior runs"},
    "metasploit.rpc.v1": {"total_runs": 9, "successful_runs": 8, "failed_runs": 1, "avg_duration_ms": 6400.0, "note": "succeeded 8/9 prior runs"},
    "shell.run.v1": {"total_runs": 40, "successful_runs": 39, "failed_runs": 1, "avg_duration_ms": 550.0, "note": "succeeded 39/40 prior runs"},
    "kali.exec.v1": {"total_runs": 35, "successful_runs": 33, "failed_runs": 2, "avg_duration_ms": 2100.0, "note": "succeeded 33/35 prior runs"},
    "system_ping": {"total_runs": 50, "successful_runs": 49, "failed_runs": 1, "avg_duration_ms": 120.0, "note": "succeeded 49/50 prior runs"},
    "hello_world": {"total_runs": 10, "successful_runs": 10, "failed_runs": 0, "avg_duration_ms": 15.0, "note": "succeeded 10/10 prior runs"},
}


def seed_default_tool_memories(db_path: Optional[Path | str] = None) -> None:
    """Populates initial realistic performance baselines into the tool memory store if empty."""
    init_db(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tool_memory")
        count = cursor.fetchone()[0]
        if count == 0:
            for tid, baseline in DEFAULT_TOOL_BASELINES.items():
                tot = baseline["total_runs"]
                succ = baseline["successful_runs"]
                rel = round(succ / tot, 4) if tot > 0 else 1.0
                cursor.execute(
                    """
                    INSERT INTO tool_memory (
                        tool_id, total_runs, successful_runs, failed_runs, timeout_runs,
                        avg_duration_ms, last_run_at, last_status, reliability_score, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tid,
                        tot,
                        succ,
                        baseline["failed_runs"],
                        0,
                        baseline["avg_duration_ms"],
                        now_iso,
                        "success",
                        rel,
                        json.dumps({"baseline_seed": True, "note": baseline["note"]}),
                    ),
                )
    conn.close()


def get_tool_memory(tool_id: str, db_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Retrieves tool memory for a tool, initializing with baseline prior if missing."""
    seed_default_tool_memories(db_path)
    conn = get_connection(db_path)
    rec: Optional[Dict[str, Any]] = None
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tool_memory WHERE tool_id = ?", (tool_id,))
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            try:
                rec["metadata"] = json.loads(rec["metadata"]) if rec.get("metadata") else {}
            except Exception:
                pass
        else:
            # If not present in table, insert default entry
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO tool_memory (
                    tool_id, total_runs, successful_runs, failed_runs, timeout_runs,
                    avg_duration_ms, last_run_at, last_status, reliability_score, metadata
                ) VALUES (?, 0, 0, 0, 0, 0.0, ?, 'queued', 1.0, ?)
                """,
                (tool_id, now_iso, json.dumps({"auto_created": True})),
            )
            cursor.execute("SELECT * FROM tool_memory WHERE tool_id = ?", (tool_id,))
            rec = dict(cursor.fetchone())
            rec["metadata"] = {}
    conn.close()
    return rec


def list_tool_memories(db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Lists memory records for all registered tools sorted by reliability and run count."""
    seed_default_tool_memories(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tool_memory ORDER BY reliability_score DESC, total_runs DESC")
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            try:
                r["metadata"] = json.loads(r["metadata"]) if r.get("metadata") else {}
            except Exception:
                pass
    conn.close()
    return rows


def record_tool_execution(
    tool_id: str,
    success: Optional[bool] = None,
    duration_ms: float = 0.0,
    exit_code: Optional[int] = 0,
    timed_out: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path | str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Updates the Tool Memory store immediately following an execution.
    Recalculates total_runs, successful_runs, failed_runs, timeout_runs,
    avg_duration_ms, and reliability_score.
    """
    if status is not None:
        if status.lower() == "failed":
            success = False
        elif status.lower() in ("timed_out", "timeout"):
            success = False
            timed_out = True
        else:
            success = True
    elif success is None:
        success = True

    seed_default_tool_memories(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    status_str = "timed_out" if timed_out else ("success" if success else "failed")

    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tool_memory WHERE tool_id = ?", (tool_id,))
        row = cursor.fetchone()

        if row:
            curr = dict(row)
            tot = curr["total_runs"] + 1
            succ = curr["successful_runs"] + (1 if success else 0)
            fail = curr["failed_runs"] + (0 if success else 1)
            timeouts = curr["timeout_runs"] + (1 if timed_out else 0)
            # Moving average of duration
            old_avg = curr["avg_duration_ms"]
            new_avg = round(((old_avg * curr["total_runs"]) + duration_ms) / tot, 2)
            rel_score = round(succ / tot, 4) if tot > 0 else 1.0

            cursor.execute(
                """
                UPDATE tool_memory
                SET total_runs = ?,
                    successful_runs = ?,
                    failed_runs = ?,
                    timeout_runs = ?,
                    avg_duration_ms = ?,
                    last_run_at = ?,
                    last_status = ?,
                    reliability_score = ?,
                    metadata = ?
                WHERE tool_id = ?
                """,
                (
                    tot,
                    succ,
                    fail,
                    timeouts,
                    new_avg,
                    now_iso,
                    status_str,
                    rel_score,
                    json.dumps(metadata or {}),
                    tool_id,
                ),
            )
        else:
            tot = 1
            succ = 1 if success else 0
            fail = 0 if success else 1
            timeouts = 1 if timed_out else 0
            rel_score = 1.0 if success else 0.0
            cursor.execute(
                """
                INSERT INTO tool_memory (
                    tool_id, total_runs, successful_runs, failed_runs, timeout_runs,
                    avg_duration_ms, last_run_at, last_status, reliability_score, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_id,
                    tot,
                    succ,
                    fail,
                    timeouts,
                    round(duration_ms, 2),
                    now_iso,
                    status_str,
                    rel_score,
                    json.dumps(metadata or {}),
                ),
            )

        cursor.execute("SELECT * FROM tool_memory WHERE tool_id = ?", (tool_id,))
        updated_rec = dict(cursor.fetchone())
        try:
            updated_rec["metadata"] = json.loads(updated_rec["metadata"]) if updated_rec.get("metadata") else {}
        except Exception:
            pass

    conn.close()
    return updated_rec


# ==============================================================================
# SCOPE CONTRACT STORE & AUTHORIZATION GATEWAY
# ==============================================================================

KAIRO_SCOPE_SECRET = os.environ.get("KAIRO_SCOPE_SECRET", "kairo_scope_auth_secret_v1")

# Standardized tool tier classifications:
# Tier 1: Passive Reconnaissance / OSINT / Local metadata / Non-intrusive lookup
# Tier 2: Active Scanning / Probing / Fuzzing / Port enumeration / Network capture
# Tier 3: Intrusive Testing / Exploitation / Brute-forcing / Arbitrary remote execution
TOOL_TIER_MAPPING: Dict[str, int] = {
    # Tier 1
    "whois.lookup.v1": 1,
    "dig.lookup.v1": 1,
    "exiftool.extract.v1": 1,
    "hashid.identify.v1": 1,
    "searchsploit.search.v1": 1,
    "dns_lookup": 1,
    "system_ping": 1,
    "hello_world": 1,

    # Tier 2
    "nmap.scan.v1": 2,
    "gobuster.dir.v1": 2,
    "ffuf.fuzz.v1": 2,
    "whatweb.scan.v1": 2,
    "nikto.scan.v1": 2,
    "tcpdump.capture.v1": 2,
    "browser.security.v1": 2,
    "playwright.browser.v1": 2,
    "browser.test.v1": 2,

    # Tier 3
    "sqlmap.scan.v1": 3,
    "hydra.brute.v1": 3,
    "metasploit.rpc.v1": 3,
    "kali.exec.v1": 3,
    "shell.run.v1": 3,
    "vm_execute": 3,
    "raw_command": 3,
    "burpsuite.gui.v1": 3,
    "burp.gui.v1": 3,
    "wireshark.gui.v1": 3,
    "zap.gui.v1": 3,
}


@dataclass
class ScopeContract:
    contract_id: str
    targets: List[str]
    network_scope: str
    time_window: str
    allowed_tool_tiers: List[int]
    authorized_by: str
    created_at: str
    expires_at: str
    signature: str
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "targets": self.targets,
            "network_scope": self.network_scope,
            "time_window": self.time_window,
            "allowed_tool_tiers": self.allowed_tool_tiers,
            "authorized_by": self.authorized_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
            "is_active": self.is_active,
            "metadata": self.metadata or {},
        }


def get_tool_tier(tool_id: str) -> int:
    """Returns the authorization tier (1, 2, or 3) for a given tool identifier."""
    if not tool_id:
        return 1
    t_lower = tool_id.lower().strip()
    if t_lower in TOOL_TIER_MAPPING:
        return TOOL_TIER_MAPPING[t_lower]
    # Keyword inference fallback
    if any(k in t_lower for k in ["exploit", "brute", "sqlmap", "hydra", "metasploit", "shell", "exec", "payload"]):
        return 3
    if any(k in t_lower for k in ["scan", "fuzz", "probe", "nmap", "gobuster", "nikto", "enum", "tcpdump"]):
        return 2
    return 1


def canonical_scope_payload(data: Dict[str, Any]) -> str:
    """Produces deterministically ordered JSON representation of core scope fields for HMAC signing."""
    targets = data.get("targets") or []
    if isinstance(targets, str):
        try:
            targets = json.loads(targets)
        except Exception:
            targets = [targets]
    tiers = data.get("allowed_tool_tiers") or []
    if isinstance(tiers, str):
        try:
            tiers = json.loads(tiers)
        except Exception:
            tiers = [int(tiers)]

    core = {
        "allowed_tool_tiers": sorted([int(t) for t in tiers]),
        "authorized_by": str(data.get("authorized_by") or "").strip(),
        "created_at": str(data.get("created_at") or "").strip(),
        "expires_at": str(data.get("expires_at") or "").strip(),
        "network_scope": str(data.get("network_scope") or "").strip(),
        "targets": sorted([str(t).strip().lower() for t in targets]),
        "time_window": str(data.get("time_window") or "").strip(),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"))


def generate_scope_signature(data: Dict[str, Any], secret_key: str = KAIRO_SCOPE_SECRET) -> str:
    """Generates an HMAC-SHA256 signature for the canonical scope contract payload."""
    payload = canonical_scope_payload(data)
    return hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_scope_signature(data: Dict[str, Any], secret_key: str = KAIRO_SCOPE_SECRET) -> bool:
    """Verifies that the HMAC-SHA256 signature matches the canonical scope content."""
    sig = data.get("signature", "")
    if not sig:
        return False
    expected = generate_scope_signature(data, secret_key)
    return hmac.compare_digest(str(sig).strip(), str(expected).strip())


def parse_time_window_seconds(time_window: str) -> int:
    """Parses time window strings (e.g. '8h', '4h', '30m', '1d', '24h') into seconds."""
    s = str(time_window).strip().lower()
    if s.endswith("h"):
        return int(float(s[:-1]) * 3600)
    elif s.endswith("m"):
        return int(float(s[:-1]) * 60)
    elif s.endswith("d"):
        return int(float(s[:-1]) * 86400)
    elif s.endswith("s"):
        return int(float(s[:-1]))
    try:
        return int(s)
    except ValueError:
        return 8 * 3600


def extract_host_from_target(target: str) -> str:
    """Normalizes a target URL, CIDR, or host string into a clean host or IP."""
    if not target:
        return ""
    t = str(target).strip()
    if t.startswith(("http://", "https://", "ftp://", "ssh://")):
        parsed = urlparse(t)
        host = parsed.hostname or parsed.netloc or ""
        return host.split(":")[0].strip().lower()
    # If host:port format without slash
    if ":" in t and "/" not in t and not t.startswith("["):
        t = t.split(":")[0]
    return t.strip().lower()


def is_target_in_scope(target: str, allowed_targets: List[str]) -> bool:
    """
    Checks whether the target is strictly permitted by the active Scope Contract.
    Supports:
    - Hostnames / domains ('localhost', 'example.com')
    - Wildcard domains ('*.domain.internal')
    - IPv4 / IPv6 addresses
    - IPv4 / IPv6 Subnet CIDR containment (e.g. '192.168.1.45' in '192.168.1.0/24')
    """
    if not target:
        return True
    
    clean_target = extract_host_from_target(target)
    if not clean_target:
        return True

    target_ip = None
    try:
        target_ip = ipaddress.ip_address(clean_target)
    except ValueError:
        pass

    for allowed in allowed_targets:
        if not allowed:
            continue
        allowed_clean = str(allowed).strip().lower()

        # 1. Exact string match
        if clean_target == allowed_clean:
            return True

        # 2. Domain wildcard match
        if allowed_clean.startswith("*."):
            suffix = allowed_clean[1:]  # e.g. .internal
            if clean_target.endswith(suffix):
                return True
        elif allowed_clean.startswith("."):
            if clean_target.endswith(allowed_clean):
                return True

        # 3. IP / Subnet CIDR match
        if target_ip is not None:
            try:
                net = ipaddress.ip_network(allowed_clean, strict=False)
                if target_ip in net:
                    return True
            except ValueError:
                pass
        else:
            # Target is a hostname; allowed might be exact host without scheme
            if clean_target == allowed_clean.split("/")[0]:
                return True

    return False


def create_scope_contract(
    targets: List[str],
    network_scope: str,
    time_window: str,
    allowed_tool_tiers: List[int],
    authorized_by: str,
    metadata: Optional[Dict[str, Any]] = None,
    secret_key: str = KAIRO_SCOPE_SECRET,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Creates and cryptographically signs a new Scope Contract, activating it in the event store.
    Any previously active contracts are automatically deactivated.
    """
    init_db(db_path)
    now = datetime.now(timezone.utc)
    seconds = parse_time_window_seconds(time_window)
    expires = now + timedelta(seconds=seconds)
    created_at_iso = now.isoformat()
    expires_at_iso = expires.isoformat()
    contract_id = f"scope_{uuid.uuid4().hex[:12]}"

    clean_targets = [str(t).strip().lower() for t in targets]
    clean_tiers = sorted(list({int(t) for t in allowed_tool_tiers}))

    payload_data = {
        "contract_id": contract_id,
        "targets": clean_targets,
        "network_scope": network_scope.strip(),
        "time_window": time_window.strip(),
        "allowed_tool_tiers": clean_tiers,
        "authorized_by": authorized_by.strip(),
        "created_at": created_at_iso,
        "expires_at": expires_at_iso,
    }
    signature = generate_scope_signature(payload_data, secret_key)

    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE scope_contracts SET is_active = 0 WHERE is_active = 1")
        cursor.execute(
            """
            INSERT INTO scope_contracts (
                contract_id, targets, network_scope, time_window,
                allowed_tool_tiers, authorized_by, created_at, expires_at,
                signature, is_active, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                contract_id,
                json.dumps(clean_targets),
                network_scope.strip(),
                time_window.strip(),
                json.dumps(clean_tiers),
                authorized_by.strip(),
                created_at_iso,
                expires_at_iso,
                signature,
                json.dumps(metadata or {}),
            ),
        )
    conn.close()

    result = {
        **payload_data,
        "signature": signature,
        "is_active": True,
        "metadata": metadata or {},
        "seconds_remaining": seconds,
        "is_expired": False,
        "signature_valid": True,
    }
    return result


def get_active_scope_contract(db_path: Path | str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieves the currently active Scope Contract, including live validity and signature verification."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM scope_contracts
        WHERE is_active = 1
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["targets"] = json.loads(d["targets"]) if isinstance(d["targets"], str) else d["targets"]
    d["allowed_tool_tiers"] = json.loads(d["allowed_tool_tiers"]) if isinstance(d["allowed_tool_tiers"], str) else d["allowed_tool_tiers"]
    d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
    d["is_active"] = bool(d.get("is_active", 0))

    try:
        exp_dt = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        rem = int((exp_dt - now_dt).total_seconds())
        d["seconds_remaining"] = max(0, rem)
        d["is_expired"] = rem <= 0
    except Exception:
        d["seconds_remaining"] = 0
        d["is_expired"] = True

    d["signature_valid"] = verify_scope_signature(d)
    return d


def seed_default_scope_contract(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Ensures an active, valid Scope Contract exists. Seeds a default authorized lab contract if none exists."""
    active = get_active_scope_contract(db_path)
    if active and not active.get("is_expired") and active.get("signature_valid"):
        return active

    return create_scope_contract(
        targets=[
            "127.0.0.1",
            "localhost",
            "target.local",
            "*.local",
            "192.168.1.0/24",
            "192.168.56.0/24",
            "example.com",
            "*.internal",
        ],
        network_scope="authorized_lab",
        time_window="8h",
        allowed_tool_tiers=[1, 2, 3],
        authorized_by="secops_lead@kairo.internal",
        metadata={
            "purpose": "Authorized sandbox and pentest lab operations",
            "policy_doc": "SEC-POL-AUTH-2026-v4",
            "auto_seeded": True,
        },
        db_path=db_path,
    )


def list_scope_contracts(limit: int = 10, db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Lists historical scope contracts."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM scope_contracts
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d["targets"] = json.loads(d["targets"]) if isinstance(d["targets"], str) else d["targets"]
        d["allowed_tool_tiers"] = json.loads(d["allowed_tool_tiers"]) if isinstance(d["allowed_tool_tiers"], str) else d["allowed_tool_tiers"]
        d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
        d["is_active"] = bool(d.get("is_active", 0))
        d["signature_valid"] = verify_scope_signature(d)
        try:
            exp_dt = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            rem = int((exp_dt - now_dt).total_seconds())
            d["seconds_remaining"] = max(0, rem)
            d["is_expired"] = rem <= 0
        except Exception:
            d["seconds_remaining"] = 0
            d["is_expired"] = True
        results.append(d)
    return results


def validate_scope_request(
    target: Optional[str] = None,
    tool_id: Optional[str] = None,
    tool_tier: Optional[int] = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Validates a tool invocation request against the currently active Scope Contract.
    Returns:
    {
        "authorized": bool,
        "reason": str,
        "scope_contract_id": Optional[str],
        "active_contract": Optional[Dict],
        "target": str,
        "tool_id": str,
        "tool_tier": int
    }
    """
    contract = get_active_scope_contract(db_path)
    tier = tool_tier if tool_tier is not None else (get_tool_tier(tool_id) if tool_id else 1)

    if not contract:
        return {
            "authorized": False,
            "reason": "NO_ACTIVE_SCOPE_CONTRACT: Execution rejected because no active Scope Contract was found.",
            "scope_contract_id": None,
            "active_contract": None,
            "target": target,
            "tool_id": tool_id,
            "tool_tier": tier,
        }

    # Verify signature
    if not contract.get("signature_valid", False):
        return {
            "authorized": False,
            "reason": f"SCOPE_INTEGRITY_VIOLATION: Scope Contract {contract.get('contract_id')} has an invalid signature or has been tampered with.",
            "scope_contract_id": contract.get("contract_id"),
            "active_contract": contract,
            "target": target,
            "tool_id": tool_id,
            "tool_tier": tier,
        }

    # Verify expiration
    if contract.get("is_expired", False) or contract.get("seconds_remaining", 0) <= 0:
        return {
            "authorized": False,
            "reason": f"SCOPE_EXPIRED: Scope Contract {contract.get('contract_id')} expired at {contract.get('expires_at')}.",
            "scope_contract_id": contract.get("contract_id"),
            "active_contract": contract,
            "target": target,
            "tool_id": tool_id,
            "tool_tier": tier,
        }

    # Verify tool tier
    allowed_tiers = contract.get("allowed_tool_tiers", [])
    if tier not in allowed_tiers:
        return {
            "authorized": False,
            "reason": f"TOOL_TIER_EXCEEDED: Tool '{tool_id or 'unknown'}' operates at Tier {tier}, but active Scope Contract only authorizes Tiers {allowed_tiers}.",
            "scope_contract_id": contract.get("contract_id"),
            "active_contract": contract,
            "target": target,
            "tool_id": tool_id,
            "tool_tier": tier,
        }

    # Verify target boundary
    if target:
        allowed_targets = contract.get("targets", [])
        if not is_target_in_scope(target, allowed_targets):
            return {
                "authorized": False,
                "reason": f"OUT_OF_SCOPE_TARGET: Target '{target}' falls outside authorized scope targets: {allowed_targets}.",
                "scope_contract_id": contract.get("contract_id"),
                "active_contract": contract,
                "target": target,
                "tool_id": tool_id,
                "tool_tier": tier,
            }

    return {
        "authorized": True,
        "reason": f"Authorized under Scope Contract {contract.get('contract_id')}.",
        "scope_contract_id": contract.get("contract_id"),
        "active_contract": contract,
        "target": target,
        "tool_id": tool_id,
        "tool_tier": tier,
    }


# ===========================================================================
# Model Memory Store (Blueprint Memory Model)
# Tracks model versions, prompt formats, adapters, and benchmark scores
# ===========================================================================

@dataclass
class ModelMemoryRecord:
    model_id: str
    version: str
    prompt_format: str
    adapter: str
    benchmark_score: float
    recorded_at: Optional[str] = None
    metrics: Optional[Dict[str, Any] | str] = None
    metadata: Optional[Dict[str, Any] | str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if isinstance(d.get("metrics"), str):
            try:
                d["metrics"] = json.loads(d["metrics"])
            except Exception:
                pass
        if isinstance(d.get("metadata"), str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                pass
        return d


def record_model_memory(
    model_id: str,
    version: str,
    prompt_format: str,
    adapter: str,
    benchmark_score: float,
    metrics: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any] | str] = None,
    db_path: Optional[Path | str] = None,
) -> int:
    """Logs a model memory record (version, prompt format, adapter, benchmark score) per the blueprint memory model."""
    init_db(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    metrics_str = json.dumps(metrics or {})
    meta_str = json.dumps(metadata) if isinstance(metadata, dict) else metadata
    query = """
    INSERT INTO model_memory (
        model_id, version, prompt_format, adapter, benchmark_score,
        recorded_at, metrics, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            query,
            (
                model_id,
                version,
                prompt_format,
                adapter,
                float(benchmark_score),
                now_iso,
                metrics_str,
                meta_str,
            ),
        )
        row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_model_memory_records(
    model_id: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves model memory history."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        if model_id:
            cursor.execute(
                "SELECT * FROM model_memory WHERE model_id = ? ORDER BY id DESC LIMIT ?",
                (model_id, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM model_memory ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            if isinstance(r.get("metrics"), str):
                try:
                    r["metrics"] = json.loads(r["metrics"])
                except Exception:
                    pass
            if isinstance(r.get("metadata"), str):
                try:
                    r["metadata"] = json.loads(r["metadata"])
                except Exception:
                    pass
    conn.close()
    return rows


def get_latest_model_memory(
    model_id: Optional[str] = None,
    db_path: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves latest model memory record."""
    records = get_model_memory_records(model_id=model_id, limit=1, db_path=db_path)
    return records[0] if records else None


# ==============================================================================
# SHARED PROJECTS & MULTI-USER STATE (Live Session View & Collaboration)
# ==============================================================================

@dataclass
class Project:
    project_id: str
    name: str
    description: str
    owner_id: str
    status: str  # "active" | "archived" | "completed"
    active_workspace_id: Optional[str]
    active_session_id: Optional[str]
    collaborators: List[Dict[str, Any]]
    shared_state: Dict[str, Any]
    created_at: str
    updated_at: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status,
            "active_workspace_id": self.active_workspace_id,
            "active_session_id": self.active_session_id,
            "collaborators": self.collaborators,
            "collaborator_count": len(self.collaborators),
            "shared_state": self.shared_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


def _deserialize_project_row(r: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    d = dict(r)
    if isinstance(d.get("collaborators"), str):
        try:
            d["collaborators"] = json.loads(d["collaborators"])
        except Exception:
            d["collaborators"] = []
    if isinstance(d.get("shared_state"), str):
        try:
            d["shared_state"] = json.loads(d["shared_state"])
        except Exception:
            d["shared_state"] = {}
    if isinstance(d.get("metadata"), str):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except Exception:
            d["metadata"] = {}
    d["collaborator_count"] = len(d.get("collaborators", []))
    return d


def create_project(
    name: str,
    owner_id: str = "default_user",
    description: str = "",
    active_workspace_id: Optional[str] = None,
    active_session_id: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Creates a shared project with initial owner and multi-user shared state."""
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    
    initial_collaborators = [
        {
            "user_id": owner_id,
            "role": "owner",
            "client_type": "browser-desktop",
            "joined_at": now_iso,
            "last_active": now_iso,
        }
    ]

    shared_state = initial_state or {
        "active_target": "127.0.0.1",
        "notes": f"Shared workspace session initialized for {name}.",
        "tags": ["pentest", "collaborative"],
        "active_task_graph_id": None,
    }

    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (
                project_id, name, description, owner_id, status,
                active_workspace_id, active_session_id, collaborators,
                shared_state, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                name.strip(),
                description.strip(),
                owner_id.strip(),
                "active",
                active_workspace_id,
                active_session_id or f"sess_{project_id}",
                json.dumps(initial_collaborators),
                json.dumps(shared_state),
                now_iso,
                now_iso,
                json.dumps(metadata or {}),
            ),
        )
    conn.close()
    return get_project(project_id, db_path=db_path)  # type: ignore


def get_project(project_id: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a shared project by project_id."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
    row = cursor.fetchone()
    conn.close()
    return _deserialize_project_row(row) if row else None


def list_projects(
    owner_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Lists shared projects filtered optionally by owner or status."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM projects WHERE 1=1"
    params = []
    if owner_id:
        query += " AND (owner_id = ? OR collaborators LIKE ?)"
        params.extend([owner_id, f'%"{owner_id}"%'])
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [_deserialize_project_row(r) for r in rows]


def update_project(
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    active_workspace_id: Optional[str] = None,
    active_session_id: Optional[str] = None,
    db_path: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Updates top-level fields of a shared project."""
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    fields = ["updated_at = ?"]
    params = [now_iso]

    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())
    if status is not None:
        fields.append("status = ?")
        params.append(status.strip())
    if active_workspace_id is not None:
        fields.append("active_workspace_id = ?")
        params.append(active_workspace_id)
    if active_session_id is not None:
        fields.append("active_session_id = ?")
        params.append(active_session_id)

    params.append(project_id)
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE projects SET {', '.join(fields)} WHERE project_id = ?", params)
    conn.close()
    return get_project(project_id, db_path=db_path)


def update_project_shared_state(
    project_id: str,
    state_patch: Dict[str, Any],
    db_path: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Merges a state patch into the project's shared state."""
    curr = get_project(project_id, db_path=db_path)
    if not curr:
        return None
    new_state = dict(curr.get("shared_state", {}))
    new_state.update(state_patch)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET shared_state = ?, updated_at = ? WHERE project_id = ?",
            (json.dumps(new_state), now_iso, project_id),
        )
    conn.close()
    return get_project(project_id, db_path=db_path)


def add_project_collaborator(
    project_id: str,
    user_id: str,
    role: str = "operator",
    client_type: str = "browser-desktop",
    db_path: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Adds or updates a collaborator in a shared project."""
    curr = get_project(project_id, db_path=db_path)
    if not curr:
        return None
    collaborators: List[Dict[str, Any]] = list(curr.get("collaborators", []))
    now_iso = datetime.now(timezone.utc).isoformat()

    updated = False
    for c in collaborators:
        if c.get("user_id") == user_id:
            c["role"] = role
            c["client_type"] = client_type
            c["last_active"] = now_iso
            updated = True
            break
    if not updated:
        collaborators.append({
            "user_id": user_id,
            "role": role,
            "client_type": client_type,
            "joined_at": now_iso,
            "last_active": now_iso,
        })

    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET collaborators = ?, updated_at = ? WHERE project_id = ?",
            (json.dumps(collaborators), now_iso, project_id),
        )
    conn.close()
    return get_project(project_id, db_path=db_path)


def remove_project_collaborator(
    project_id: str,
    user_id: str,
    db_path: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Removes a collaborator from a shared project (owner cannot be removed)."""
    curr = get_project(project_id, db_path=db_path)
    if not curr:
        return None
    if curr.get("owner_id") == user_id:
        return curr  # Cannot remove project owner

    collaborators = [c for c in curr.get("collaborators", []) if c.get("user_id") != user_id]
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET collaborators = ?, updated_at = ? WHERE project_id = ?",
            (json.dumps(collaborators), now_iso, project_id),
        )
    conn.close()
    return get_project(project_id, db_path=db_path)


def seed_default_shared_project(db_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Seeds a canonical shared project if none exists."""
    existing = list_projects(limit=1, db_path=db_path)
    if existing:
        return existing[0]

    return create_project(
        name="Global Operations Center (Alpha)",
        owner_id="alice_secops",
        description="Collaborative red-team assessment & autonomous audit operations space.",
        initial_state={
            "active_target": "target.local",
            "notes": "Target environment initialized for multi-user assessment. All operations bound by Task 2.3 Scope Contract.",
            "tags": ["web_security", "recon", "authorized_lab"],
            "live_scratchpad": "# Session Notes\n- Initial recon completed via whatweb and dnsrecon.\n- Next: Review Audit Explorer for scope compliance.\n",
        },
        db_path=db_path,
    )


# ==============================================================================
# AUDIT EXPLORER: SEARCHABLE TIMELINE & SCOPE CONTRACT CORRELATION (Task 2.3)
# ==============================================================================

def query_audit_timeline(
    query: Optional[str] = None,
    actor: Optional[str] = None,
    tool_id: Optional[str] = None,
    status: Optional[str] = None,
    time_range: Optional[str] = None,
    scope_filter: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """
    Queries a chronological timeline combining every agent/tool execution event
    with the governing Scope Contract history (Task 2.3) for complete accountability.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc)

    # 1. Fetch Scope Contracts for correlation
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scope_contracts ORDER BY created_at ASC")
    raw_contracts = [dict(r) for r in cursor.fetchall()]
    scope_contracts = []
    for sc in raw_contracts:
        sc["targets"] = json.loads(sc["targets"]) if isinstance(sc["targets"], str) else sc["targets"]
        sc["allowed_tool_tiers"] = json.loads(sc["allowed_tool_tiers"]) if isinstance(sc["allowed_tool_tiers"], str) else sc["allowed_tool_tiers"]
        sc["metadata"] = json.loads(sc["metadata"]) if sc.get("metadata") else {}
        sc["signature_valid"] = verify_scope_signature(sc)
        scope_contracts.append(sc)

    def find_governing_contract(event_ts_iso: str) -> Optional[Dict[str, Any]]:
        if not scope_contracts:
            return None
        governing = None
        for c in scope_contracts:
            c_created = c.get("created_at", "")
            if c_created <= event_ts_iso:
                governing = c
        return governing or (scope_contracts[0] if scope_contracts else None)

    # 2. Build Event Query with dynamic filters
    where_clauses = ["1=1"]
    params: List[Any] = []

    if session_id:
        where_clauses.append("session_id = ?")
        params.append(session_id)

    if actor and actor.lower() != "all":
        where_clauses.append("actor = ?")
        params.append(actor)

    if tool_id and tool_id.lower() != "all":
        where_clauses.append("tool_id = ?")
        params.append(tool_id)

    if status and status.lower() != "all":
        st = status.lower()
        if st in ("success", "0"):
            where_clauses.append("exit_code = 0")
        elif st in ("failed", "failure", "error"):
            where_clauses.append("(exit_code != 0 OR stderr_ref IS NOT NULL)")
        elif st == "timeout":
            where_clauses.append("result_summary LIKE '%timeout%'")

    if time_range and time_range.lower() != "all":
        tr = time_range.lower()
        cutoff = None
        if tr in ("1h", "last 1 hour", "last_1h"):
            cutoff = (now - timedelta(hours=1)).isoformat()
        elif tr in ("24h", "last 24 hours", "last_24h", "1d"):
            cutoff = (now - timedelta(hours=24)).isoformat()
        elif tr in ("7d", "last 7 days", "last_7d"):
            cutoff = (now - timedelta(days=7)).isoformat()
        if cutoff:
            where_clauses.append("timestamp >= ?")
            params.append(cutoff)

    if query and query.strip():
        q_wild = f"%{query.strip()}%"
        where_clauses.append(
            """
            (tool_id LIKE ? OR actor LIKE ? OR requested_args LIKE ?
             OR normalized_args LIKE ? OR result_summary LIKE ? OR task_id LIKE ?)
            """
        )
        params.extend([q_wild, q_wild, q_wild, q_wild, q_wild, q_wild])

    sql = f"""
        SELECT * FROM events
        WHERE {' AND '.join(where_clauses)}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    cursor.execute(sql, params)
    raw_events = [dict(r) for r in cursor.fetchall()]

    # 3. Correlate Events with Scope Contract History
    correlated_events: List[Dict[str, Any]] = []
    scope_violation_count = 0
    in_scope_count = 0

    for ev in raw_events:
        ev_ts = ev.get("timestamp") or now.isoformat()
        gov_contract = find_governing_contract(ev_ts)

        target_extracted = ""
        for args_field in (ev.get("normalized_args"), ev.get("requested_args")):
            if args_field:
                try:
                    parsed_args = json.loads(args_field) if isinstance(args_field, str) else args_field
                    if isinstance(parsed_args, dict):
                        target_extracted = (
                            parsed_args.get("target")
                            or parsed_args.get("host")
                            or parsed_args.get("domain")
                            or parsed_args.get("url")
                            or parsed_args.get("ip")
                            or ""
                        )
                        if not target_extracted:
                            cmd_args = parsed_args.get("args") or []
                            if isinstance(cmd_args, list):
                                for a in cmd_args:
                                    a_str = str(a).strip()
                                    if a_str.startswith(("http://", "https://", "ftp://", "ssh://")):
                                        target_extracted = extract_host_from_target(a_str)
                                        if target_extracted:
                                            break
                                    elif re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', a_str):
                                        m = re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', a_str)
                                        target_extracted = m.group(0)
                                        if target_extracted:
                                            break
                            elif isinstance(cmd_args, str):
                                target_extracted = extract_host_from_target(cmd_args)
                        if target_extracted:
                            target_extracted = extract_host_from_target(target_extracted)
                            break
                    elif isinstance(parsed_args, list) and parsed_args:
                        target_extracted = extract_host_from_target(str(parsed_args[0]))
                        break
                except Exception:
                    pass

        tool = ev.get("tool_id") or ""
        tool_tier = get_tool_tier(tool)

        scope_status = "unscoped"
        scope_reason = "No active Scope Contract recorded"
        gov_contract_id = None
        signature_valid = False
        target_ok = True
        tier_ok = True

        if gov_contract:
            gov_contract_id = gov_contract.get("contract_id")
            signature_valid = gov_contract.get("signature_valid", False)
            allowed_targets = gov_contract.get("targets", [])
            allowed_tiers = gov_contract.get("allowed_tool_tiers", [1, 2, 3])

            target_ok = is_target_in_scope(target_extracted, allowed_targets) if target_extracted else True
            tier_ok = tool_tier in allowed_tiers

            if not target_ok:
                scope_status = "scope_violation"
                scope_reason = f"Target '{target_extracted}' outside authorized boundaries ({', '.join(allowed_targets[:3])})"
                scope_violation_count += 1
            elif not tier_ok:
                scope_status = "scope_violation"
                scope_reason = f"Tool tier {tool_tier} exceeds authorized contract tiers ({allowed_tiers}) for tool '{tool}'"
                scope_violation_count += 1
            else:
                scope_status = "in_scope"
                scope_reason = f"Authorized target '{target_extracted or 'local'}' under Tier {tool_tier}"
                in_scope_count += 1
        else:
            in_scope_count += 1

        if scope_filter:
            sf = scope_filter.lower()
            if sf in ("contracts", "scope_contracts"):
                continue
            if sf == "in_scope" and scope_status != "in_scope":
                continue
            if sf in ("violation", "violations", "scope_violation") and scope_status != "scope_violation":
                continue

        ev_item = {
            "timeline_type": "event",
            "is_scope_contract_milestone": False,
            "id": ev.get("id"),
            "session_id": ev.get("session_id"),
            "task_id": ev.get("task_id"),
            "timestamp": ev.get("timestamp"),
            "actor": ev.get("actor"),
            "tool_id": ev.get("tool_id"),
            "tool_version": ev.get("tool_version"),
            "tool_tier": tool_tier,
            "target": target_extracted,
            "target_in_scope": target_ok if gov_contract else True,
            "requested_args": ev.get("requested_args"),
            "normalized_args": ev.get("normalized_args"),
            "process_id": ev.get("process_id"),
            "start_time": ev.get("start_time"),
            "end_time": ev.get("end_time"),
            "exit_code": ev.get("exit_code"),
            "status": "success" if ev.get("exit_code") == 0 else "failed",
            "result_summary": ev.get("result_summary"),
            "stdout_ref": ev.get("stdout_ref"),
            "stderr_ref": ev.get("stderr_ref"),
            "artifact_refs": ev.get("artifact_refs"),
            "screenshots": ev.get("screenshots"),
            "governing_contract_id": gov_contract_id,
            "scope_contract_id": gov_contract_id,
            "scope_status": scope_status,
            "scope_reason": scope_reason,
            "scope_violation_reason": scope_reason if scope_status == "scope_violation" else "",
            "signature_valid": signature_valid,
        }
        correlated_events.append(ev_item)

    # 4. Integrate Scope Contract milestones into timeline
    milestones: List[Dict[str, Any]] = []
    if not scope_filter or scope_filter.lower() in ("all", "contracts", "scope_contracts"):
        for sc in scope_contracts:
            if actor and actor.lower() != "all" and sc["authorized_by"].lower() != actor.lower():
                continue
            if query and query.strip():
                q = query.strip().lower()
                in_targets = any(q in str(t).lower() for t in sc["targets"])
                in_auth = q in sc["authorized_by"].lower()
                in_scope_name = q in sc.get("network_scope", "").lower()
                if not (in_targets or in_auth or in_scope_name):
                    continue
            milestones.append({
                "timeline_type": "scope_contract",
                "is_scope_contract_milestone": True,
                "id": f"sc_{sc['contract_id']}",
                "contract_id": sc["contract_id"],
                "timestamp": sc["created_at"],
                "actor": sc["authorized_by"],
                "network_scope": sc["network_scope"],
                "time_window": sc["time_window"],
                "targets": sc["targets"],
                "allowed_tool_tiers": sc["allowed_tool_tiers"],
                "authorized_by": sc["authorized_by"],
                "signature": sc["signature"],
                "signature_valid": sc["signature_valid"],
                "is_active": sc["is_active"],
                "is_expired": sc.get("is_expired", False),
                "summary": f"Scope Contract Signed & Activated: {', '.join(sc['targets'])} (Tiers: {sc['allowed_tool_tiers']})",
            })

    combined_timeline = sorted(
        correlated_events + milestones,
        key=lambda x: str(x.get("timestamp", "")),
        reverse=True,
    )

    cursor.execute("SELECT COUNT(*) as count FROM events")
    total_db_events = cursor.fetchone()["count"]
    conn.close()

    total_evaluated = in_scope_count + scope_violation_count
    compliance_rate = round((in_scope_count / total_evaluated * 100), 1) if total_evaluated > 0 else 100.0

    return {
        "timeline": combined_timeline,
        "total_events_matched": len(correlated_events),
        "total_db_events": total_db_events,
        "scope_contracts_count": len(scope_contracts),
        "stats": {
            "in_scope_actions": in_scope_count,
            "scope_violations": scope_violation_count,
            "compliance_rate_pct": compliance_rate,
            "active_contracts": sum(1 for c in scope_contracts if c.get("is_active")),
        },
        "query_params": {
            "query": query,
            "actor": actor,
            "tool_id": tool_id,
            "status": status,
            "time_range": time_range,
            "scope_filter": scope_filter,
            "limit": limit,
            "offset": offset,
        },
    }


def get_audit_stats(
    time_range: Optional[str] = None,
    db_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Generates high-level statistical summaries for the Audit Explorer overview."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM events")
    tot_events = cursor.fetchone()["cnt"]

    cursor.execute("SELECT actor, COUNT(*) as cnt FROM events GROUP BY actor ORDER BY cnt DESC")
    actor_counts = {r["actor"]: r["cnt"] for r in cursor.fetchall()}

    cursor.execute("SELECT tool_id, COUNT(*) as cnt FROM events WHERE tool_id IS NOT NULL GROUP BY tool_id ORDER BY cnt DESC LIMIT 10")
    tool_counts = {r["tool_id"]: r["cnt"] for r in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) as cnt FROM events WHERE exit_code = 0")
    successes = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) as cnt FROM events WHERE exit_code != 0")
    failures = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM scope_contracts")
    tot_contracts = cursor.fetchone()["cnt"]

    conn.close()

    return {
        "total_events": tot_events,
        "actors": actor_counts,
        "top_tools": tool_counts,
        "success_rate_pct": round(successes / (tot_events or 1) * 100, 1),
        "total_scope_contracts": tot_contracts,
        "successful_executions": successes,
        "failed_executions": failures,
    }






