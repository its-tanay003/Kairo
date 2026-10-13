# KAIRO: Complete API & Protocol Reference

> **Authoritative Specification of KAIRO IPC Protocols, WebSocket Messages, & REST Endpoints**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Session Gateway WebSocket API (`ws://localhost:4000`)](#1-session-gateway-websocket-api-wslocalhost4000)
   - [1.1 Connection & Handshake](#11-connection--handshake)
   - [1.2 Client-to-Server Messages](#12-client-to-server-messages)
   - [1.3 Server-to-Client Messages](#13-server-to-client-messages)
2. [Orchestrator REST API (`http://localhost:8000`)](#2-orchestrator-rest-api-httplocalhost8000)
   - [2.1 Agent Execution & Lifecycle](#21-agent-execution--lifecycle)
   - [2.2 DAG Planner & Decomposition](#22-dag-planner--decomposition)
   - [2.3 Model Center & Hardware Telemetry](#23-model-center--hardware-telemetry)
   - [2.4 Forensic Event Store](#24-forensic-event-store)
   - [2.5 Evidence Store & Finding Cards](#25-evidence-store--finding-cards)
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
  "timestamp": "2026-10-13T16:30:20.100Z"
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

#### `planner_decompose` (Decompose Goal)
Requests the DAG engine to generate an ordered, dependency-checked execution plan:
```json
{
  "type": "planner_decompose",
  "goal": "Conduct penetration test on target 192.168.1.50 with parallel roots",
  "sessionId": "sess_main_01",
  "prefer_llm": true
}
```

---

### 1.3 Server-to-Client Messages

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
    "duration_ms": 2740
  },
  "toolSelection": {
    "selected_tool": {
      "tool_id": "nmap.scan.v1",
      "rank": 1,
      "total_score": 0.88
    },
    "selection_reason": "High semantic affinity for port scanning directive."
  }
}
```

#### `tool_event` (Live Process Telemetry)
Streamed in real-time while a long-running process executes inside the Kali sandbox:
```json
{
  "type": "tool_event",
  "taskId": "task_1791380123_abc",
  "event_id": 52,
  "status": "running",
  "chunk": "Discovered open port 22/tcp on 192.168.1.50\n"
}
```

---

## 2. Orchestrator REST API (`http://localhost:8000`)

The Orchestrator is a Python 3.12+ FastAPI application managing the agent reasoning, DAG planner, model inference, and audit events.

### 2.1 Agent Execution & Lifecycle

#### `POST /run`
Triggers the autonomous agent loop for a given session.
- **Request Body**:
  ```json
  {
    "session_id": "sess_main_01",
    "message": "Enumerate web vulnerabilities on 192.168.1.50"
  }
  ```
- **Response**:
  ```json
  {
    "status": "success",
    "session_id": "sess_main_01",
    "reply": "Identified Apache 2.4 web server. Running nikto vulnerability assessment.",
    "event_id": 53
  }
  ```

#### `GET /vm/status`
Returns real-time status of the Kali Linux VM worker.
- **Response**:
  ```json
  {
    "name": "Kali-Worker-Sandbox",
    "running": true,
    "vm_state": "running",
    "worker_online": true,
    "snapshots_count": 3
  }
  ```

---

### 2.2 DAG Planner & Decomposition

#### `POST /planner/decompose`
Generates a multi-step execution plan represented as a Directed Acyclic Graph (DAG).
- **Request Body**:
  ```json
  {
    "goal": "Conduct penetration test on target 192.168.1.50",
    "session_id": "sess_main_01"
  }
  ```
- **Response**:
  ```json
  {
    "plan_id": "plan_1791387767_7225",
    "goal": "Conduct penetration test on target 192.168.1.50",
    "total_nodes": 7,
    "parallel_roots": 2,
    "convergence_nodes": 1,
    "nodes": [
      {
        "id": "node_net_ports",
        "tool": "network_port_scan",
        "status": "READY",
        "depends_on": []
      },
      {
        "id": "node_dns_recon",
        "tool": "dns_subdomain_discovery",
        "status": "READY",
        "depends_on": []
      }
    ]
  }
  ```

#### `GET /planner/plans`
Lists all generated plans (`?limit=10`).

#### `GET /planner/plans/{plan_id}`
Returns the complete plan graph, nodes, and execution dependencies.

#### `GET /planner/plans/{plan_id}/ready`
Returns the list of unblocked nodes ready for immediate parallel execution.

---

### 2.3 Model Center & Hardware Telemetry

#### `GET /model-center`
Returns hardware, VRAM, RAM, and model runtime diagnostics:
```json
{
  "model_id": "kairo-3.7-cyberops-q4_k_m.gguf",
  "runtime": "llama.cpp",
  "quantization": "Q4_K_M",
  "context_length": 8192,
  "role": "Autonomous Security Planning & Tool Calling",
  "server_status": "running",
  "vram": {
    "total_mb": 8192,
    "used_mb": 3410,
    "free_mb": 4782,
    "utilization_pct": 41.6
  },
  "ram": {
    "total_mb": 32768,
    "used_mb": 14200,
    "free_mb": 18568,
    "utilization_pct": 43.3
  }
}
```

---

### 2.4 Forensic Event Store

#### `GET /events`
Queries operational audit records (`?limit=50&offset=0&search=nmap`).
- **Response**:
  ```json
  {
    "total": 52,
    "events": [
      {
        "id": 52,
        "session_id": "sess_main_01",
        "task_id": "task_1791380123_abc",
        "timestamp": "2026-10-13T16:35:10Z",
        "actor": "agent",
        "tool_id": "nmap.scan.v1",
        "tool_version": "1.0.0",
        "exit_code": 0,
        "result_summary": "Discovered ports 22, 80 open on 192.168.1.50"
      }
    ]
  }
  ```

---

## 3. Kali Worker VM REST API (`http://192.168.56.x:9999`)

Runs as a systemd service inside the Kali guest VM:

- `GET /health`: Returns `{ "status": "ok", "uptime_s": 3840 }`.
- `POST /exec`: Spawns a process in the sandbox with cgroup CPU/memory caps:
  ```json
  {
    "command": "nikto -h 192.168.1.50",
    "timeout_s": 120,
    "memory_cap_mb": 512
  }
  ```
- `POST /snapshot/rollback`: Reverts the VM disk state to the baseline snapshot.

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
