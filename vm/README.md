# /vm - Isolated Virtualization & Worker Agent Subsystem

The `/vm` subsystem provides zero-trust execution isolation for Kairo. All security tools that perform network interactions, active scanning, or payload testing execute inside a dedicated, disposable VirtualBox Kali Linux virtual machine managed by the Orchestrator.

---

## Architecture & Containment Model

```text
┌────────────────────────────────────────────────────────┐
│                   Host Operating System                │
│  - Orchestrator (/orchestrator/server.py)             │
│  - VM Manager (/orchestrator/vm_manager.py)           │
│  - VBoxManage control plane (snapshots, rollback)      │
└───────────────────────────┬────────────────────────────┘
                            │ Host-Only Network (192.168.56.0/24)
                            ▼
┌────────────────────────────────────────────────────────┐
│             Isolated Kali Linux Guest VM               │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │       Worker Agent (vm/worker_agent.py:9999)      │  │
│  │  - Typed ToolSpec execution requests             │  │
│  │  - Hard resource caps (CPU, RAM, Disk, Time)     │  │
│  │  - Process Supervisor (SIGSTOP, SIGCONT, SIGKILL)│  │
│  │  - SSE stream & ANSI terminal stdout/stderr      │  │
│  │  - SHA-256 artifact verification                 │  │
│  └────────────────────────┬─────────────────────────┘  │
│                           │ Process Fork & Exec        │
│                           ▼                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │       Security Tool Binaries (Nmap, Nikto,       │  │
│  │       SQLMap, Burp Suite, Wireshark, etc.)       │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## Worker Agent API (`vm/worker_agent.py`)

The worker daemon inside the VM exposes an HTTP RPC interface on port `9999`:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | Health check verifying agent is listening and CPU/RAM status. |
| `/execute` | `POST` | Execute a typed ToolSpec with args, environment, timeout, and resource caps. |
| `/poll/{task_id}` | `GET` | Poll task execution status, exit code, stdout/stderr delta, and artifacts. |
| `/stream/{task_id}` | `GET` | Server-Sent Events (SSE) streaming real-time stdout and stderr output. |
| `/process/tree` | `GET` | Retrieve the hierarchical process tree (parent PID, children, background processes). |
| `/process/pause/{task_id}` | `POST` | Pause the running task process tree using `SIGSTOP`. |
| `/process/resume/{task_id}` | `POST` | Resume paused task process tree using `SIGCONT`. |
| `/process/stop/{task_id}` | `POST` | Forcibly terminate the task and all descendants using `SIGKILL`. |
| `/process/retry/{task_id}` | `POST` | Re-execute a failed task with original arguments. |
| `/artifacts/{task_id}` | `GET` | List produced artifact files with size and SHA-256 hashes. |
| `/artifacts/verify` | `POST` | Cryptographically verify artifact digest against tampering. |

---

## Enforced Resource Caps per Task

To prevent host resource starvation or fork-bomb attacks, the Worker Agent enforces hard resource limits:

- **Memory Bound**: Maximum 512 MB per task (configurable up to 2048 MB). Exceeding triggers automated `SIGKILL`.
- **CPU Throttling**: 95% CPU utilization ceiling.
- **Disk Cap**: Maximum 100 MB temporary disk usage per task.
- **Artifact Limits**:
  - Maximum **100 MB** single artifact file size.
  - Maximum **500 artifacts** produced per task.
  - Mandatory **SHA-256** digest computation upon file write.

---

## Automated VM Snapshot & Rollback Lifecycle

When an autonomous task declares `privilege: elevated` or modifies guest system state:

1. **Pre-Execution Snapshot**: The Orchestrator's `VMManager` issues `VBoxManage snapshot "kairo-kali" take "pre_task_<task_id>"`.
2. **Execution**: The worker agent runs the task.
3. **Critic Evaluation**:
   - If task succeeds $\to$ snapshot is retained or pruned.
   - If task fails or compromises the VM $\to$ `VBoxManage controlvm "kairo-kali" poweroff` and `VBoxManage snapshot "kairo-kali" restore "pre_task_<task_id>"`.
4. **Resumption**: Guest returns to clean baseline state in $\le 8$ seconds.

---

## Deployment & Worker Launch

Inside the Kali Linux VM:

```bash
# Start worker agent on 0.0.0.0:9999
python3 /opt/kairo/worker_agent.py
```

From host machine via automation script:

```bash
python scripts/deploy_worker.py --host 192.168.56.101 --user kali --port 9999
```
