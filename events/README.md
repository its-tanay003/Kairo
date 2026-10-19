# /events - Immutable Operational Audit Event Store

The `/events` subsystem provides immutable forensic logging and audit persistence for all actions executed by Kairo. Backed by **SQLite 3** (`events/events.db`), every tool execution, planner step, cognitive evaluation, and error recovery is recorded conforming to a strict **20-field audit schema**.

---

## The 20-Field Audit Schema

Defined in [`schema.sql`](schema.sql) and implemented in [`db.py`](db.py):

| # | Field Name | Data Type | Constraint | Description |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `session_id` | `TEXT` | `NOT NULL` | Unique identifier for the user session or campaign. |
| 2 | `task_id` | `TEXT` | `NOT NULL` | Unique identifier for the discrete unit of execution. |
| 3 | `timestamp` | `TEXT` | `NOT NULL` | UTC ISO-8601 creation timestamp. |
| 4 | `actor` | `TEXT` | `NOT NULL` | Initiator: `user`, `orchestrator`, `agent`, or `recovery_agent`. |
| 5 | `tool_id` | `TEXT` | Nullable | ToolSpec identifier (e.g. `nmap.scan.v1`, `shell.run.v1`). |
| 6 | `tool_version` | `TEXT` | Nullable | Semantic version of the tool invoked (e.g. `1.0.0`). |
| 7 | `requested_args` | `TEXT` | Nullable | Raw input arguments received from operator or LLM. |
| 8 | `normalized_args` | `TEXT` | Nullable | Sanitized, validated arguments compiled by the adapter. |
| 9 | `process_id` | `INTEGER` | Nullable | OS PID assigned by the Process Supervisor or VM worker. |
| 10 | `start_time` | `TEXT` | Nullable | UTC execution start timestamp. |
| 11 | `end_time` | `TEXT` | Nullable | UTC execution completion timestamp. |
| 12 | `exit_code` | `INTEGER` | Nullable | Return code ($0$ for success, non-zero for failure). |
| 13 | `stdout_ref` | `TEXT` | Nullable | File URI or pointer to full captured stdout. |
| 14 | `stderr_ref` | `TEXT` | Nullable | File URI or pointer to captured stderr. |
| 15 | `artifact_refs` | `TEXT` | Nullable | JSON array of produced artifact paths (dumps, reports, logs). |
| 16 | `screenshots` | `TEXT` | Nullable | JSON array of GUI / browser screenshot image paths. |
| 17 | `network_context` | `TEXT` | Nullable | Network details: host IP, VM proxy, CIDR scope status. |
| 18 | `result_summary` | `TEXT` | Nullable | Textual summary synthesized by the Observer. |
| 19 | `confidence` | `REAL` | Nullable | Execution confidence score in range $[0.0, 1.0]$. |
| 20 | `parent_event` | `TEXT` | Nullable | Lineage pointer to parent event ID for causal reconstruction. |

---

## Supporting Tables in `events.db`

In addition to the primary `events` table, `events.db` manages:

1. `plans` & `plan_nodes`: Hierarchical DAG task plans and execution dependencies.
2. `scope_contracts`: Active and historical cryptographic scope agreements with HMAC signatures.
3. `projects` & `project_collaborators`: Multi-operator workspace states and live presence.
4. `tool_memories`: Historical tool performance metrics (success rate, average latency) used by the Tool Selector.
5. `finding_cards`: Verified security findings (CVEs, misconfigurations, open services) with reproducible reproduction steps.
6. `artifacts`: Forensic files with MIME types, byte sizes, and cryptographic SHA-256 digests.

---

## Python Database Interface (`db.py`)

All database interactions use connection-pooled SQLite with WAL mode enabled for high concurrency:

```python
from events.db import get_connection, insert_event, query_audit_timeline

# Insert an event
event_id = insert_event(event_obj)

# Query audit timeline with multi-dimensional filtering
results, total = query_audit_timeline(
    session_id="sess_01",
    tool_id="nmap.scan.v1",
    status="error",
    limit=50
)
```
