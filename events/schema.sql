-- SQLite schema for the Event Store
-- Conforms strictly to the required Event specification

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    tool_id TEXT,
    tool_version TEXT,
    requested_args TEXT,
    normalized_args TEXT,
    process_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    exit_code INTEGER,
    stdout_ref TEXT,
    stderr_ref TEXT,
    artifact_refs TEXT,
    screenshots TEXT,
    network_context TEXT,
    result_summary TEXT,
    confidence REAL,
    parent_event TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);

CREATE TABLE IF NOT EXISTS task_graphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT UNIQUE NOT NULL,
    session_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_graphs_plan_id ON task_graphs(plan_id);
CREATE INDEX IF NOT EXISTS idx_task_graphs_session_id ON task_graphs(session_id);

CREATE TABLE IF NOT EXISTS task_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT,
    dependencies TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TEXT,
    completed_at TEXT,
    result TEXT,
    assigned_tool TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(plan_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_task_nodes_plan_id ON task_nodes(plan_id);
CREATE INDEX IF NOT EXISTS idx_task_nodes_status ON task_nodes(status);

-- Tool Memory Store: Global system state tracking historical reliability and performance per tool
CREATE TABLE IF NOT EXISTS tool_memory (
    tool_id TEXT PRIMARY KEY,
    total_runs INTEGER NOT NULL DEFAULT 0,
    successful_runs INTEGER NOT NULL DEFAULT 0,
    failed_runs INTEGER NOT NULL DEFAULT 0,
    timeout_runs INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms REAL NOT NULL DEFAULT 0.0,
    last_run_at TEXT,
    last_status TEXT,
    reliability_score REAL NOT NULL DEFAULT 1.0,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_memory_reliability ON tool_memory(reliability_score);


