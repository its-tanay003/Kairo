# /orchestrator - Autonomous Agent Engine & Cognitive Core

The `/orchestrator` subsystem is the central nervous system of Kairo. Implemented in Python with FastAPI, it coordinates the autonomous cognitive loop: translating high-level operator directives into Directed Acyclic Graph (DAG) execution plans, selecting tools via 7-dimensional scoring, enforcing cryptographic scope boundaries, evaluating execution outcomes, and self-healing upon tool failures.

---

## Subsystem Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (/run, /events)                  │
│                               (server.py)                              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Autonomous Planner (planner.py)                     │
│  - Decomposes directives into a Directed Acyclic Graph (DAG)           │
│  - Detects cycles, resolves dependencies, coordinates parallel tasks   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Hybrid Tool Selector (tool_selector.py)                  │
│  - Scores tools across 7 dimensions (category, capability, history)    │
│  - Consults persistent Tool Memory Store (/events/events.db)           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Scope Contract Authorization Gate                        │
│  - Validates HMAC-SHA256 signature and operator authorization          │
│  - Strictly verifies target IP/domain resides within allowed CIDR      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│           Process Supervisor & VM Manager (process_supervisor.py)      │
│  - Dispatches to Host Supervisor or Kali VM Worker (vm_manager.py)     │
│  - Enforces hard memory/CPU caps, timeouts, and SIGKILL kill switch    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Self-Healing Cognitive Loop (Observer & Critic)            │
│                                                                        │
│  1. Observer (observer.py): Extracts structured ObservationFacts       │
│  2. Critic (critic.py): Evaluates success vs failure criteria          │
│  3. Recovery Agent (recovery_agent.py): Proposes compensatory actions   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                Evidence Store & Reporting (reporter.py)                │
│  - Emits 20-field audit events to SQLite (/events/events.db)           │
│  - Synthesizes Finding Cards & Executive Penetration Reports           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Module Index

| Module | Purpose & Core Responsibilities |
| :--- | :--- |
| [`server.py`](server.py) | Main FastAPI application exposing REST and WebSocket endpoints for execution, process management, evidence, audit, and model evolution. |
| [`planner.py`](planner.py) | Autonomous DAG task planner. Validates dependency structures, prevents cycles, and orchestrates multi-step penetration operations. |
| [`observer.py`](observer.py) | Telemetry observer parsing raw tool stdout/stderr into structured `ObservationFact` entities (open ports, CVEs, hosts). |
| [`critic.py`](critic.py) | Evaluation critic verifying task exit codes, regex success signals, and hallucination indicators. |
| [`recovery_agent.py`](recovery_agent.py) | Self-healing engine triggering fallback tools (e.g. Nmap XML $\to$ Nmap normal parse; Nikto $\to$ WhatWeb) upon tool errors. |
| [`tool_selector.py`](tool_selector.py) | 7-dimensional scoring engine evaluating candidate tools against requirements and historical success rates. |
| [`model_evolution_controller.py`](model_evolution_controller.py) | Background engine monitoring model performance and triggering autonomous SFT refresh, tier scaling, and benchmark validation. |
| [`failover_router.py`](failover_router.py) | High-availability inference router automatically diverting prompts to secondary fallback models upon timeout or schema crash. |
| [`model_center.py`](model_center.py) | Centralized model runtime manager tracking active backends, GPU/CPU usage, and context memory. |
| [`process_supervisor.py`](process_supervisor.py) | Host process execution supervisor enforcing timeouts, memory caps, and process tree termination. |
| [`vm_manager.py`](vm_manager.py) | VirtualBox management plane managing snapshot creation, rollback, and host-to-guest networking. |
| [`kali_connector.py`](kali_connector.py) | HTTP client interfacing with the remote Kali Linux guest worker agent on port 9999. |
| [`vnc_server.py`](vnc_server.py) | Internal RFB proxy bridging desktop GUI streams to noVNC web sockets. |
| [`evidence_store.py`](evidence_store.py) | Forensic artifact store managing 6 artifact classes with cryptographic SHA-256 integrity checks. |
| [`reporter.py`](reporter.py) | Comprehensive markdown and PDF audit report generator with finding cards and causal recovery chains. |
| [`workspace_manager.py`](workspace_manager.py) | Manages ephemeral per-session working directories and artifact storage. |
| [`schema_gen.py`](schema_gen.py) | Compiles runtime GBNF grammars for `llama.cpp` to constrain model generation strictly to valid JSON. |

---

## Running the Orchestrator

```bash
# Start the FastAPI server on port 8000
python -m uvicorn orchestrator.server:app --host 0.0.0.0 --port 8000 --reload
```
