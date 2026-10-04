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
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def init_db(db_path: Optional[Path | str] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.close()


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



