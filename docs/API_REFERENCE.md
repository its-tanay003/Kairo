# KAIRO: Complete API & Protocol Reference

> **Authoritative Specification of KAIRO IPC Protocols, WebSocket Messages, & REST Endpoints**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Session Gateway WebSocket API (`ws://localhost:4000`)](#1-session-gateway-websocket-api-wslocalhost4000)
2. [Orchestrator REST API (`http://localhost:8000`)](#2-orchestrator-rest-api-httplocalhost8000)
   - [2.1 Agent Execution & Lifecycle](#21-agent-execution--lifecycle)
   - [2.2 DAG Planner & Graph Execution](#22-dag-planner--graph-execution)
   - [2.3 Tool Selection & Tool Memory](#23-tool-selection--tool-memory)
   - [2.4 Scope Contract Authorization Gate](#24-scope-contract-authorization-gate)
   - [2.5 Self-Healing Cognitive Loop (Observer, Critic, Recovery)](#25-self-healing-cognitive-loop-observer-critic-recovery)
   - [2.6 Evidence Store, Finding Cards & Reports](#26-evidence-store-finding-cards--reports)
   - [2.7 Model Center, Telemetry & Model Switching](#27-model-center-telemetry--model-switching)
   - [2.8 Model Evolution Controller & Autonomous Policies](#28-model-evolution-controller--autonomous-policies)
   - [2.9 Dataset Curation & Model Training Pipeline](#29-dataset-curation--model-training-pipeline)
   - [2.10 Benchmark Leaderboard & Multi-Model Sweeps](#210-benchmark-leaderboard--multi-model-sweeps)
   - [2.11 Process Supervision & Terminal Streaming](#211-process-supervision--terminal-streaming)
   - [2.12 Virtualization Sandbox & Snapshot Management](#212-virtualization-sandbox--snapshot-management)
   - [2.13 GUI Tool Adapters & Playwright Browser Security](#213-gui-tool-adapters--playwright-browser-security)
   - [2.14 Multi-User Projects, Presence & Workspaces](#214-multi-user-projects-presence--workspaces)
   - [2.15 Audit Explorer & Forensic Timeline](#215-audit-explorer--forensic-timeline)
3. [Kali Worker VM REST API (`http://192.168.56.x:9999`)](#3-kali-worker-vm-rest-api-http19216856x9999)
4. [noVNC RFB Desktop Streaming (`ws://localhost:6080`)](#4-novnc-rfb-desktop-streaming-wslocalhost6080)
5. [SQLite Audit Event Schema (20 Columns)](#5-sqlite-audit-event-schema-20-columns)

---

## 1. Session Gateway WebSocket API (`ws://localhost:4000`)

The Gateway is a Node.js TypeScript multiplexer responsible for session routing, authentication tokens, and real-time streaming between the UI client and the Orchestrator.

### 1.1 Connection & Handshake

Upon establishing a WebSocket connection to `ws://localhost:4000`, the Gateway responds with an immediate session handshake:

```json
{
  "type": "handshake",
  "sessionId": "sess_main_01",
  "authToken": "kairo_token_9f81a7b8e19c",
  "timestamp": "2026-10-17T16:30:20.100Z"
}
```

### 1.2 Client-to-Server Messages

#### `chat` (Submit Directive)

Submits a user prompt or operational command to the autonomous agent loop:

```json
{
  "type": "chat",
  "content": "Perform comprehensive port scan on 192.168.1.50",
  "sessionId": "sess_main_01",
  "taskId": "task_1791380123_abc"
}
```

#### `tool_call` (Direct Sandbox Invocation)

Bypasses the LLM agent loop to execute a specific ToolSpec directly in the Kali worker sandbox:

```json
{
  "type": "tool_call",
  "tool": "kali.exec.v1",
  "args": {
    "command": "nmap",
    "args": ["-sV", "-p", "80,443,22", "192.168.1.50"]
  },
  "sessionId": "sess_main_01",
  "taskId": "task_dev_exec_01"
}
```

#### `subscribe_terminal` (Stream Output)

Subscribes to live ANSI terminal output chunks emitted by an active process supervisor:

```json
{
  "type": "subscribe_terminal",
  "taskId": "task_1791380123_abc"
}
```

#### `presence_heartbeat` (Multi-User Collaboration)

Broadcasts operator focus, cursor position, and active tab:

```json
{
  "type": "presence_heartbeat",
  "projectId": "proj_corp_audit_01",
  "userId": "operator_alice",
  "activeTab": "task_graph"
}
```

---

### 1.3 Server-to-Client Messages

#### `agent_thought` (Extended Thinking Accordion)

Emits cognitive reasoning traces in real time:

```json
{
  "type": "agent_thought",
  "thought": "Decomposing directive into 2 reconnaissance phases...",
  "duration_ms": 1240
}
```

#### `agent_response` (Agent Completion)

Returned when the agent loop completes a thinking/execution turn:

```json
{
  "type": "agent_response",
  "reply": "Network reconnaissance completed for target 192.168.1.50.",
  "taskId": "task_1791380123_abc",
  "tool": {
    "id": "nmap.scan.v1",
    "version": "1.0.0",
    "name": "Nmap Network Scanner"
  },
  "execution": {
    "command": "nmap -sV 192.168.1.50",
    "exit_code": 0,
    "stdout": "PORT   STATE SERVICE VERSION\n22/tcp open  ssh     OpenSSH 8.9\n80/tcp open  http    Apache httpd 2.4",
    "stderr": ""
  },
  "eventId": 52
}
```

---

## 2. Orchestrator REST API (`http://localhost:8000`)

The FastAPI Orchestrator coordinates agent planning, process execution, model management, and forensic auditing.

### 2.1 Agent Execution & Lifecycle

- `POST /run`: Trigger the agent loop for a user directive.
- `GET /health`: Orchestrator health check, uptime, and database connection status.
- `GET /tools`: Return all 27 registered ToolSpecs loaded from `registry/tools/`.

---

### 2.2 DAG Planner & Graph Execution

- `POST /planner/decompose`: Decompose an operational goal into an ordered DAG plan.
- `GET /planner/plans`: List all created DAG plans.
- `GET /planner/plans/{plan_id}`: Retrieve graph nodes and dependency structure for a specific plan.
- `GET /planner/plans/{plan_id}/ready`: Return all unblocked nodes ready for immediate execution.
- `POST /planner/plans/{plan_id}/nodes/{node_id}/status`: Update node status (`READY`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`).
- `POST /planner/plans/{plan_id}/execute`: Execute all nodes in the DAG in topological order.
- `POST /planner/plans/{plan_id}/nodes/{node_id}/execute`: Execute a single discrete node.
- `GET /planner/plans/{plan_id}/report`: Generate a structured report summarizing execution of the plan.

---

### 2.3 Tool Selection & Tool Memory

- `POST /tools/select`: Evaluate candidate tools against requirements and return top 3 choices with 7-dimensional scoring breakdown.
- `GET /tools/memory`: Retrieve historical performance metrics for all tools (success rate, average latency, error counts).
- `GET /tools/memory/{tool_id}`: Retrieve detailed memory profile for a specific tool.

---

### 2.4 Scope Contract Authorization Gate

- `GET /scope/active`: Retrieve current active cryptographic Scope Contract.
- `POST /scope/contract`: Authorize and register a new Scope Contract signed with HMAC-SHA256.
- `GET /scope/contracts`: List historical and active scope contracts.
- `POST /scope/validate`: Cryptographically validate an execution request against active CIDR targets, tool tiers, and time windows.

---

### 2.5 Self-Healing Cognitive Loop (Observer, Critic, Recovery)

- `POST /observer/observe`: Parse raw execution stdout/stderr into normalized `ObservationFact` entities.
- `POST /critic/evaluate`: Evaluate execution results against success signals, exit codes, and hallucination heuristics.
- `POST /recovery/recover`: Generate compensatory recovery actions when a tool fails or produces unusable output.

---

### 2.6 Evidence Store, Finding Cards & Reports

- `GET /evidence/findings`: List all verified security findings (CVEs, exposed services, misconfigurations).
- `POST /evidence/findings`: Ingest a verified finding card with severity, CVSS, and reproduction steps.
- `GET /evidence/findings/{finding_id}`: Retrieve full finding details and associated forensic artifacts.
- `POST /evidence/ingest-plan/{plan_id}`: Automatically ingest all outputs and facts from a completed DAG plan into the evidence store.
- `POST /evidence/reports/generate`: Generate an executive markdown or PDF audit report with causal recovery narratives.
- `GET /evidence/artifacts`: List all stored forensic artifacts with MIME types and SHA-256 hashes.

---

### 2.7 Model Center, Telemetry & Model Switching

- `GET /model-center`: Retrieve real-time VRAM, RAM, CPU utilization, active model ID, and latency telemetry.
- `GET /api/models/active`: Retrieve current active language model configuration.
- `POST /api/models/switch`: Hot-swap active model backend (e.g. `Qwen3-Coder-30B-A3B-Instruct` $\to$ `kairo-scale-2b`) without server restart.

---

### 2.8 Model Evolution Controller & Autonomous Policies

- `GET /evolution/status`: Retrieve controller operational status, active cycle number, and last evaluation timestamp.
- `GET /evolution/proposals`: List pending model training and promotion proposals.
- `GET /evolution/policy`: View active evolution policy rules from `orchestrator/evolution_policy.yaml`.
- `POST /evolution/cycle`: Trigger an immediate model evolution evaluation cycle.
- `POST /evolution/start`: Start the autonomous evolution background daemon.
- `POST /evolution/stop`: Stop the autonomous evolution daemon.
- `POST /evolution/reload-policy`: Hot-reload evolution policy from YAML.
- `POST /evolution/proposals/{proposal_id}/approve`: Manually approve a pending model promotion proposal.
- `POST /evolution/proposals/{proposal_id}/dismiss`: Dismiss a model promotion proposal.
- `GET /evolution/evaluations`: List historical model evaluation metrics across training cycles.

---

### 2.9 Dataset Curation & Model Training Pipeline

- `GET /training/dataset/stats`: Retrieve statistics on harvested SFT dialogues, DPO preference pairs, and token counts.
- `GET /training/dataset/examples`: List training dataset examples with pagination and mode filtering (`sft` vs `dpo`).
- `POST /training/dataset/curate`: Flag, annotate, or reject an example for model training.
- `POST /training/dataset/clean`: Run automated schema cleaning filter across raw training data.
- `POST /training/dataset/expand`: Trigger synthetic task expansion across registered ToolSpecs.
- `GET /training/jobs`: List active and historical training jobs.
- `POST /training/jobs/start`: Launch an asynchronous SFT, DPO, or GRPO training job.
- `GET /training/jobs/{job_id}`: Retrieve training job status, loss curve telemetry, and current epoch.
- `POST /training/jobs/{job_id}/stop`: Terminate a running training job.
- `GET /training/checkpoints`: List saved model checkpoints with parameter counts and validation scores.

---

### 2.10 Benchmark Leaderboard & Multi-Model Sweeps

- `GET /benchmark/leaderboard`: Retrieve composite leaderboard rankings across all evaluated models.
- `GET /benchmark/runs/{run_id}`: Retrieve granular task-by-task results for a specific benchmark run.
- `POST /benchmark/run`: Trigger a benchmark evaluation on the active model (Golden 50 or Full 120 suite).
- `POST /benchmark/sweep`: Trigger an automated sweep evaluating a list of model IDs sequentially.
- `GET /benchmark/public-card`: Retrieve a cryptographically certified public benchmark score card with SHA-256 digest.
- `GET /benchmark/sweeps/{sweep_id}`: Retrieve comparative evaluation matrix across models for a specific sweep.
- `GET /benchmark/sweep-comparison`: Retrieve latest side-by-side model comparison metrics.

---

### 2.11 Process Supervision & Terminal Streaming

- `GET /processes`: List all active child processes under supervision.
- `POST /kill`: Terminate an active process by task ID using SIGKILL.
- `POST /process/pause/{task_id}`: Pause a running process with SIGSTOP.
- `POST /process/resume/{task_id}`: Resume a paused process with SIGCONT.
- `POST /process/stop/{task_id}`: Stop process and all child descendants.
- `POST /process/retry/{task_id}`: Re-run a failed process with identical inputs.
- `GET /process/tree`: Retrieve hierarchical process tree for all active tasks.
- `GET /process/poll/{task_id}`: Poll current stdout/stderr delta and execution state.

---

### 2.12 Virtualization Sandbox & Snapshot Management

- `GET /vm/status`: Real-time status of the VirtualBox Kali Linux VM.
- `GET /vm/snapshots`: List available VM disk snapshots.
- `POST /vm/snapshot`: Create a named disk snapshot prior to executing high-privilege operations.
- `POST /vm/rollback`: Instantly revert guest VM disk state to a baseline snapshot.
- `POST /vm/execute`: Execute a typed ToolSpec inside the isolated guest worker.
- `POST /vm/kill/{task_id}`: Terminate a running task inside the VM.

---

### 2.13 GUI Tool Adapters & Playwright Browser Security

- `GET /gui/adapters`: List available Tier 3 GUI tools (Burp Suite, Wireshark, ZAP).
- `POST /gui/execute`: Launch an interactive GUI tool inside the virtual display.
- `GET /gui/state/{tool_id}`: Retrieve window coordinates and running state of a GUI tool.
- `POST /gui/screenshot/{tool_id}`: Capture a high-resolution screenshot of a specific GUI tool window.
- `POST /gui/stop/{tool_id}`: Close a running GUI tool.
- `GET /browser/state`: Retrieve current URL, DOM title, and viewport state of the Playwright security browser.
- `GET /browser/history`: Retrieve navigation history and captured HTTP requests.
- `POST /browser/execute`: Execute a browser action (navigate, click, type, extract DOM, capture storage).
- `POST /browser/screenshot`: Capture a screenshot of the active browser viewport.
- `POST /browser/stop`: Terminate the headless browser session.

---

### 2.14 Multi-User Projects, Presence & Workspaces

- `GET /projects`: List shared team projects.
- `POST /projects`: Create a new collaborative project workspace.
- `GET /projects/{project_id}`: Retrieve project metadata, shared state, and target scopes.
- `PUT /projects/{project_id}/state`: Synchronize shared workspace state across connected operators.
- `POST /projects/{project_id}/collaborators`: Add a collaborator with designated role (`admin`, `operator`, `auditor`).
- `DELETE /projects/{project_id}/collaborators/{user_id}`: Remove a collaborator.
- `GET /projects/{project_id}/presence`: Retrieve active operator cursors and view locations.
- `POST /workspaces/provision`: Provision an isolated scratch directory for an operator session.
- `GET /workspaces`: List active workspaces.
- `POST /workspaces/{workspace_id}/terminate`: Securely shred and delete workspace files.

---

### 2.15 Audit Explorer & Forensic Timeline

- `GET /audit/timeline`: Query immutable event timeline with filters for session, task, actor, tool, exit code, and time range.
- `GET /audit/stats`: Retrieve high-level operational statistics (total runs, error rates, average latency, top tools).
- `GET /audit/model-evolution-timeline`: Query chronological timeline of model evolution decisions and training triggers.
- `GET /audit/model-evolution-stats`: Summary statistics of autonomous model training frequency and accuracy gains.

---

## 3. Kali Worker VM REST API (`http://192.168.56.x:9999`)

Runs as a background daemon inside the isolated Kali Linux guest VM (`vm/worker_agent.py`):

- `GET /health`: Health status and guest CPU/RAM telemetry.
- `POST /execute`: Execute a ToolSpec command line inside the VM with hard resource caps.
- `GET /stream/{task_id}`: Server-Sent Events (SSE) streaming real-time stdout and stderr.
- `GET /poll/{task_id}`: Incremental polling endpoint for non-streaming clients.
- `GET /process/tree`: Hierarchical process tree inspection inside the guest.
- `POST /process/pause/{task_id}`: Pause execution with SIGSTOP.
- `POST /process/resume/{task_id}`: Resume execution with SIGCONT.
- `POST /process/stop/{task_id}`: Terminate execution with SIGKILL.
- `GET /artifacts/{task_id}`: List produced artifact files.
- `POST /artifacts/verify`: Verify artifact SHA-256 digest against tampering.

---

## 4. noVNC RFB Desktop Streaming (`ws://localhost:6080`)

The Orchestrator includes a built-in RFB (Remote Framebuffer) WebSocket gateway:

- **Protocol**: RFB 003.008 over WebSockets.
- **Port**: `6080`.
- **Canvas Resolution**: `1024x768`, 24-bit truecolor.
- **Client**: Embedded noVNC HTML5 canvas viewer inside [`ScreenPanel.tsx`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/components/ScreenPanel.tsx).

---

## 5. SQLite Audit Event Schema (20 Columns)

Table definition in [`events/events.db`](file:///c:/New%20Volume%20(D)/dev/events):

```sql
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

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool_id);
```
