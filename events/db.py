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

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "events.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


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
