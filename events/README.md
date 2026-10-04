# /events - SQLite Event Store

Stores strictly typed execution events emitted by the agent orchestrator and tools.

## Schema Fields
- `session_id`: Unique identifier for the user or agent session (TEXT NOT NULL)
- `task_id`: Identifier for the discrete unit of work (TEXT NOT NULL)
- `timestamp`: UTC ISO-8601 creation timestamp (TEXT NOT NULL)
- `actor`: Entity initiating or executing the action, e.g. `agent`, `user`, `orchestrator` (TEXT NOT NULL)
- `tool_id`: Identifier of the tool executed, if applicable (TEXT)
- `tool_version`: Semantic version of the tool invoked (TEXT)
- `requested_args`: Raw arguments received for the tool invocation (JSON/TEXT)
- `normalized_args`: Validated or sanitized arguments (JSON/TEXT)
- `process_id`: OS process ID executing the tool (INTEGER)
- `start_time`: UTC ISO-8601 execution start timestamp (TEXT)
- `end_time`: UTC ISO-8601 execution end timestamp (TEXT)
- `exit_code`: Process or action exit status code (INTEGER)
- `stdout_ref`: Reference or pointer to captured stdout (TEXT)
- `stderr_ref`: Reference or pointer to captured stderr (TEXT)
- `artifact_refs`: JSON array of artifact URIs/paths produced (JSON/TEXT)
- `screenshots`: JSON array of screenshot paths/URIs (JSON/TEXT)
- `network_context`: JSON object detailing network environment/proxy (JSON/TEXT)
- `result_summary`: Short textual summary of the result (TEXT)
- `confidence`: Confidence score in [0.0, 1.0] (REAL)
- `parent_event`: ID or UUID of the causal parent event for lineage (TEXT)
