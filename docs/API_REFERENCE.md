# KAIRO: Complete API & Protocol Reference

> **Authoritative Specification of KAIRO IPC Protocols, WebSocket Messages, & REST Endpoints**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Session Gateway WebSocket API (`ws://localhost:4000`)](#1-session-gateway-websocket-api-wslocalhost4000)
2. [Orchestrator REST API (`http://localhost:8000`)](#2-orchestrator-rest-api-httplocalhost8000)
   - [2.1 Agent Execution, Intent Classification & Lifecycle](#21-agent-execution-intent-classification--lifecycle)
   - [2.2 DAG Planner, Graph Execution & Prerequisite Evidence Gating](#22-dag-planner-graph-execution--prerequisite-evidence-gating)
   - [2.3 Tool Selection & Tool Memory](#23-tool-selection--tool-memory)
   - [2.4 Scope Contract & Authoritative Execution Gateway](#24-scope-contract--authoritative-execution-gateway)
   - [2.5 Self-Healing Cognitive Loop (Observer, Critic, Recovery)](#25-self-healing-cognitive-loop-observer-critic-recovery)
   - [2.6 Evidence Store, Finding Verification & Reports](#26-evidence-store-finding-verification--reports)
   - [2.7 Model Center, Telemetry, Dual-Model Routing & Hot-Switching](#27-model-center-telemetry-dual-model-routing--hot-switching)
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
5. [SQLite Audit Event & Trajectory Schemas](#5-sqlite-audit-event--trajectory-schemas)

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

Submits a user prompt or operational command to the autonomous agent loop with optional autonomous task mode and active scope contracts:

```json
{
  "type": "chat",
  "content": "Perform comprehensive port scan on 192.168.1.50",
  "sessionId": "sess_main_01",
  "taskId": "task_1791380123_abc",
  "modelId": "kairo-scale-2b",
  "autonomous": true,
  "mode": "autonomous_task",
  "target": "192.168.1.50",
  "scopeContract": {
    "contract_id": "scope_c89f",
    "target": "192.168.1.50",
    "targets": ["192.168.1.0/24"],
    "allowed_tool_tiers": [1, 2]
  }
}
```

#### `get_active_scope` (Query Active Scope Contract)

Requests the currently authorized cryptographic Scope Contract from the gateway or orchestrator:

```json
{
  "type": "get_active_scope"
}
```

Responses are returned via `active_scope_contract` with `signature_valid`, `targets`, `allowed_tool_tiers`, and `seconds_remaining`.

#### `tool_call` (Direct Tool Invocation via ExecutionGateway)

Invokes a specific registered ToolSpec directly through the authoritative `ExecutionGateway`. Direct tool invocations are never unvetted: they must pass all 7 security gates (registry check, schema & injection validation, Scope Contract perimeter verification, cryptographic operator token check, workflow policy, sandbox execution, and SQLite audit trail):

```json
{
  "type": "tool_call",
  "tool": "nmap.network_scan.v1",
  "args": {
    "target": "192.168.1.50",
    "ports": "80,443,22"
  },
  "sessionId": "sess_main_01",
  "taskId": "task_dev_exec_01",
  "operatorToken": "KAIRO-OP-1792000000-admin-a1b2c3d4e5f67890"
}
```

If the target is outside the active Scope Contract or if the operator token is missing or forged, the `ExecutionGateway` rejects the request before adapter instantiation with structured error codes (`403 SCOPE_VIOLATION` or `401 OPERATOR_UNAUTHORIZED`).

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

Returned when the agent loop completes a thinking/execution turn. Kairo enforces **Trustworthy Execution Results**: authentic exit codes (e.g. `1` or `127` on error, never synthesized `0`), deterministic reconstructed command lines (`command_line`), structured typed invocations (`typed_invocation`), and honest synthesis:

```json
{
  "type": "agent_response",
  "reply": "## 1. Executive Summary\nAutonomous reconnaissance completed against authorized target `192.168.1.50`. Discovered 2 active network listeners (OpenSSH 8.9 and Apache httpd 2.4). Scope boundary adherence certified.\n\n## 2. Step-by-Step Breakdown\n- **Step 1 (`nmap.scan.v1`)**: Exit code 0, 1.42s duration. Network port discovery completed.\n- **Step 2 (`nikto.scan.v1`)**: Exit code 0, 4.10s duration. Discovered outdated Apache header and missing X-Frame-Options.\n\n## 3. Verified Findings & Evidence\n- `22/tcp` (OpenSSH 8.9) - Confidence 0.95 (Verified via TCP handshake)\n- `80/tcp` (Apache 2.4) - Confidence 0.98 (Verified via HTTP banner interrogation)\n- `CVE-2023-XXXX` - Inconclusive, requires active probing.\n\n## 4. What We Can Do Next\nProceed to web application path discovery with Gobuster, perform targeted vulnerability analysis, or test credential hygiene on SSH.",
  "taskId": "task_1791380123_abc",
  "tool": {
    "id": "nmap.scan.v1",
    "version": "1.0.0",
    "name": "Nmap Network Scanner"
  },
  "command_line": "nmap -sV 192.168.1.50",
  "typed_invocation": {
    "tool": "nmap.scan.v1",
    "version": "1.0.0",
    "arguments": {
      "target": "192.168.1.50",
      "flags": "-sV"
    }
  },
  "execution": {
    "command": "nmap -sV 192.168.1.50",
    "command_line": "nmap -sV 192.168.1.50",
    "exit_code": 0,
    "stdout": "PORT   STATE SERVICE VERSION\n22/tcp open  ssh     OpenSSH 8.9\n80/tcp open  http    Apache httpd 2.4",
    "stderr": "",
    "typed_invocation": {
      "tool": "nmap.scan.v1",
      "version": "1.0.0",
      "arguments": {
        "target": "192.168.1.50",
        "flags": "-sV"
      }
    }
  },
  "next_step_recommendations": [
    {
      "tool_id": "gobuster.dir.v1",
      "label": "Web Content Discovery",
      "priority": "HIGH",
      "args": {
        "target": "http://192.168.1.50",
        "wordlist": "/usr/share/wordlists/dirb/common.txt"
      },
      "rationale": "Port 80/tcp is open with Apache 2.4. Enumerate hidden endpoints, admin panels, and API routes."
    },
    {
      "tool_id": "nikto.scan.v1",
      "label": "Web Vulnerability Audit",
      "priority": "HIGH",
      "args": {
        "target": "http://192.168.1.50"
      },
      "rationale": "Scan web server headers, outdated server components, and default files."
    },
    {
      "tool_id": "hydra.ssh.v1",
      "label": "SSH Credential Audit",
      "priority": "MEDIUM",
      "args": {
        "target": "192.168.1.50",
        "port": 22
      },
      "rationale": "Verify whether default or weak administrator credentials permit unauthorized SSH access."
    }
  ],
  "eventId": 52
}
```

*Note on Conversational Reports & Failure Badges*: Responses strictly present 4 structured sections (`Executive Summary`, `Step-by-Step Breakdown`, `Verified Findings & Evidence`, and `What We Can Do Next`) along with 3–5 click-to-run follow-up recommendations. If an execution fails (e.g. host unreachable, tool missing, or non-zero exit code), Kairo surfaces an explicit failure badge (`❌ Execution Failed`), preserves the authentic exit code (e.g. `1` for socket error, `127` for unregistered tool), and explains the actual error rather than inventing a success summary or claiming "No vulnerabilities found".

---

## 2. Orchestrator REST API (`http://localhost:8000`)

The FastAPI Orchestrator coordinates agent planning, process execution, model management, finding verification, and forensic auditing.

### 2.1 Agent Execution, Intent Classification & Lifecycle

- `POST /run`: Trigger the autonomous agent loop for a user directive. Accepts `{"message": str, "session_id": str, "prefer_llm": bool, "mode": Optional[str]}`.
- `POST /chat`: Unified conversational endpoint with dynamic intent classification. Automatically classifies directives into one of 4 interaction modes, routes to local inference without cloud fallback, synthesizes 4-section executive responses, provides 3–5 click-to-run recommendations, and tracks complete execution and inference provenance:
  - **General Conversation**: Informative cybersecurity answers with zero tools executed.
  - **Plan-Only Mode**: Structured graph decomposition without executing tools or making network requests.
  - **Operational Task Mode**: Full autonomous DAG execution by default across all approved steps when within authorized scope.
  - **Explicit Direct Tool Mode**: Executes a specific registered tool through `ExecutionGateway` after verifying arguments and scope.
- `POST /chat/stream`: Real-time Server-Sent Events (SSE) streaming endpoint for live token generation, reasoning chunks, and execution lifecycle updates.
  - **Request Body**:

    ```json
    {
      "message": "Audit 192.168.1.50 for web application flaws",
      "session_id": "sess_main_01",
      "autonomous": true,
      "target": "192.168.1.50"
    }
    ```

  - **Emitted Lifecycle SSE Event Types**:
    - `event: intent`: Classification output with target, interaction mode, and confidence score.
    - `event: plan`: Structured DAG plan nodes and dependency topology.
    - `event: thought`: Cognitive reasoning traces from local causal LM models.
    - `event: tool_start`: Notification that a tool node is being dispatched via `ExecutionGateway`.
    - `event: tool_output`: Streaming stdout/stderr chunks from process supervisor.
    - `event: tool_result`: Authentic execution results (exit code, duration, parsed facts).
    - `event: token`: Streaming markdown token fragments for the conversational response.
    - `event: recommendations`: 3–5 structured click-to-run follow-up recommendations.
    - `event: done`: Execution complete signal with final state summary and trajectory ID.
- `POST /intent`: Standalone intent classifier endpoint. Analyzes user directives and returns:

```json
{
  "intent": "task_request",
  "confidence": 0.95,
  "reasoning": "User requested an active network scan against a specific host",
  "target": "192.168.1.50",
  "extracted_entities": {
    "target": "192.168.1.50",
    "action": "scan"
  },
  "provenance": {
    "step": "intent_classification",
    "model": "kairo-grpo-final",
    "backend": "transformers_local",
    "timestamp": "2026-10-20T10:30:00Z"
  }
}
```

- `GET /health`: Orchestrator health check, uptime, memory, database connection, and local model runtime readiness status.
- `GET /tools`: Return all registered ToolSpecs loaded from `registry/tools/`.

---

### 2.2 DAG Planner, Graph Execution & Prerequisite Evidence Gating

- `POST /planner/decompose`: Decompose an operational goal into a validated Directed Acyclic Graph (DAG) plan with dependency tracking and topological ordering. Accepts `{"goal": str, "session_id": str, "prefer_llm": bool}`.
- `GET /planner/plans`: List all created DAG plans across sessions.
- `GET /planner/plans/{plan_id}`: Retrieve graph nodes, dependencies, and execution states for a specific plan.
- `GET /planner/plans/{plan_id}/ready`: Return all unblocked nodes ready for immediate parallel or serial execution.
- `POST /planner/plans/{plan_id}/nodes/{node_id}/status`: Update node status (`PENDING`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`, `BLOCKED`).
- `POST /planner/plans/{plan_id}/execute` or `POST /planner/plans/{plan_id}/run`: Execute all nodes in the DAG in strict topological order using the `DAGController`. All node executions route through `ExecutionGateway.execute()`. Enforces:
  - **Prerequisite Evidence Gating**: Subsequent dependent nodes (e.g. web scanners, brute-force tools) are executed only if prerequisite observations were confirmed (e.g. verified open HTTP ports).
  - **Dynamic DAG Output Chaining (`_resolve_arguments_from_evidence`)**: Resolves runtime arguments (discovered IPs, open ports, web base URLs) dynamically from verified facts emitted by upstream dependency nodes.
  - **Mid-Execution Attack Surface Adaptation (`_adapt_plan_if_new_attack_surface`)**: Inspects live verified findings and injects specialized downstream evaluation nodes dynamically (e.g. injecting `nikto.scan.v1` upon port 80/443 discovery or `hydra.ssh.v1` upon port 22 discovery).
  - **Failure Containment**: If a node fails (`exit_code != 0`), observation ingestion skips the failed run to prevent polluting downstream context.
  - **Recovery Lineage**: Failed nodes record compensatory `recovery_path` traces.
  - **Truthful Terminal States**: Plans terminate at strictly defined, evidence-based states: `COMPLETED` (all required nodes succeeded), `PARTIAL` (some succeeded), `FAILED` (critical path failed), `BLOCKED` (stopped by policy or scope), or `INCONCLUSIVE` (insufficient evidence gathered).
- `POST /planner/plans/{plan_id}/nodes/{node_id}/execute`: Execute a single discrete node.
- `POST /planner/run`: Decompose and immediately execute a multi-step DAG in a single API call (defaults to autonomous multi-step execution).
- `GET /planner/plans/{plan_id}/report`: Generate a structured report summarizing execution of the plan, clearly distinguishing confirmed findings, refuted findings, and unresolved checks.

---

### 2.3 Tool Selection & Tool Memory

- `POST /tools/select`: Evaluate candidate tools against requirements and return top 3 choices with 7-dimensional scoring breakdown.
- `GET /tools/memory`: Retrieve historical performance metrics for all tools (success rate, average latency, error counts).
- `GET /tools/memory/{tool_id}`: Retrieve detailed memory profile for a specific tool.

---

### 2.4 Scope Contract & Authoritative Execution Gateway

- `GET /scope/active`: Retrieve current active cryptographic Scope Contract.
- `POST /scope/contract`: Authorize and register a new Scope Contract signed with HMAC-SHA256 or Ed25519.
- `GET /scope/contracts`: List historical and active scope contracts.
- `POST /scope/validate`: Cryptographically validate an execution request against active CIDR targets, tool tiers, and time windows.
- `POST /gateway/execute`: Direct REST entry point to `ExecutionGateway.execute()`. Enforces the 7 authoritative security gates:
  1. **Registry Verification**: Rejects unregistered tools (`127 TOOL_NOT_FOUND`).
  2. **Schema & Injection Defense**: Rejects command injection characters and populates default parameters (`400 VALIDATION_ERROR`).
  3. **Scope Contract Perimeter**: Validates allowed CIDRs and tool privilege tier (`403 SCOPE_VIOLATION`). Evaluated before any workflow checks.
  4. **Cryptographic Operator Token**: Validates HMAC token `KAIRO-OP-<timestamp>-<role>-<hex>` (`401 OPERATOR_UNAUTHORIZED`).
  5. **Broad Command Workflow Policy**: Verifies cryptographic workflow token for Tier 3 tools (`403 UNAPPROVED_COMMAND_EXECUTION`).
  6. **Sandbox Process Execution**: Subprocess or VM worker execution with process supervision and timeout enforcement.
  7. **Forensic Audit Logging**: 20-field SQLite event log written to `events.db`.

---

### 2.5 Self-Healing Cognitive Loop (Observer, Critic, Recovery)

- `POST /observer/observe`: Parse raw execution stdout/stderr into normalized `ObservationFact` entities.
- `POST /critic/evaluate`: Evaluate execution results against success signals, exit codes, and hallucination heuristics.
- `POST /recovery/recover`: Generate compensatory recovery actions when a tool fails or produces unusable output.

---

### 2.6 Evidence Store, Finding Verification & Reports

- `GET /evidence/findings`: List all security findings (CVEs, exposed services, misconfigurations).
- `POST /evidence/findings`: Ingest a finding card with severity, CVSS, and reproduction steps.
- `GET /evidence/findings/{finding_id}`: Retrieve full finding details and associated forensic artifacts.
- `POST /evidence/ingest-plan/{plan_id}`: Automatically ingest all outputs and facts from a completed DAG plan into the evidence store.
- `POST /evidence/reports/generate`: Generate an executive markdown or PDF audit report with causal recovery narratives.
- `GET /evidence/artifacts`: List all stored forensic artifacts with MIME types and SHA-256 hashes.

#### Active Finding Verification Engine (`FindingVerifier`)

Kairo provides active, live verification of security findings through scope-gated probes:

- `GET /findings`: Query findings across the active workspace with multi-attribute filtering:
  - Query parameters: `status` (`verified`, `refuted`, `inconclusive`, `unverified`), `min_confidence` (`0.0`-`1.0`), `severity` (`info`, `low`, `medium`, `high`, `critical`), `limit`.
- `GET /findings/{finding_id}`: Retrieve a single finding by ID, including verification state, timestamp, and probe latency:

```json
{
  "id": "find_80_http_open",
  "title": "Open Port 80/tcp (HTTP)",
  "severity": "medium",
  "confidence": 0.95,
  "verified": true,
  "verification_status": "verified",
  "verification_details": "Connected to 192.168.1.50:80 in 14.2ms. HTTP banner: Apache/2.4.52",
  "verified_at": "2026-10-20T10:32:00Z"
}
```

- `POST /findings/{finding_id}/verify`: Trigger an active, live verification probe against the finding:
  - **Scope Gate**: Probes are strictly checked against the HMAC `ScopeContract`. If the target is out of scope, the probe is rejected deterministically with status `"blocked_out_of_scope"`.
  - **Live Verification Techniques**: Raw TCP socket connect handshake with microsecond latency measurement, HTTP/HTTPS banner interrogation, and service signature checks.
  - **Confidence Adjustment**: Confirmed findings boost confidence by `+0.2` (capped at `1.0`); refuted findings penalize confidence by `-0.4` (floored at `0.0`).
  - **Evidence Ingestion**: Emits an `AnalyticEvidence` record and logs the verification to the audit store.
  - Response:

    ```json
    {
      "finding_id": "find_80_http_open",
      "verified": true,
      "status": "verified",
      "latency_ms": 14.2,
      "evidence": "Connected to 192.168.1.50:80 in 14.2ms. HTTP banner: Apache/2.4.52",
      "confidence": 0.95
    }
    ```

---

### 2.7 Model Center, Telemetry, Dual-Model Routing & Hot-Switching

- `GET /model-center`: Retrieve real-time VRAM, RAM, CPU utilization, active model ID, and latency telemetry.
- `GET /models/status` & `GET /api/models/active`: Retrieve current active language model configuration, loaded model weights, parameters, and primary/fallback state.
- `GET /models/benchmark`: Retrieve local model benchmark metrics, golden suite pass rates, and evaluation history.
- `GET /models/memory`: Retrieve KV-cache memory usage and context window limits.
- `GET /models/evolution`: Retrieve model evolution cycle progress and proposal states.
- `POST /api/models/switch`: Hot-swap active model backend (e.g. `kairo-scale-1.5b-grpo` $\leftrightarrow$ `qwen2.5-coder-7b`) without server restart.

#### Dual-Model Local Routing & Audit Provenance

To guarantee deterministic autonomy while remaining strictly local and air-gapped:

- **Primary Model**: Custom fine-tuned local weights trained on ToolSpec schemas (e.g. `kairo-scale-1.5b-grpo`).
- **Local Fallback Model**: Secondary local model (e.g. `Qwen2.5-Coder-7B-Instruct`) automatically invoked if the primary encounter schema parsing errors.
- **Audit 6-Tuple**: Every model response records a 6-tuple audit object in the execution trace:
  `{"model_id": str, "version": str, "prompt_format": str, "adapter": str, "benchmark_score": float, "inference_source": "primary" | "fallback"}`.

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

## 5. SQLite Audit Event & Trajectory Schemas

Table definitions in [`events/events.db`](file:///c:/New%20Volume%20(D)/dev/events) and [`events/schema.sql`](file:///c:/New%20Volume%20(D)/dev/events/schema.sql):

### 5.1 Events Table (20 Columns)

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

### 5.2 Trajectories Table

Stores multi-step autonomous execution runs, input goals, dynamically chained steps, and follow-up recommendations for automatic training dataset curation:

```sql
CREATE TABLE IF NOT EXISTS trajectories (
    trajectory_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    plan_id TEXT,
    goal TEXT NOT NULL,
    target TEXT,
    steps TEXT NOT NULL DEFAULT '[]',
    recommendations TEXT NOT NULL DEFAULT '[]',
    success INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories(session_id);
CREATE INDEX IF NOT EXISTS idx_trajectories_plan ON trajectories(plan_id);
CREATE INDEX IF NOT EXISTS idx_trajectories_success ON trajectories(success);
```
